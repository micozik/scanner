# -*- coding: utf-8 -*-
"""
patch_price.py  ——  放仓库【根目录】，和 scanner_cloud.py 同一层

╔══════════════════════════════════════════════════════════════╗
║ 【驱动价格表】—— 周期股的"售价"，报告里唯一缺的那一块        ║
║  输出：reports/驱动价格_最新.txt + 驱动价格_日期.txt          ║
╚══════════════════════════════════════════════════════════════╝

★为什么必须有它（2026-09-01~03 三次实证）★
  · 山东黄金 → 我搜到金价跌破100日均线、两周低点 → 🚫否决（救了一笔）
  · 招商轮船 → 我搜到BDI创26个月新高            → ✅通过
  · 紫金矿业 → 我搜到LME铜12,195美元处历史高位   → ✅通过
  ★三次全靠临时上网搜。9月2日我推山东黄金时【没搜】，
    只看到人民币金价日内+2.31%，就当成"金价在涨"，
    实际国际金价已跌破100日均线。用户让我再查，才自己推翻自己。★

  报告有90个行业、387个概念、651条新闻，
  ★唯独没有一张商品价格表★ —— 而商品价格才是周期股的售价。

★这张表回答的问题（AI的"死穴④"）★
  推荐任何周期股之前必须答：★它的驱动价格，此刻是涨是跌？★
    有色股 → 看沪铜/沪铝/沪锌/沪镍/沪锡
    黄金股 → 看沪金/沪银
    农业股 → 看玉米/豆粕/棉花/白糖
    养殖股 → 看生猪（★注意：豆粕玉米涨=养殖成本涨=利空★）
    石化股 → 看原油
    锂电股 → 看碳酸锂
    钢铁股 → 看螺纹/铁矿石
  ★每个品种都给：最新价 / 今日 / 5日 / 20日 / 60日 / 距60日高低点★

★安全性★
  · ★完全不改 scanner_cloud.py / scanner_usa.py / scan.yml★
  · 只写 reports/驱动价格_*.txt
  · 100秒硬预算 + 6线程并发 + 全程异常捕获
  · 取不到就写【无数据】，★绝不编数★（铁律Y）
  · 实测应在 20-40 秒，主扫描余量足够
"""

import io
import os
import time
import datetime
import traceback
from concurrent.futures import ThreadPoolExecutor

OUTDIR = "reports"
TIME_BUDGET = 100.0
WORKERS = 6

_T0 = time.time()
_LOG = []

# 品种表：新浪主力连续代码 → (中文名, 它是谁的售价, 谁受损)
SYMBOLS = [
    # ── 有色 ──
    ("CU0", "沪铜",   "紫金矿业/江西铜业/铜陵有色", "电缆/家电(成本)"),
    ("AL0", "沪铝",   "中国铝业/云铝股份",         "汽车/包装(成本)"),
    ("ZN0", "沪锌",   "驰宏锌锗/白银有色",         "镀锌钢材(成本)"),
    ("NI0", "沪镍",   "青山系/华友钴业",           "不锈钢/三元电池(成本)"),
    ("SN0", "沪锡",   "锡业股份",                 "焊料/电子(成本)"),
    ("PB0", "沪铅",   "白银有色/驰宏锌锗",         "铅酸电池(成本)"),
    # ── 贵金属 ──
    ("AU0", "沪金",   "山东黄金/中金黄金/紫金矿业", "珠宝零售(成本)"),
    ("AG0", "沪银",   "盛达资源/银泰黄金",         "光伏银浆(成本)"),
    # ── 能源化工 ──
    ("SC0", "原油",   "中国石油/中海油/油运",       "航空/化纤/塑料(成本)"),
    ("FG0", "玻璃",   "旗滨集团/南玻A",            "地产装修(成本)"),
    ("SA0", "纯碱",   "远兴能源/三友化工",          "玻璃厂(成本)"),
    ("LC0", "碳酸锂", "天齐锂业/赣锋锂业",          "★电池厂(成本)★"),
    # ── 黑色 ──
    ("RB0", "螺纹钢", "华菱钢铁/三钢闽光",          "地产基建(成本)"),
    ("I0",  "铁矿石", "河钢资源/大中矿业",          "★钢厂(成本)★"),
    ("J0",  "焦炭",   "山西焦煤/平煤股份",          "钢厂(成本)"),
    # ── 农产品（★注意收入端/成本端相反★）──
    ("C0",  "玉米",   "★种植:登海/万向德农(收入)★", "★养殖/饲料(成本)★"),
    ("M0",  "豆粕",   "★压榨:金龙鱼(部分)★",       "★养殖:牧原/温氏(成本)★"),
    ("CF0", "棉花",   "新赛股份/新农开发",          "纺织服装(成本)"),
    ("SR0", "白糖",   "中粮糖业/南宁糖业",          "食品饮料(成本)"),
    ("LH0", "生猪",   "★牧原/温氏/新希望(收入)★",   "屠宰/food(成本)"),
]


def over():
    return (time.time() - _T0) > TIME_BUDGET


def note(s):
    _LOG.append(s)


def col(df, *names):
    for n in names:
        if n in df.columns:
            return n
    return None


def fetch_one(ak, item):
    sym, cn, up, down = item
    if over():
        return (sym, cn, up, down, None, "超时预算")
    df = None
    err = ""
    for fn in (
        lambda: ak.futures_main_sina(symbol=sym),
        lambda: ak.futures_main_sina(symbol=sym, start_date="20260101"),
    ):
        try:
            d = fn()
            if d is not None and len(d) > 5:
                df = d
                break
        except Exception as e:
            err = str(e)[:60]
    if df is None:
        return (sym, cn, up, down, None, err or "取数失败")

    try:
        c_close = col(df, "收盘价", "close", "收盘")
        c_date = col(df, "日期", "date")
        if c_close is None:
            return (sym, cn, up, down, None, "无收盘列")
        closes = [float(x) for x in df[c_close] if str(x) not in ("nan", "")]
        if len(closes) < 5:
            return (sym, cn, up, down, None, "数据太短")
        last = closes[-1]
        w = closes[-60:] if len(closes) >= 60 else closes
        r = {
            "last": last,
            "d1": (last / closes[-2] - 1) * 100 if len(closes) > 1 else None,
            "d5": (last / closes[-6] - 1) * 100 if len(closes) > 5 else None,
            "d20": (last / closes[-21] - 1) * 100 if len(closes) > 20 else None,
            "d60": (last / w[0] - 1) * 100,
            "hi": max(w), "lo": min(w),
            "date": str(list(df[c_date])[-1])[:10] if c_date else "",
        }
        r["from_hi"] = (last / r["hi"] - 1) * 100
        r["from_lo"] = (last / r["lo"] - 1) * 100
        return (sym, cn, up, down, r, "")
    except Exception as e:
        return (sym, cn, up, down, None, str(e)[:60])


def run():
    bj = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    L = []

    def w(s=""):
        L.append(s)

    w("=" * 74)
    w("💹【驱动价格表】周期股的售价 | 北京 %s" % bj.strftime("%Y-%m-%d %H:%M"))
    w("   ★推荐任何周期股之前必答：它的驱动价格，此刻是涨是跌？★")
    w("   2026-09-02 教训：推山东黄金时没查国际金价，")
    w("              只看到人民币金价日内+2.31%就当成'金价在涨'，")
    w("              实际它已跌破100日均线、两周低点。")
    w("=" * 74)

    try:
        import akshare as ak
    except Exception as e:
        w("🔴 akshare 导入失败：%s → 本表无数据" % e)
        _save(L, bj)
        return

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        res = list(ex.map(lambda it: fetch_one(ak, it), SYMBOLS))

    ok = len([r for r in res if r[4]])
    w("   取数成功 %d / %d 个品种 | 耗时 %.1f 秒"
      % (ok, len(SYMBOLS), time.time() - _T0))
    w("")

    def fmt(v):
        return "  【无】" if v is None else ("%+6.2f%%" % v)

    # ── 主表 ──
    w("-" * 74)
    w("%-8s %10s %8s %8s %8s %8s   %s"
      % ("品种", "最新价", "今日", "5日", "20日", "60日", "位置"))
    w("-" * 74)
    rows_ok = []
    for sym, cn, up, down, r, err in res:
        if r is None:
            w("%-8s 【无数据】%s" % (cn, err))
            continue
        rows_ok.append((cn, up, down, r))
        pos = "🔴60日高位" if r["from_hi"] > -3 else (
            "🟢60日低位" if r["from_lo"] < 5 else "🟡中段")
        w("%-8s %10.2f %s %s %s %s   %s"
          % (cn, r["last"], fmt(r["d1"]), fmt(r["d5"]),
             fmt(r["d20"]), fmt(r["d60"]), pos))

    # ── 涨得最猛的5个 → 谁受益 ──
    w("")
    w("=" * 74)
    w("🔥【20日涨幅前5】= 这些行业的售价在涨 → 收入端受益")
    w("=" * 74)
    up5 = sorted([x for x in rows_ok if x[3]["d20"] is not None],
                 key=lambda x: -x[3]["d20"])[:5]
    for cn, up, down, r in up5:
        w("  ★%s %+.2f%%(20日) 最新%.2f 距60日高点%+.1f%%"
          % (cn, r["d20"], r["last"], r["from_hi"]))
        w("     ✅收入端受益：%s" % up)
        w("     🔴成本端受损：%s" % down)

    # ── 跌得最猛的5个 → 谁受益 ──
    w("")
    w("=" * 74)
    w("❄️【20日跌幅前5】= 这些行业的售价在跌 → ★别碰收入端，看成本端★")
    w("=" * 74)
    dn5 = sorted([x for x in rows_ok if x[3]["d20"] is not None],
                 key=lambda x: x[3]["d20"])[:5]
    for cn, up, down, r in dn5:
        w("  ❄️%s %+.2f%%(20日) 最新%.2f 距60日低点%+.1f%%"
          % (cn, r["d20"], r["last"], r["from_lo"]))
        w("     🔴收入端受损：%s" % up)
        w("     ✅成本端受益：%s" % down)

    w("")
    w("=" * 74)
    w("⚠️ 用法（AI每次推荐周期股必须引用本表）：")
    w("   ① 驱动价格【20日为正 且 距60日高点>-10%】→ 才可以推它的收入端")
    w("   ② 驱动价格【20日为负】→ ★这条链的收入端一律不许推★")
    w("      2026-09-02 山东黄金就是死在这一条")
    w("   ③ ★同一个价格，收入端和成本端方向相反★")
    w("      玉米涨：种植股受益，养殖股受损（9月1日我判反过一次）")
    w("   ④ 价格创新高但个股在低位 = 铁律K反常 = 最佳埋伏")
    w("      价格在跌但个股在高位 = ★背离，最危险★")
    for s in _LOG[:8]:
        w("     · %s" % s)
    w("   耗时 %.1f 秒" % (time.time() - _T0))
    w("=" * 74)

    _save(L, bj)


def _save(L, bj):
    t = "\n".join(L)
    print(t)
    try:
        if not os.path.isdir(OUTDIR):
            os.makedirs(OUTDIR)
        d = bj.strftime("%Y%m%d")
        io.open(os.path.join(OUTDIR, "驱动价格_最新.txt"),
                "w", encoding="utf-8").write(t)
        io.open(os.path.join(OUTDIR, "驱动价格_%s.txt" % d),
                "w", encoding="utf-8").write(t)
        print("✅ patch_price: 已写出 reports/驱动价格_最新.txt")
    except Exception as e:
        print("🔴 patch_price: 写文件失败 %s" % e)


try:
    run()
except Exception:
    print("🔴 patch_price 整体异常，已跳过，不影响主扫描：")
    traceback.print_exc()

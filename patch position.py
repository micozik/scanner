# -*- coding: utf-8 -*-
"""
patch_position.py  ——  放仓库【根目录】  ★V2 并发版，替换掉V1★

★V1 的事故（2026-09-01）★
   V1 串行抓65只K线，每只2-4秒，给流水线多加了约4分钟。
   #494 原本 18分22秒，加上V1变成 22分18秒，
   撞上 scan.yml 的 timeout-minutes: 22 → ★整个job被强杀，报告一个字没提交★。
   而主扫描器自己「K线并发预热64只只用18秒」—— 它并发，我串行。

★V2 的三道保险★
   ① 并发 8 线程（和主扫描器同样的做法）
   ② ★硬性时间预算 150 秒★，到点立刻收工，没抓完的写【无数据】
   ③ 每只票最多试 2 个接口，不再试 3 个

★做什么★
   为 我的清单.txt 每一只票算：60日涨跌 / 距60日高低点 / 连板天数 / 缩量倍数
   写到 reports/位置表_最新.txt + 位置表_日期.txt

★安全性★
   · ★完全不修改 scanner_cloud.py★
   · 只读 我的清单.txt，只写 reports/位置表_*.txt
   · 取不到就写【无数据】，绝不编数
   · 全程异常捕获，最坏情况是本表空白，不会让流水线红灯
"""

import io
import os
import time
import datetime
import traceback
from concurrent.futures import ThreadPoolExecutor

LIST_FILE = "我的清单.txt"
OUTDIR = "reports"
LOOKBACK = 95
MAX_STOCKS = 80
WORKERS = 8
TIME_BUDGET = 150.0        # 秒，硬上限

_T0 = time.time()


def out_of_time():
    return (time.time() - _T0) > TIME_BUDGET


def board_limit(code):
    if code.startswith("30") or code.startswith("68"):
        return 19.8
    if code[:2] in ("92", "83", "87"):
        return 29.5
    return 9.8


def load_list():
    out = []
    if not os.path.exists(LIST_FILE):
        return out
    for line in io.open(LIST_FILE, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        p = [x.strip() for x in line.split("|")]
        if len(p) < 3 or p[0] not in ("持仓", "观察", "候选"):
            continue
        code, name = p[1], p[2]
        if not code.isdigit() or len(code) != 6:
            continue
        out.append((p[0], code, name))
    return out


def col(df, *names):
    for n in names:
        if n in df.columns:
            return n
    return None


def work(ak, item):
    """单只票：抓K线 + 算指标。任何失败都返回 None，不抛出。"""
    tag, code, name = item
    if out_of_time():
        return (tag, code, name, None, None, "超时预算用尽")

    end = datetime.datetime.now().strftime("%Y%m%d")
    start = (datetime.datetime.now()
             - datetime.timedelta(days=LOOKBACK)).strftime("%Y%m%d")

    df = None
    err = ""
    for fn in (
        lambda: ak.stock_zh_a_hist(symbol=code, period="daily",
                                   start_date=start, end_date=end,
                                   adjust="qfq"),
        lambda: ak.stock_zh_a_hist(symbol=code, period="daily",
                                   start_date=start, end_date=end),
    ):
        try:
            d = fn()
            if d is not None and len(d) > 5:
                df = d
                break
        except Exception as e:
            err = str(e)[:60]
            continue

    if df is None:
        return (tag, code, name, None, None, err or "取数失败")

    try:
        c_close = col(df, "收盘", "close")
        c_pct = col(df, "涨跌幅", "pct_chg")
        c_vol = col(df, "成交量", "volume")
        if c_close is None:
            return (tag, code, name, None, None, "无收盘列")

        closes = [float(x) for x in list(df[c_close])[-60:]]
        last = closes[-1]
        a = {"last": last, "d60": None, "hi": None, "lo": None,
             "from_hi": None, "from_lo": None, "vol_ratio": None,
             "today": None}

        if len(closes) >= 2:
            a["d60"] = (last / closes[0] - 1) * 100
            a["hi"] = max(closes)
            a["lo"] = min(closes)
            a["from_hi"] = (last / a["hi"] - 1) * 100
            a["from_lo"] = (last / a["lo"] - 1) * 100

        streak = None
        if c_pct is not None:
            pcts = [float(x) for x in list(df[c_pct])]
            a["today"] = pcts[-1]
            lim = board_limit(code)
            n = 0
            for v in reversed(pcts):
                if v >= lim:
                    n += 1
                else:
                    break
            streak = n

        if c_vol is not None:
            vols = [float(x) for x in list(df[c_vol])]
            if len(vols) >= 60:
                v60 = sum(vols[-60:]) / 60.0
                if v60 > 0:
                    a["vol_ratio"] = (sum(vols[-5:]) / 5.0) / v60

        return (tag, code, name, a, streak, "")
    except Exception as e:
        return (tag, code, name, None, None, str(e)[:60])


def run():
    buf = []

    def w(s=""):
        buf.append(s)

    bj = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    w("=" * 66)
    w("📍【位置表 V2】60日位置 + 连板天数 + 缩量 | 北京 %s"
      % bj.strftime("%Y-%m-%d %H:%M"))
    w("   决策卡第④项【位置】的数据源。取不到写【无数据】，绝不编数。")
    w("=" * 66)

    try:
        import akshare as ak
    except Exception as e:
        w("🔴 akshare 导入失败：%s" % e)
        ak = None

    rows = load_list()[:MAX_STOCKS]
    w("   清单载入 %d 只 | 并发 %d 线程 | 时间预算 %.0f 秒"
      % (len(rows), WORKERS, TIME_BUDGET))

    results = []
    if ak is not None and rows:
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            results = list(ex.map(lambda it: work(ak, it), rows))

    ok = len([r for r in results if r[3] is not None])
    w("   取数成功 %d / %d 只 | 实际耗时 %.1f 秒"
      % (ok, len(rows), time.time() - _T0))
    w("")

    for group in ("持仓", "观察", "候选"):
        sub = [r for r in results if r[0] == group]
        if not sub:
            continue
        w("-" * 66)
        w("【%s】" % group)
        w("-" * 66)
        for tag, code, name, a, s, err in sub:
            if a is None:
                w("  ◆ %s(%s)：【无数据】%s" % (name, code, err))
                continue

            def f(v):
                return "【无数据】" if v is None else ("%+.1f%%" % v)

            w("  ◆ %s(%s) 现价%.2f 今%s" % (name, code, a["last"], f(a["today"])))

            pos = ""
            if a["from_hi"] is not None:
                if a["from_hi"] > -3:
                    pos = "🔴60日高点附近·追高区"
                elif a["from_lo"] is not None and a["from_lo"] < 8:
                    pos = "🟢60日低位·可埋伏区"
                else:
                    pos = "🟡中段"
            w("      60日%s | 距高点%s 距低点%s %s"
              % (f(a["d60"]), f(a["from_hi"]), f(a["from_lo"]), pos))

            extra = []
            if s:
                extra.append("🔥连板%d天" % s)
            if a["vol_ratio"] is not None:
                t = "缩量" if a["vol_ratio"] < 0.8 else (
                    "放量" if a["vol_ratio"] > 1.5 else "常量")
                extra.append("5日/60日量=%.2f(%s)" % (a["vol_ratio"], t))
            if extra:
                w("      " + " | ".join(extra))
        w("")

    w("=" * 66)
    w("⚠️ 怎么用（AI每次决断必须引用本表）：")
    w("   · 距60日高点 > -3%   → 追高区，仓位砍半或不买")
    w("   · 距60日低点 < +8%   → 埋伏区，同等条件优先")
    w("   · 连板≥3天           → 位置已高，只在【产业周期型】才可考虑")
    w("   · 5日/60日量 < 0.8   → 缩量没人注意，配合催化才是机会")
    w("=" * 66)

    text = "\n".join(buf)
    print(text)
    try:
        if not os.path.isdir(OUTDIR):
            os.makedirs(OUTDIR)
        io.open(os.path.join(OUTDIR, "位置表_最新.txt"),
                "w", encoding="utf-8").write(text)
        io.open(os.path.join(OUTDIR, "位置表_%s.txt" % bj.strftime("%Y%m%d")),
                "w", encoding="utf-8").write(text)
        print("✅ patch_position V2: 已写出，耗时 %.1f 秒" % (time.time() - _T0))
    except Exception as e:
        print("🔴 patch_position: 写文件失败 %s" % e)


try:
    run()
except Exception:
    print("🔴 patch_position 整体异常，已跳过，不影响主扫描：")
    traceback.print_exc()

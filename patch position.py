# -*- coding: utf-8 -*-
"""
patch_position.py  ——  放仓库【根目录】

★做什么★
   为 我的清单.txt 里【每一只】票计算：
     · 60日涨跌幅        · 距60日最高点 / 最低点
     · 连板天数          · 5日均量 / 60日均量（缩量倍数）
     · 今日涨跌幅
   结果写成独立文件：reports/位置表_最新.txt + reports/位置表_日期.txt

★为什么需要★
   决策卡第④项是【位置】，但现行报告只对【冷低早】筛出的10只算60日，
   其余60多只候选/持仓一个都没有。
   2026-09-01：我推万向德农时不知道它已经6连板（那是从新闻标题里看到的），
   也不知道它在60日的什么位置 —— 位置是瞎判的。

★安全性（重点）★
   · ★完全不修改 scanner_cloud.py，一行都不碰★
   · 只读 我的清单.txt，只写 reports/位置表_*.txt
   · 取数失败就写【无数据】，绝不编数（铁律Y）
   · 三个 akshare 接口依次尝试，全失败就明确报出来
   · 任何异常都被捕获，不会让流水线红灯

★用完不用删★（每天自动更新）
"""

import io
import os
import time
import datetime
import traceback

LIST_FILE = "我的清单.txt"
OUTDIR = "reports"
LOOKBACK = 95          # 取95个自然日，够算60个交易日
MAX_STOCKS = 80        # 上限，防止跑太久


def board_limit(code):
    """按代码前缀判断涨停幅度：科创/创业20%，北交所30%，其余10%"""
    if code.startswith("30") or code.startswith("68"):
        return 19.8
    if code.startswith("92") or code.startswith("83") or code.startswith("87"):
        return 29.5
    return 9.8


def load_list():
    """读 我的清单.txt，返回 [(标签, 代码, 名称), ...]"""
    out = []
    if not os.path.exists(LIST_FILE):
        return out
    for line in io.open(LIST_FILE, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        p = [x.strip() for x in line.split("|")]
        if len(p) < 3:
            continue
        if p[0] not in ("持仓", "观察", "候选"):
            continue
        code, name = p[1], p[2]
        if not code.isdigit() or len(code) != 6:
            continue
        out.append((p[0], code, name))
    return out


def fetch_hist(ak, code):
    """三个接口依次试，返回 DataFrame 或 None"""
    end = datetime.datetime.now().strftime("%Y%m%d")
    start = (datetime.datetime.now()
             - datetime.timedelta(days=LOOKBACK)).strftime("%Y%m%d")

    tries = [
        ("stock_zh_a_hist",
         lambda: ak.stock_zh_a_hist(symbol=code, period="daily",
                                    start_date=start, end_date=end,
                                    adjust="qfq")),
        ("stock_zh_a_hist_qfq",
         lambda: ak.stock_zh_a_hist(symbol=code, period="daily",
                                    start_date=start, end_date=end)),
        ("stock_bj_a_hist",
         lambda: ak.stock_bj_a_hist(symbol=code, period="daily",
                                    start_date=start, end_date=end,
                                    adjust="qfq")),
    ]
    for fname, fn in tries:
        try:
            df = fn()
            if df is not None and len(df) > 5:
                return df
        except Exception:
            continue
    return None


def col(df, *names):
    for n in names:
        if n in df.columns:
            return n
    return None


def analyze(df):
    """返回 dict，取不到的字段写 None"""
    c_close = col(df, "收盘", "close")
    c_pct = col(df, "涨跌幅", "pct_chg")
    c_vol = col(df, "成交量", "volume")
    if c_close is None:
        return None

    closes = list(df[c_close])[-60:]
    last = closes[-1]

    r = {
        "last": last,
        "d60": None, "hi": None, "lo": None,
        "from_hi": None, "from_lo": None,
        "streak": None, "vol_ratio": None, "today": None,
    }

    if len(closes) >= 2:
        r["d60"] = (last / closes[0] - 1) * 100
        r["hi"] = max(closes)
        r["lo"] = min(closes)
        r["from_hi"] = (last / r["hi"] - 1) * 100
        r["from_lo"] = (last / r["lo"] - 1) * 100

    if c_pct is not None:
        pcts = list(df[c_pct])
        r["today"] = pcts[-1]

    if c_vol is not None:
        vols = list(df[c_vol])
        if len(vols) >= 60:
            v5 = sum(vols[-5:]) / 5.0
            v60 = sum(vols[-60:]) / 60.0
            if v60 > 0:
                r["vol_ratio"] = v5 / v60
    return r


def streak_of(df, code):
    """连板天数：从最后一天往回数，连续涨停的天数"""
    c_pct = col(df, "涨跌幅", "pct_chg")
    if c_pct is None:
        return None
    lim = board_limit(code)
    n = 0
    for v in reversed(list(df[c_pct])):
        try:
            if float(v) >= lim:
                n += 1
            else:
                break
        except Exception:
            break
    return n


def run():
    buf = []

    def w(s=""):
        buf.append(s)

    bj = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    w("=" * 66)
    w("📍【位置表】60日位置 + 连板天数 + 缩量  | 北京 %s"
      % bj.strftime("%Y-%m-%d %H:%M"))
    w("   决策卡第④项【位置】的数据来源。取不到就写【无数据】，绝不编数。")
    w("=" * 66)

    try:
        import akshare as ak
    except Exception as e:
        w("🔴 akshare 导入失败：%s → 本表无数据" % e)
        ak = None

    rows = load_list()
    if not rows:
        w("🔴 读不到 %s 或其中无有效行" % LIST_FILE)
    w("   清单载入 %d 只（上限 %d）" % (len(rows), MAX_STOCKS))
    rows = rows[:MAX_STOCKS]

    ok = fail = 0
    results = []

    if ak is not None:
        for tag, code, name in rows:
            df = fetch_hist(ak, code)
            if df is None:
                results.append((tag, code, name, None, None))
                fail += 1
                continue
            try:
                a = analyze(df)
                s = streak_of(df, code)
                results.append((tag, code, name, a, s))
                ok += 1
            except Exception:
                results.append((tag, code, name, None, None))
                fail += 1
            time.sleep(0.12)

    w("   取数成功 %d 只 / 失败 %d 只" % (ok, fail))
    w("")

    for group in ("持仓", "观察", "候选"):
        sub = [r for r in results if r[0] == group]
        if not sub:
            continue
        w("-" * 66)
        w("【%s】" % group)
        w("-" * 66)
        for tag, code, name, a, s in sub:
            if a is None:
                w("  ◆ %s(%s)：【无数据】取数失败" % (name, code))
                continue

            def f(v, unit="%"):
                return "【无数据】" if v is None else ("%+.1f%s" % (v, unit))

            line = "  ◆ %s(%s) 现价%.2f 今%s" % (
                name, code, a["last"], f(a["today"]))
            w(line)

            pos = ""
            if a["from_hi"] is not None:
                if a["from_hi"] > -3:
                    pos = "🔴60日最高点附近·追高区"
                elif a["from_lo"] is not None and a["from_lo"] < 8:
                    pos = "🟢60日低位·可埋伏区"
                else:
                    pos = "🟡中段"
            w("      60日%s | 距高点%s 距低点%s %s" % (
                f(a["d60"]), f(a["from_hi"]), f(a["from_lo"]), pos))

            extra = []
            if s is not None and s > 0:
                extra.append("🔥连板%d天" % s)
            elif s is not None:
                extra.append("连板0天")
            if a["vol_ratio"] is not None:
                tagv = "缩量" if a["vol_ratio"] < 0.8 else (
                    "放量" if a["vol_ratio"] > 1.5 else "常量")
                extra.append("5日/60日量=%.2f(%s)" % (a["vol_ratio"], tagv))
            if extra:
                w("      " + " | ".join(extra))
        w("")

    w("=" * 66)
    w("⚠️ 怎么用（写死，AI每次决断必须引用本表）：")
    w("   · 距60日高点 > -3%  → 追高区，仓位砍半或不买")
    w("   · 距60日低点 < +8%  → 埋伏区，同等条件下优先")
    w("   · 连板≥3天          → 位置已高，只在【产业周期型】才可考虑")
    w("   · 5日/60日量 < 0.8  → 缩量，没人注意，配合催化才是机会")
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
        print("✅ patch_position: 已写出 reports/位置表_最新.txt")
    except Exception as e:
        print("🔴 patch_position: 写文件失败 %s" % e)


try:
    run()
except Exception:
    print("🔴 patch_position 整体异常，已跳过，不影响主扫描：")
    traceback.print_exc()

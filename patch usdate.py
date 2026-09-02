# -*- coding: utf-8 -*-
"""
patch_usdate.py  ——  放在仓库【根目录】，和 scanner_usa.py 同一层

★为什么要它★
   美股_最新.txt 的【二、重点个股】那一节，日期标签用的是【运行日期】，
   不是这根K线的【真实日期】。
   实测：2026-08-31 / 09-01 / 09-02 三份报告，
        美光+2.77%、闪迪+5.50%、英伟达+1.48% —— 数字一字不差，
        但日期标签从 [08-31] 一路改到 [09-02]。
   而同一份报告的【指数】那一节老老实实标了 "[2026-08-31] 距今2天"。
   → 结果：【持仓夜盘影响】连续三天用三天前的价，
          写出"佰维/香农 偏多 +1.62% 持有顺风"的错误结论。

★这个补丁做什么★
   独立重抓14只关键美股，输出每只的【真实K线日期】和真实涨跌幅，
   写到 reports/美股核对_最新.txt 和 reports/美股核对_日期.txt
   → 拿它和 美股_最新.txt 对一眼，日期不符就说明那节数据作废。

★安全性★
   · ★完全不修改 scanner_usa.py，一行都不碰★
   · 只读接口、只写 reports/美股核对_*.txt
   · 两个数据源自动切换，取不到就写【无数据】，绝不编数
   · 6线程并发 + 全程异常捕获，几秒钟跑完，不影响流水线
"""

import io
import os
import datetime
import traceback
from concurrent.futures import ThreadPoolExecutor

OUTDIR = "reports"
TICKERS = ["NVDA", "MU", "SNDK", "WDC", "STX", "TSM", "AVGO",
           "AMD", "AAPL", "LRCX", "AMAT", "COHR", "GLW", "TSLA"]
NAMES = {
    "NVDA": "英伟达", "MU": "美光", "SNDK": "闪迪", "WDC": "西部数据",
    "STX": "希捷", "TSM": "台积电", "AVGO": "博通", "AMD": "AMD",
    "AAPL": "苹果", "LRCX": "拉姆研究", "AMAT": "应用材料",
    "COHR": "Coherent", "GLW": "康宁", "TSLA": "特斯拉",
}


def bj_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=8)


def pick(df, *names):
    for n in names:
        if n in df.columns:
            return n
    return None


def fetch(ak, sym):
    """两源依次试，返回 DataFrame 或 None"""
    for fn in (
        lambda: ak.stock_us_daily(symbol=sym),
        lambda: ak.stock_us_hist(symbol=sym, period="daily"),
    ):
        try:
            d = fn()
            if d is not None and len(d) > 2:
                return d
        except Exception:
            continue
    return None


def run():
    L = []

    def w(s=""):
        L.append(s)

    now = bj_now()
    w("=" * 62)
    w("🇺🇸【美股真实日期核对】北京 %s" % now.strftime("%Y-%m-%d %H:%M"))
    w("   用途：核对 美股_最新.txt 里【重点个股】那节的日期是不是真的")
    w("=" * 62)

    try:
        import akshare as ak
    except Exception as e:
        w("🔴 akshare 导入失败：%s → 本表无数据" % e)
        ak = None

    results = []
    if ak is not None:
        def job(sym):
            return (sym, fetch(ak, sym))
        with ThreadPoolExecutor(max_workers=6) as ex:
            results = list(ex.map(job, TICKERS))

    dates_seen = {}
    for sym, df in results:
        cn = NAMES.get(sym, sym)
        if df is None:
            w("  %-10s(%-5s) 【无数据】取数失败" % (cn, sym))
            continue
        try:
            c_close = pick(df, "close", "收盘")
            c_date = pick(df, "date", "日期")
            if c_close is None:
                w("  %-10s(%-5s) 【无数据】没有收盘列" % (cn, sym))
                continue
            closes = [float(x) for x in list(df[c_close])]
            last = closes[-1]
            prev = closes[-2]
            pct = (last / prev - 1) * 100 if prev else 0.0
            d = str(list(df[c_date])[-1])[:10] if c_date else "无日期列"
            dates_seen[d] = dates_seen.get(d, 0) + 1
            w("  %-10s(%-5s) 收 %10.2f  %+7.2f%%   ★真实K线日期 %s★"
              % (cn, sym, last, pct, d))
        except Exception as e:
            w("  %-10s(%-5s) 解析失败：%s" % (cn, sym, str(e)[:40]))

    w("")
    w("-" * 62)
    if dates_seen:
        main_date = sorted(dates_seen.items(), key=lambda kv: -kv[1])[0][0]
        w("📅 多数股票的真实K线日期：%s" % main_date)
        try:
            d0 = datetime.datetime.strptime(main_date, "%Y-%m-%d")
            gap = (now.date() - d0.date()).days
            w("   距今 %d 天（北京 %s）" % (gap, now.strftime("%Y-%m-%d")))
            if gap >= 2:
                w("   🔴🔴 数据已陈旧 ≥2天 → "
                  "美股_最新.txt 的【持仓夜盘影响】那节★整节作废★")
            elif gap == 1:
                w("   ✅ 正常（美股收盘后一天，北京时间必然差1天）")
            else:
                w("   ⚠️ 当天日期 = 美股可能还没收盘，数据未定型")
        except Exception:
            pass
    else:
        w("🔴 一只都没取到，无法判断")

    w("")
    w("⚠️ 怎么用：把上面的『真实K线日期』和 美股_最新.txt 里")
    w("   【二、重点个股】每行末尾方括号里的日期比一比。")
    w("   ★不一致 = 那节数据作废，不许用来判断持仓顺风逆风★")
    w("=" * 62)

    text = "\n".join(L)
    print(text)

    try:
        if not os.path.isdir(OUTDIR):
            os.makedirs(OUTDIR)
        d = now.strftime("%Y%m%d")
        io.open(os.path.join(OUTDIR, "美股核对_最新.txt"),
                "w", encoding="utf-8").write(text)
        io.open(os.path.join(OUTDIR, "美股核对_%s.txt" % d),
                "w", encoding="utf-8").write(text)
        print("✅ patch_usdate: 已写出 reports/美股核对_最新.txt")
    except Exception as e:
        print("🔴 patch_usdate: 写文件失败 %s" % e)


try:
    run()
except Exception:
    print("🔴 patch_usdate 整体异常，已跳过，不影响主扫描：")
    traceback.print_exc()

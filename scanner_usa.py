
# -*- coding: utf-8 -*-
"""
美股夜盘扫描器 · 独立版 V1.0（北京凌晨4:35，美股收盘后）
输出：reports/美股_最新.txt + reports/美股_日期.txt
与A股扫描器完全独立，互不影响
"""

import os, time, signal, datetime
import akshare as ak
import pandas as pd

REPORT = []

US_TICKERS = [
    ("英伟达", "NVDA"), ("台积电", "TSM"), ("美光", "MU"), ("AMD", "AMD"),
    ("博通", "AVGO"), ("SK海力士", "SKHY"), ("特斯拉", "TSLA"), ("苹果", "AAPL"),
    ("阿斯麦", "ASML"), ("英特尔", "INTC"), ("阿里巴巴", "BABA"), ("Meta", "META"),
    ("微软", "MSFT"), ("谷歌", "GOOGL"), ("亚马逊", "AMZN"), ("希捷", "STX"),
    ("西部数据", "WDC"), ("闪迪", "SNDK"), ("应用材料", "AMAT"), ("拉姆研究", "LRCX"),
]

US_INDEX = [
    ("道琼斯", ".DJI"), ("纳斯达克", ".IXIC"), ("标普500", ".INX"),
    ("费城半导体", ".SOX"),
]


def now_beijing():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=8)


def w(line=""):
    print(line)
    REPORT.append(str(line))


def pick_col(df, keywords):
    for kw in keywords:
        for c in df.columns:
            if kw in str(c):
                return c
    return None


class CallTimeout(Exception):
    pass


def _alarm(signum, frame):
    raise CallTimeout("接口超时")


def with_retry(fn, tries=2, wait=3, timeout=60):
    last = None
    for _ in range(tries):
        try:
            signal.signal(signal.SIGALRM, _alarm)
            signal.alarm(timeout)
            try:
                return fn()
            finally:
                signal.alarm(0)
        except Exception as e:
            last = e
            time.sleep(wait)
    raise last


def safe_run(title, func):
    try:
        func()
    except Exception as e:
        w(f"  [报空] {title}：{type(e).__name__}: {str(e)[:80]}")
    time.sleep(2)


# ========== 一、美股指数 ==========

def scan_index():
    w("\n【一、美股指数】（费城半导体SOX最关键=A股半导体风向标）")

    def _do():
        for name, sym in US_INDEX:
            try:
                df = with_retry(lambda s=sym: ak.index_us_stock_sina(symbol=s))
                if df is None or len(df) == 0:
                    w(f"    {name}：暂无数据")
                    continue
                last = df.iloc[-1]
                c_close = pick_col(df, ["close", "收盘"])
                c_open = pick_col(df, ["open", "开盘"])
                c_date = pick_col(df, ["date", "日期"])
                close = pd.to_numeric(last[c_close], errors="coerce")
                pct = ""
                if len(df) >= 2:
                    prev = pd.to_numeric(df.iloc[-2][c_close], errors="coerce")
                    if prev:
                        pct = f" {(close-prev)/prev*100:+.2f}%"
                d = str(last[c_date])[:10] if c_date else ""
                w(f"    {name}：{close}{pct}  [{d}]")
            except Exception as e:
                w(f"    {name}：[报空] {type(e).__name__}")
            time.sleep(1)
    safe_run("美股指数", _do)


# ========== 二、重点个股 ==========

def scan_stocks():
    w("\n【二、重点个股】（芯片/算力/存储/中概）")

    def _one(tk):
        """单只逐个抓，避开全市场快照的超时/限流"""
        for fname in ["stock_us_hist", "stock_us_daily"]:
            try:
                fn = getattr(ak, fname, None)
                if fn is None:
                    continue
                if fname == "stock_us_daily":
                    df = with_retry(lambda: fn(symbol=tk, adjust=""), tries=1, timeout=30)
                else:
                    end = now_beijing().strftime("%Y%m%d")
                    start = (now_beijing() - datetime.timedelta(days=12)).strftime("%Y%m%d")
                    df = with_retry(
                        lambda: fn(symbol=tk, period="daily", start_date=start,
                                   end_date=end, adjust=""), tries=1, timeout=30)
                if df is None or len(df) < 2:
                    continue
                c_close = pick_col(df, ["收盘", "close"])
                c_date = pick_col(df, ["日期", "date"])
                c_vol = pick_col(df, ["成交量", "volume"])
                close = pd.to_numeric(df.iloc[-1][c_close], errors="coerce")
                prev = pd.to_numeric(df.iloc[-2][c_close], errors="coerce")
                pct = (close - prev) / prev * 100 if prev else None
                d = str(df.iloc[-1][c_date])[:10] if c_date else ""
                vol = f" 量{df.iloc[-1][c_vol]}" if c_vol else ""
                return close, pct, d, vol, fname
            except Exception:
                continue
        return None, None, None, None, None

    def _do():
        ok = 0
        for cn, tk in US_TICKERS:
            close, pct, d, vol, src = _one(tk)
            if close is not None:
                pstr = f"{pct:+.2f}%" if pct is not None else ""
                w(f"    {cn}({tk}) {close} {pstr}{vol}  [{d}]")
                ok += 1
            else:
                w(f"    {cn}({tk}) [报空]")
            time.sleep(1)
        if ok == 0:
            raise RuntimeError("所有个股接口均失败")
        w(f"  （成功{ok}/{len(US_TICKERS)}只）")
    safe_run("美股个股", _do)



# ========== 三、美股新闻 ==========

def scan_news():
    w("\n【三、美股/全球新闻】")

    sources = [
        ("东财全球", lambda: ak.stock_info_global_em()),
        ("富途", lambda: ak.stock_info_global_futu()),
        ("财联社", lambda: ak.stock_info_global_cls(symbol="全部")),
        ("新浪", lambda: ak.stock_info_global_sina()),
    ]
    KW = ["美股", "纳斯达克", "道指", "标普", "美联储", "加息", "降息", "CPI", "通胀",
          "英伟达", "台积电", "美光", "AMD", "博通", "芯片", "半导体", "存储", "AI",
          "特斯拉", "苹果", "关税", "白宫", "特朗普", "鲍威尔", "沃什", "原油", "黄金",
          "中概", "费城", "SOX", "算力", "数据中心"]

    allnews = []
    for name, fn in sources:
        try:
            df = with_retry(fn, tries=2, wait=3)
            if df is None or len(df) == 0:
                continue
            c_title = pick_col(df, ["标题", "内容", "新闻", "摘要"])
            c_time = pick_col(df, ["发布时间", "时间", "日期"])
            for _, r in df.iterrows():
                t = str(r[c_title]).strip() if c_title else ""
                tm = str(r[c_time])[:16] if c_time else ""
                if t and t != "nan":
                    allnews.append((tm, t))
            w(f"  （源：{name} 已抓取）")
        except Exception as e:
            w(f"  [跳过] {name}：{type(e).__name__}")
        time.sleep(2)

    if not allnews:
        w("  [报空] 所有新闻源均失败")
        return

    seen, uniq = set(), []
    for tm, t in allnews:
        k = t[:30]
        if k not in seen:
            seen.add(k)
            uniq.append((tm, t))
    try:
        uniq.sort(key=lambda x: x[0], reverse=True)
    except Exception:
        pass

    hits = [(tm, t) for tm, t in uniq if any(k in t for k in KW)]
    w(f"\n  ★★★ 美股相关情报（{len(hits)}条）★★★")
    for tm, t in hits[:40]:
        w(f"    [{tm}] {t[:75]}")

    w(f"\n  ◆ 全量新闻（最近60条，共{len(uniq)}条去重）：")
    for tm, t in uniq[:60]:
        w(f"    [{tm}] {t[:70]}")


# ========== 主程序 ==========

def main():
    bj = now_beijing()
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][bj.weekday()]

    w("=" * 60)
    w(f"美股夜盘扫描器V1.0 | 北京 {bj.strftime('%Y-%m-%d %H:%M')} {weekday} | 美股收盘后")
    w("=" * 60)

    scan_index()
    scan_stocks()
    scan_news()

    w("\n" + "=" * 60)
    w("★★★【明日A股开盘参考】★★★")
    w("  数据在上，具体操作由AI结合你的持仓在对话中给出。")
    w("  核心看点：①费城半导体SOX涨跌 → A股半导体/芯片")
    w("           ②英伟达/美光/存储链 → A股算力/存储/CPO/PCB")
    w("           ③美联储/CPI表态 → 成长股整体估值")
    w("           ④油价/黄金 → A股资源链")
    w("=" * 60)

    os.makedirs("reports", exist_ok=True)
    text = "\n".join(REPORT)
    date = bj.strftime("%Y%m%d")
    for p in [f"reports/美股_最新.txt", f"reports/美股_{date}.txt"]:
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    print("\n✅ 美股扫描完成 reports/美股_最新.txt")


if __name__ == "__main__":
    main()

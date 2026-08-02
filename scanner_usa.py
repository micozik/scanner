# -*- coding: utf-8 -*-
"""
美股夜盘扫描器 · 独立版 V2.0（2026-08-02 对齐A股V3.5：催化热力图/多空/地域过滤/映射A股）
V1.1新增：
  1. 伯克希尔 BRK.A / BRK.B 加入重点个股
  2. 新闻雷达新增【聪明钱专区】：巴菲特/伯克希尔、伯里、木头姐、段永平、
     达里奥、阿克曼、索罗斯、13F 等大佬动向自动置顶
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
    ("伯克希尔B", "BRK.B"), ("伯克希尔A", "BRK.A"),
]

US_INDEX = [
    ("道琼斯", ".DJI"), ("纳斯达克", ".IXIC"), ("标普500", ".INX"),
    ("费城半导体", ".SOX"),
]

# 聪明钱关键词（大佬动向自动置顶）
SMART_MONEY = [
    "巴菲特", "伯克希尔", "哈撒韦", "芒格", "阿贝尔", "13F",
    "迈克尔·伯里", "伯里", "大空头",
    "木头姐", "凯茜·伍德", "凯西·伍德", "ARK", "方舟",
    "段永平",
    "达里奥", "桥水", "Bridgewater",
    "阿克曼", "潘兴广场", "Pershing",
    "索罗斯", "格林布拉特", "德鲁肯米勒", "查诺斯",
    "灰度", "贝莱德", "先锋领航", "景林", "高瓴",
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


# ========== 二、重点个股（含伯克希尔） ==========

def scan_stocks():
    w("\n【二、重点个股】（芯片/算力/存储/中概 + 伯克希尔）")

    def _one(tk):
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


# ========== 三、美股新闻 + 聪明钱专区 ==========


# ★美股→A股 板块映射（美股是A股的先行指标）
US_SECTOR_MAP = {
    "存储芯片→A股存储/长鑫链": ["美光", "Micron", "SK海力士", "海力士", "闪迪",
        "SanDisk", "西部数据", "希捷", "铠侠", "DRAM", "NAND", "HBM", "存储"],
    "半导体设备→A股北方华创/中微": ["应用材料", "拉姆", "Lam", "阿斯麦", "ASML",
        "KLA", "科天", "半导体设备", "光刻", "刻蚀"],
    "AI算力→A股紫光/中科曙光": ["英伟达", "NVIDIA", "AMD", "博通", "Broadcom",
        "数据中心", "capex", "资本开支", "云计算", "AWS", "Azure", "算力"],
    "光模块CPO→A股中际旭创/新易盛": ["光模块", "CPO", "硅光", "Coherent",
        "Lumentum", "康宁", "800G", "1.6T"],
    "消费电子→A股立讯/歌尔": ["苹果", "Apple", "iPhone", "消费电子", "手机出货"],
    "软件AI应用→A股金山/华大九天": ["微软", "Microsoft", "谷歌", "Google",
        "Meta", "OpenAI", "大模型", "Copilot", "软件"],
    "电动车→A股比亚迪链": ["特斯拉", "Tesla", "电动车", "EV", "电池"],
    "医药→A股创新药": ["辉瑞", "礼来", "默沙东", "FDA", "临床", "减肥药"],
    "金融→A股银行/保险": ["美联储", "加息", "降息", "美债", "收益率", "银行"],
    "能源→A股油气": ["原油", "WTI", "布伦特", "OPEC", "埃克森", "雪佛龙"],
}

US_BULL = ["涨", "上调", "创新高", "超预期", "大增", "暴增", "增长", "回购",
           "订单", "扩产", "紧缺", "缺货", "涨价", "提价", "利好", "反弹",
           "看好", "买入", "跑赢", "翻倍", "强劲", "复苏", "突破"]
US_BEAR = ["跌", "下调", "暴跌", "重挫", "不及预期", "下滑", "减产", "裁员",
           "亏损", "砍单", "推迟", "取消", "调查", "制裁", "抛售", "去杠杆",
           "利空", "承压", "疲软", "警告", "泡沫", "回撤", "熊市"]


def _pol(t):
    b = sum(1 for x in US_BULL if x in t)
    r = sum(1 for x in US_BEAR if x in t)
    return 1 if b > r else (-1 if r > b else 0)


def scan_us_heat(uniq):
    """美股催化热力图 → 直接映射到A股对应板块"""
    w("\n" + "=" * 60)
    w("🔥【美股催化热力图 → A股映射】美股是A股的先行指标")
    w("=" * 60)
    hits = {}
    for sect, kws in US_SECTOR_MAP.items():
        bu, be, seen = [], [], set()
        for tm, t in uniq:
            for k in kws:
                if k in t and t[:26] not in seen:
                    seen.add(t[:26])
                    p = _pol(t)
                    if p > 0:
                        bu.append((tm, t, k))
                    elif p < 0:
                        be.append((tm, t, k))
                    break
        if bu or be:
            hits[sect] = (bu, be)
    if not hits:
        w("  本次无命中")
        return
    ranked = sorted(hits.items(), key=lambda x: len(x[1][0]) - len(x[1][1]), reverse=True)
    w("\n  ★净利多排行（美股利多→次日A股对应板块大概率跟涨）：")
    for i, (sect, (bu, be)) in enumerate(ranked, 1):
        net = len(bu) - len(be)
        f = " 🔥🔥🔥重点" if net >= 4 else (" 🔥🔥" if net >= 2 else
            (" 🔥" if net >= 1 else (" ❄️❄️回避" if net <= -3 else
             (" ❄️偏空" if net <= -1 else " ⚖️"))))
        w(f"    {i}. {sect}：净{net:+d}（↑{len(bu)} ↓{len(be)}）{f}")
    w("\n  ★前3名的具体催化：")
    for sect, (bu, be) in ranked[:3]:
        if len(bu) - len(be) < 1:
            continue
        w(f"\n  ◆【{sect}】↑{len(bu)} ↓{len(be)}")
        for tm, t, k in bu[:5]:
            w(f"      ↑[{tm}] ({k}) {t[:58]}")
    w("\n  ★利空最重（次日A股对应板块回避）：")
    for sect, (bu, be) in ranked[-2:]:
        if len(bu) - len(be) < 0:
            w(f"    ❄️ {sect}：净{len(bu)-len(be):+d}")
            for tm, t, k in be[:3]:
                w(f"        ↓[{tm}] ({k}) {t[:58]}")
    w("\n  ⚠️ 判读：美股某板块净利多高 → 次日A股对应板块优先看")
    w("     但仍需过A股决策卡①②④⑤（板块第几天/资金/位置/游资）")
    w("=" * 60)


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
          "中概", "费城", "SOX", "算力", "数据中心", "Meta", "谷歌", "微软", "亚马逊"]

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

    # 聪明钱专区（最高优先级，置顶）
    smart = [(tm, t) for tm, t in uniq if any(k in t for k in SMART_MONEY)]
    w(f"\n  💰💰💰【聪明钱专区·大佬动向】（{len(smart)}条）💰💰💰")
    if smart:
        for tm, t in smart[:25]:
            w(f"    [{tm}] {t[:80]}")
    else:
        w("    本次无大佬动向新闻（13F季度披露日前后最密集）")

    hits = [(tm, t) for tm, t in uniq if any(k in t for k in KW)]
    w(f"\n  ★★★ 美股相关情报（{len(hits)}条）★★★")
    for tm, t in hits[:40]:
        w(f"    [{tm}] {t[:75]}")

    w(f"\n  ◆ 全量新闻（最近60条，共{len(uniq)}条去重）：")
    for tm, t in uniq[:60]:
        w(f"    [{tm}] {t[:70]}")

    scan_us_heat(uniq)


# ========== 主程序 ==========

def main():
    bj = now_beijing()
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][bj.weekday()]

    w("=" * 60)
    w(f"美股夜盘扫描器V2.0 | 北京 {bj.strftime('%Y-%m-%d %H:%M')} {weekday} | 美股收盘后")
    w("=" * 60)

    scan_index()
    scan_stocks()
    scan_news()

    w("\n" + "=" * 60)
    w("★★★【明日A股开盘参考】★★★")
    w("  数据在上，具体操作由AI结合你的持仓在对话中给出。")
    w("  核心看点：①费城半导体SOX → A股半导体/芯片")
    w("           ②英伟达/美光/存储链 → A股算力/存储/CPO/PCB")
    w("           ③美联储/CPI → 成长股整体估值")
    w("           ④油价/黄金 → A股资源链")
    w("           ⑤💰聪明钱专区 → 巴菲特等大佬持仓/表态（13F披露日重点看）")
    w("=" * 60)

    os.makedirs("reports", exist_ok=True)
    text = "\n".join(REPORT)
    date = bj.strftime("%Y%m%d")
    for p in [f"reports/美股_最新.txt", f"reports/美股_{date}.txt"]:
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    print("\n✅ 美股扫描V2.0完成 reports/美股_最新.txt")


if __name__ == "__main__":
    main()

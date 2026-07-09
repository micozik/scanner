# -*- coding: utf-8 -*-
"""
A股作战扫描器 · 云端版 V1.1（2026-07-09升级）
新增：状态门探测器（昨日涨停股今日表现——判断电风扇行情/能否开仓）
新增：缩量吸筹候选筛选（冷低早过滤器第④关线索）
运行：GitHub Actions 自动定时，结果写入 reports/latest.txt
安全：只读公开行情数据，不涉及任何账户信息
"""

import os
import datetime

import akshare as ak
import pandas as pd

REPORT = []


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


def safe_run(title, func):
    try:
        func()
    except Exception as e:
        w(f"  [报空] {title} 获取失败：{type(e).__name__}: {str(e)[:80]}")


# ========== 状态门探测器（V1.1新增，最重要模块） ==========

def scan_regime_gate():
    w("\n【零、状态门探测器】（昨日涨停股今日表现：正=情绪健康可开仓，负=电风扇行情禁开仓）")

    def _do():
        date = now_beijing().strftime("%Y%m%d")
        df = ak.stock_zt_pool_previous_em(date=date)
        if df is None or len(df) == 0:
            w("  暂无昨日涨停股数据")
            return
        c_name = pick_col(df, ["名称"])
        c_pct = pick_col(df, ["涨跌幅"])
        df[c_pct] = pd.to_numeric(df[c_pct], errors="coerce")
        avg = df[c_pct].mean()
        up_ratio = (df[c_pct] > 0).mean() * 100
        w(f"  昨日涨停股共{len(df)}只 | 今日平均涨跌：{avg:.2f}% | 红盘比例：{up_ratio:.0f}%")
        if avg > 1:
            w("  >>> 状态门判定：情绪健康，涨停有溢价，可按七关过滤器开仓")
        elif avg > -1:
            w("  >>> 状态门判定：中性震荡，仅限最高确定性标的，半仓试探")
        else:
            w("  >>> 状态门判定：电风扇/退潮行情，禁止一切新开仓")
        w("  最强表现前5：")
        for _, r in df.sort_values(c_pct, ascending=False).head(5).iterrows():
            w(f"    {r[c_name]} {r[c_pct]:+.2f}%")
    safe_run("状态门探测", _do)


# ========== 引擎A：异动扫描 ==========

def scan_sector_flow():
    w("\n【一、板块资金流向】（主力净流入，亿元）")
    for stype, label in [("行业资金流", "行业"), ("概念资金流", "概念")]:
        def _do(stype=stype, label=label):
            df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type=stype)
            c_name = pick_col(df, ["名称"])
            c_pct = pick_col(df, ["涨跌幅"])
            c_flow = pick_col(df, ["主力净流入-净额", "主力净流入"])
            df = df[[c_name, c_pct, c_flow]].copy()
            df[c_flow] = (pd.to_numeric(df[c_flow], errors="coerce") / 1e8).round(2)
            df = df.sort_values(c_flow, ascending=False)
            w(f"  ◆ {label}净流入前10：")
            for _, r in df.head(10).iterrows():
                w(f"    {r[c_name]} | 涨跌{r[c_pct]}% | 净流入{r[c_flow]}亿")
            w(f"  ◆ {label}净流出前5：")
            for _, r in df.tail(5).iloc[::-1].iterrows():
                w(f"    {r[c_name]} | 涨跌{r[c_pct]}% | 净流出{r[c_flow]}亿")
        safe_run(f"{label}资金流", _do)


def scan_zt_pool():
    w("\n【二、涨停池】（涨停扎堆=板块真启动验证器）")

    def _do():
        date = now_beijing().strftime("%Y%m%d")
        df = ak.stock_zt_pool_em(date=date)
        if df is None or len(df) == 0:
            w("  暂无涨停数据")
            return
        c_name = pick_col(df, ["名称"])
        c_industry = pick_col(df, ["所属行业", "行业"])
        c_lbc = pick_col(df, ["连板数"])
        w(f"  今日涨停共 {len(df)} 只")
        if c_industry:
            cnt = df[c_industry].value_counts().head(8)
            w("  ◆ 涨停扎堆行业：")
            for k, v in cnt.items():
                w(f"    {k}：{v}只")
        if c_lbc:
            high = df.sort_values(c_lbc, ascending=False).head(10)
            w("  ◆ 最高连板：")
            for _, r in high.iterrows():
                w(f"    {r[c_name]} | {r[c_industry] if c_industry else ''} | {r[c_lbc]}连板")
    safe_run("涨停池", _do)


def scan_spot():
    w("\n【三、全市场个股快照】")

    def _do():
        df = ak.stock_zh_a_spot_em()
        c_name = pick_col(df, ["名称"])
        c_code = pick_col(df, ["代码"])
        c_pct = pick_col(df, ["涨跌幅"])
        c_lb = pick_col(df, ["量比"])
        c_hs = pick_col(df, ["换手率", "换手"])
        df = df[~df[c_name].astype(str).str.contains("ST", na=False)]
        df[c_pct] = pd.to_numeric(df[c_pct], errors="coerce")
        df[c_lb] = pd.to_numeric(df[c_lb], errors="coerce")
        df[c_hs] = pd.to_numeric(df[c_hs], errors="coerce")

        w("  ◆ 涨幅前15（剔除ST）：")
        for _, r in df.sort_values(c_pct, ascending=False).head(15).iterrows():
            w(f"    {r[c_name]}({r[c_code]}) | +{r[c_pct]}% | 量比{r[c_lb]} | 换手{r[c_hs]}%")
        w("  ◆ 缩量吸筹候选（微跌且量比<0.6，冷低早第④关线索）：")
        quiet = df[(df[c_pct] < 0) & (df[c_pct] > -3) & (df[c_lb] < 0.6)]
        quiet = quiet.sort_values(c_lb).head(10)
        for _, r in quiet.iterrows():
            w(f"    {r[c_name]}({r[c_code]}) | {r[c_pct]}% | 量比{r[c_lb]}")
        w("  ◆ 跌幅前10：")
        for _, r in df.sort_values(c_pct).head(10).iterrows():
            w(f"    {r[c_name]}({r[c_code]}) | {r[c_pct]}% | 换手{r[c_hs]}%")
    safe_run("全市场快照", _do)


def scan_stock_flow():
    w("\n【四、个股主力净流入榜】")

    def _do():
        df = ak.stock_individual_fund_flow_rank(indicator="今日")
        c_name = pick_col(df, ["名称"])
        c_pct = pick_col(df, ["涨跌幅"])
        c_flow = pick_col(df, ["主力净流入-净额", "主力净流入"])
        df[c_flow] = (pd.to_numeric(df[c_flow], errors="coerce") / 1e8).round(2)
        for _, r in df.sort_values(c_flow, ascending=False).head(15).iterrows():
            w(f"    {r[c_name]} | 涨跌{r[c_pct]}% | 主力净流入{r[c_flow]}亿")
    safe_run("个股资金流", _do)


def scan_lhb():
    w("\n【五、龙虎榜】（约18点后更新）")

    def _do():
        today = now_beijing().strftime("%Y%m%d")
        df = ak.stock_lhb_detail_em(start_date=today, end_date=today)
        if df is None or len(df) == 0:
            w("  今日龙虎榜暂未发布")
            return
        c_name = pick_col(df, ["名称"])
        c_pct = pick_col(df, ["涨跌幅"])
        c_reason = pick_col(df, ["上榜原因", "解读"])
        c_net = pick_col(df, ["净买额", "龙虎榜净买额"])
        if c_net:
            df[c_net] = (pd.to_numeric(df[c_net], errors="coerce") / 1e8).round(2)
            df = df.sort_values(c_net, ascending=False)
        for _, r in df.head(15).iterrows():
            reason = str(r[c_reason])[:20] if c_reason else ""
            net = f" | 净买{r[c_net]}亿" if c_net else ""
            w(f"    {r[c_name]} | {r[c_pct]}%{net} | {reason}")
    safe_run("龙虎榜", _do)


def scan_north():
    w("\n【六、北向资金】")

    def _do():
        df = ak.stock_hsgt_fund_flow_summary_em()
        for _, r in df.iterrows():
            vals = " | ".join(f"{c}:{r[c]}" for c in df.columns[:6])
            w(f"    {vals}")
    safe_run("北向资金", _do)


# ========== 引擎B：催化潜伏（新闻） ==========

def scan_news():
    w("\n【七、新闻电报流】（最近40条）")
    sources = [
        ("财联社电报", lambda: ak.stock_info_global_cls(symbol="全部")),
        ("东财全球快讯", lambda: ak.stock_info_global_em()),
        ("新浪快讯", lambda: ak.stock_info_global_sina()),
    ]
    got = False
    for name, fn in sources:
        if got:
            break
        try:
            df = fn()
            if df is None or len(df) == 0:
                continue
            c_title = pick_col(df, ["标题", "内容", "新闻"])
            c_time = pick_col(df, ["发布时间", "时间", "日期"])
            w(f"  ◆ 数据源：{name}")
            for _, r in df.head(40).iterrows():
                t = str(r[c_time])[:16] if c_time else ""
                w(f"    [{t}] {str(r[c_title])[:60]}")
            got = True
        except Exception as e:
            w(f"  [跳过] {name}：{type(e).__name__}")
    if not got:
        w("  [报空] 所有新闻源均失败")


# ========== 主程序 ==========

def main():
    bj = now_beijing()
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][bj.weekday()]
    intraday = bj.weekday() < 5 and (9 <= bj.hour < 15)
    mode = "盘中快照" if intraday else "盘后全扫描"

    w("=" * 60)
    w(f"A股作战扫描器V1.1 | {bj.strftime('%Y-%m-%d %H:%M')} {weekday} | 模式：{mode}")
    w("数据源：公开接口（延迟秒~分钟级）；收盘价以券商截图为唯一权威")
    w("=" * 60)

    scan_regime_gate()
    scan_sector_flow()
    if not intraday:
        scan_zt_pool()
    scan_spot()
    scan_stock_flow()
    if not intraday:
        scan_lhb()
        scan_north()
    scan_news()

    os.makedirs("reports", exist_ok=True)
    text = "\n".join(REPORT)
    with open("reports/latest.txt", "w", encoding="utf-8") as f:
        f.write(text)
    with open(f"reports/日报_{bj.strftime('%Y%m%d')}.txt", "w", encoding="utf-8") as f:
        f.write(text)
    print("\n✅ 扫描完成，已写入 reports/latest.txt")


if __name__ == "__main__":
    main()

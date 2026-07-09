
# -*- coding: utf-8 -*-
"""
A股作战扫描器 · 云端版 V1.2（2026-07-09晚升级）
V1.2新增：
  1. 双重重试机制（修复接口抖动报空）
  2. 市场广度仪表盘（整个A股今天发生了什么）
  3. 板块全景榜（行业+概念完整排序，每个板块附领涨股）
  4. 轮动连续性追踪（今天vs上次对比：持续=真主线，新面孔=待验证）
  5. 新闻流扩容（多源并抓，全谱信息面：政策/科技/战争/气候/金融）
"""

import os
import json
import time
import signal
import datetime

import akshare as ak
import pandas as pd

REPORT = []
HIST_FILE = "reports/top_sectors.json"


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


def _alarm_handler(signum, frame):
    raise CallTimeout("接口60秒无响应")


def with_retry(fn, tries=2, wait=3, timeout=60):
    """每次请求最多等60秒（防挂起），失败自动重试"""
    last = None
    for _ in range(tries):
        try:
            signal.signal(signal.SIGALRM, _alarm_handler)
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
        w(f"  [报空] {title} 获取失败：{type(e).__name__}: {str(e)[:80]}")


# ========== 零、状态门探测器 ==========

def scan_regime_gate():
    w("\n【零、状态门】昨日涨停股今日表现（正=可开仓，负=电风扇禁开仓）")

    def _do():
        date = now_beijing().strftime("%Y%m%d")
        df = with_retry(lambda: ak.stock_zt_pool_previous_em(date=date))
        if df is None or len(df) == 0:
            w("  暂无昨日涨停股数据")
            return
        c_name = pick_col(df, ["名称"])
        c_pct = pick_col(df, ["涨跌幅"])
        df[c_pct] = pd.to_numeric(df[c_pct], errors="coerce")
        avg = df[c_pct].mean()
        up_ratio = (df[c_pct] > 0).mean() * 100
        w(f"  昨日涨停{len(df)}只 | 今日平均{avg:.2f}% | 红盘率{up_ratio:.0f}%")
        if avg > 1:
            w("  >>> 判定：情绪健康可开仓（按七关过滤器）")
        elif avg > -1:
            w("  >>> 判定：中性震荡，仅最高确定性半仓")
        else:
            w("  >>> 判定：电风扇/退潮，禁止新开仓")
    safe_run("状态门", _do)


# ========== 一、市场广度仪表盘（V1.2新增） ==========

def scan_breadth_and_spot():
    w("\n【一、市场广度仪表盘】整个A股今天的体检单")

    def _do():
        df = with_retry(lambda: ak.stock_zh_a_spot_em())
        c_name = pick_col(df, ["名称"])
        c_code = pick_col(df, ["代码"])
        c_pct = pick_col(df, ["涨跌幅"])
        c_lb = pick_col(df, ["量比"])
        c_amt = pick_col(df, ["成交额"])
        df[c_pct] = pd.to_numeric(df[c_pct], errors="coerce")
        df[c_lb] = pd.to_numeric(df[c_lb], errors="coerce")
        df[c_amt] = pd.to_numeric(df[c_amt], errors="coerce")

        total = df[c_pct].notna().sum()
        ups = (df[c_pct] > 0).sum()
        downs = (df[c_pct] < 0).sum()
        zt = (df[c_pct] > 9.85).sum()
        dt = (df[c_pct] < -9.85).sum()
        amt = df[c_amt].sum() / 1e8
        w(f"  全市场{total}只 | 涨{ups} : 跌{downs} | 涨停约{zt} : 跌停约{dt} | 总成交约{amt:.0f}亿")

        ndf = df[~df[c_name].astype(str).str.contains("ST", na=False)]
        w("  ◆ 涨幅前15（剔除ST）：")
        for _, r in ndf.sort_values(c_pct, ascending=False).head(15).iterrows():
            w(f"    {r[c_name]}({r[c_code]}) +{r[c_pct]}% 量比{r[c_lb]}")
        w("  ◆ 缩量吸筹候选（微跌+量比<0.6，暗流线索）：")
        quiet = ndf[(ndf[c_pct] < 0) & (ndf[c_pct] > -3) & (ndf[c_lb] < 0.6)]
        for _, r in quiet.sort_values(c_lb).head(10).iterrows():
            w(f"    {r[c_name]}({r[c_code]}) {r[c_pct]}% 量比{r[c_lb]}")
    safe_run("市场广度", _do)


# ========== 二、板块全景榜+轮动连续性（V1.2核心新增） ==========

def scan_board_rank():
    w("\n【二、板块全景榜】什么板块在涨·板块里谁领涨·与上次对比")

    prev_top = []
    try:
        if os.path.exists(HIST_FILE):
            with open(HIST_FILE, "r", encoding="utf-8") as f:
                prev = json.load(f)
                prev_top = prev.get("industry_top", [])
                w(f"  （上次记录：{prev.get('date','?')} 领涨板块：{'、'.join(prev_top[:5])}...）")
    except Exception:
        pass

    today_top = []

    def _industry():
        nonlocal today_top
        df = with_retry(lambda: ak.stock_board_industry_name_em())
        c_name = pick_col(df, ["板块名称", "名称"])
        c_pct = pick_col(df, ["涨跌幅"])
        c_lead = pick_col(df, ["领涨股票", "领涨股"])
        c_leadpct = pick_col(df, ["领涨股票-涨跌幅", "领涨股-涨跌幅"])
        df[c_pct] = pd.to_numeric(df[c_pct], errors="coerce")
        df = df.sort_values(c_pct, ascending=False)
        today_top = df.head(10)[c_name].astype(str).tolist()
        w("  ◆ 行业板块涨幅前15（板块 | 涨跌 | 领涨股 | 连续性）：")
        for _, r in df.head(15).iterrows():
            name = str(r[c_name])
            tag = "🔥持续" if name in prev_top else "🆕新面孔"
            lead = f"{r[c_lead]}" if c_lead else ""
            lp = f" {r[c_leadpct]}%" if c_leadpct else ""
            w(f"    {name} | {r[c_pct]}% | 领涨:{lead}{lp} | {tag}")
        w("  ◆ 行业板块跌幅前5：")
        for _, r in df.tail(5).iloc[::-1].iterrows():
            w(f"    {r[c_name]} | {r[c_pct]}%")
    safe_run("行业板块榜", _industry)

    def _concept():
        df = with_retry(lambda: ak.stock_board_concept_name_em())
        c_name = pick_col(df, ["板块名称", "名称"])
        c_pct = pick_col(df, ["涨跌幅"])
        c_lead = pick_col(df, ["领涨股票", "领涨股"])
        df[c_pct] = pd.to_numeric(df[c_pct], errors="coerce")
        df = df.sort_values(c_pct, ascending=False)
        w("  ◆ 概念板块涨幅前15：")
        for _, r in df.head(15).iterrows():
            lead = f" 领涨:{r[c_lead]}" if c_lead else ""
            w(f"    {r[c_name]} | {r[c_pct]}%{lead}")
    safe_run("概念板块榜", _concept)

    try:
        if today_top:
            os.makedirs("reports", exist_ok=True)
            with open(HIST_FILE, "w", encoding="utf-8") as f:
                json.dump({"date": now_beijing().strftime("%Y-%m-%d %H:%M"),
                           "industry_top": today_top}, f, ensure_ascii=False)
    except Exception:
        pass


# ========== 三、板块资金流（双重试加固） ==========

def scan_sector_flow():
    w("\n【三、板块资金流向】钱从哪抽·注进哪（主力净流入，亿元）")
    for stype, label in [("行业资金流", "行业"), ("概念资金流", "概念")]:
        def _do(stype=stype, label=label):
            df = with_retry(lambda: ak.stock_sector_fund_flow_rank(
                indicator="今日", sector_type=stype))
            c_name = pick_col(df, ["名称"])
            c_pct = pick_col(df, ["涨跌幅"])
            c_flow = pick_col(df, ["主力净流入-净额", "主力净流入"])
            df = df[[c_name, c_pct, c_flow]].copy()
            df[c_flow] = (pd.to_numeric(df[c_flow], errors="coerce") / 1e8).round(2)
            df = df.sort_values(c_flow, ascending=False)
            w(f"  ◆ {label}净流入前10：")
            for _, r in df.head(10).iterrows():
                w(f"    {r[c_name]} | {r[c_pct]}% | +{r[c_flow]}亿")
            w(f"  ◆ {label}净流出前5：")
            for _, r in df.tail(5).iloc[::-1].iterrows():
                w(f"    {r[c_name]} | {r[c_pct]}% | {r[c_flow]}亿")
        safe_run(f"{label}资金流", _do)


# ========== 四、涨停池 ==========

def scan_zt_pool():
    w("\n【四、涨停池】资金攻击方向验证器")

    def _do():
        date = now_beijing().strftime("%Y%m%d")
        df = with_retry(lambda: ak.stock_zt_pool_em(date=date))
        if df is None or len(df) == 0:
            w("  暂无涨停数据")
            return
        c_name = pick_col(df, ["名称"])
        c_industry = pick_col(df, ["所属行业", "行业"])
        c_lbc = pick_col(df, ["连板数"])
        w(f"  今日涨停共 {len(df)} 只")
        if c_industry:
            for k, v in df[c_industry].value_counts().head(8).items():
                w(f"    {k}：{v}只")
        if c_lbc:
            w("  ◆ 最高连板：")
            for _, r in df.sort_values(c_lbc, ascending=False).head(10).iterrows():
                w(f"    {r[c_name]} | {r[c_industry] if c_industry else ''} | {r[c_lbc]}连板")
    safe_run("涨停池", _do)


# ========== 五、龙虎榜 ==========

def scan_lhb():
    w("\n【五、龙虎榜】大资金署名单（约18点后更新）")

    def _do():
        today = now_beijing().strftime("%Y%m%d")
        df = with_retry(lambda: ak.stock_lhb_detail_em(start_date=today, end_date=today))
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
            net = f" 净买{r[c_net]}亿" if c_net else ""
            w(f"    {r[c_name]} {r[c_pct]}%{net} {reason}")
    safe_run("龙虎榜", _do)


# ========== 六、北向资金 ==========

def scan_north():
    w("\n【六、北向资金】")

    def _do():
        df = with_retry(lambda: ak.stock_hsgt_fund_flow_summary_em())
        for _, r in df.iterrows():
            w("    " + " | ".join(f"{c}:{r[c]}" for c in df.columns[:6]))
    safe_run("北向资金", _do)


# ========== 七、新闻流（V1.2扩容：多源并抓，全谱信息面） ==========

def scan_news():
    w("\n【七、新闻电报流】全谱信息面（政策/科技/战争/气候/金融）")
    sources = [
        ("财联社电报", lambda: ak.stock_info_global_cls(symbol="全部"), 50),
        ("东财全球快讯", lambda: ak.stock_info_global_em(), 30),
        ("新浪快讯", lambda: ak.stock_info_global_sina(), 30),
    ]
    got = 0
    for name, fn, limit in sources:
        if got >= 2:
            break
        try:
            df = with_retry(fn, tries=2, wait=3)
            if df is None or len(df) == 0:
                continue
            c_title = pick_col(df, ["标题", "内容", "新闻"])
            c_time = pick_col(df, ["发布时间", "时间", "日期"])
            w(f"  ◆ 数据源：{name}")
            for _, r in df.head(limit).iterrows():
                t = str(r[c_time])[:16] if c_time else ""
                w(f"    [{t}] {str(r[c_title])[:70]}")
            got += 1
        except Exception as e:
            w(f"  [跳过] {name}：{type(e).__name__}")
    if got == 0:
        w("  [报空] 所有新闻源均失败")


# ========== 主程序 ==========

def main():
    bj = now_beijing()
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][bj.weekday()]
    intraday = bj.weekday() < 5 and (9 <= bj.hour < 15)
    mode = "盘中快照" if intraday else "盘后全扫描"

    w("=" * 60)
    w(f"A股作战扫描器V1.2 | {bj.strftime('%Y-%m-%d %H:%M')} {weekday} | {mode}")
    w("=" * 60)

    scan_regime_gate()
    scan_breadth_and_spot()
    scan_board_rank()
    scan_sector_flow()
    if not intraday:
        scan_zt_pool()
        scan_lhb()
        scan_north()
    scan_news()

    os.makedirs("reports", exist_ok=True)
    text = "\n".join(REPORT)
    with open("reports/latest.txt", "w", encoding="utf-8") as f:
        f.write(text)
    with open(f"reports/日报_{bj.strftime('%Y%m%d')}.txt", "w", encoding="utf-8") as f:
        f.write(text)
    print("\n✅ V1.2扫描完成 reports/latest.txt")


if __name__ == "__main__":
    main()

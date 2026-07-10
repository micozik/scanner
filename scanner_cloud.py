
# -*- coding: utf-8 -*-
"""
A股作战扫描器 · 云端版 V1.3（2026-07-09晚·多源互备版）
V1.3新增：
  1. 多数据源自动切换：东财失败自动切同花顺/乐咕乐股/新浪
  2. 市场广度改用乐咕乐股轻量接口（涨跌家数/涨停跌停/活跃度）
  3. 模块间隔2秒，降低被限流概率
  4. 每次请求60秒硬超时+重试（防挂起）
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


def multi_source(title, sources):
    """依次尝试多个数据源，第一个成功的生效"""
    for src_name, fn in sources:
        try:
            result = with_retry(fn)
            if result is not None:
                return src_name, result
        except Exception as e:
            w(f"  [切换] {title}·{src_name}失败({type(e).__name__})，尝试备源...")
    return None, None


def safe_run(title, func):
    try:
        func()
    except Exception as e:
        w(f"  [报空] {title}：{type(e).__name__}: {str(e)[:80]}")
    time.sleep(2)  # 模块间隔，防限流


# ========== 零、状态门 ==========

def scan_regime_gate():
    w("\n【零、状态门】昨日涨停股今日表现（正=可开仓，负=禁开仓）")

    def _do():
        date = now_beijing().strftime("%Y%m%d")
        df = with_retry(lambda: ak.stock_zt_pool_previous_em(date=date))
        if df is None or len(df) == 0:
            w("  暂无数据")
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


# ========== 一、市场广度（主源：乐咕乐股） ==========

def scan_breadth():
    w("\n【一、市场广度仪表盘】")

    def _do():
        src, df = multi_source("市场广度", [
            ("乐咕乐股", lambda: ak.stock_market_activity_legu()),
        ])
        if df is not None:
            w(f"  （数据源：{src}）")
            for _, r in df.iterrows():
                w(f"    {r.iloc[0]}：{r.iloc[1]}")
            return
        # 备源：东财快照计算
        df2 = with_retry(lambda: ak.stock_zh_a_spot_em())
        c_pct = pick_col(df2, ["涨跌幅"])
        df2[c_pct] = pd.to_numeric(df2[c_pct], errors="coerce")
        w(f"  （数据源：东财计算）涨{(df2[c_pct]>0).sum()} : 跌{(df2[c_pct]<0).sum()}"
          f" | 涨停~{(df2[c_pct]>9.85).sum()} : 跌停~{(df2[c_pct]<-9.85).sum()}")
    safe_run("市场广度", _do)


# ========== 二、全市场快照+缩量吸筹 ==========

def scan_spot():
    w("\n【二、全市场快照与暗流筛选】")

    def _do():
        df = with_retry(lambda: ak.stock_zh_a_spot_em(), tries=2, timeout=90)
        c_name = pick_col(df, ["名称"])
        c_code = pick_col(df, ["代码"])
        c_pct = pick_col(df, ["涨跌幅"])
        c_lb = pick_col(df, ["量比"])
        df = df[~df[c_name].astype(str).str.contains("ST", na=False)]
        df[c_pct] = pd.to_numeric(df[c_pct], errors="coerce")
        df[c_lb] = pd.to_numeric(df[c_lb], errors="coerce")
        w("  ◆ 涨幅前15：")
        for _, r in df.sort_values(c_pct, ascending=False).head(15).iterrows():
            w(f"    {r[c_name]}({r[c_code]}) +{r[c_pct]}% 量比{r[c_lb]}")
        w("  ◆ 缩量吸筹候选（微跌+量比<0.6）：")
        quiet = df[(df[c_pct] < 0) & (df[c_pct] > -3) & (df[c_lb] < 0.6)]
        for _, r in quiet.sort_values(c_lb).head(10).iterrows():
            w(f"    {r[c_name]}({r[c_code]}) {r[c_pct]}% 量比{r[c_lb]}")
    safe_run("全市场快照", _do)


# ========== 三、板块全景榜（东财主源+同花顺备源） ==========

def scan_board_rank():
    w("\n【三、板块全景榜】板块|涨跌|领涨股|连续性")

    prev_top = []
    try:
        if os.path.exists(HIST_FILE):
            with open(HIST_FILE, "r", encoding="utf-8") as f:
                prev = json.load(f)
                prev_top = prev.get("industry_top", [])
                w(f"  （上次{prev.get('date','?')}领涨：{'、'.join(prev_top[:5])}...）")
    except Exception:
        pass

    today_top = []

    def _industry():
        nonlocal today_top
        src, df = multi_source("行业榜", [
            ("东财", lambda: ak.stock_board_industry_name_em()),
            ("同花顺", lambda: ak.stock_board_industry_summary_ths()),
        ])
        if df is None:
            raise RuntimeError("东财与同花顺行业榜均失败")
        c_name = pick_col(df, ["板块名称", "板块", "名称"])
        c_pct = pick_col(df, ["涨跌幅", "涨跌"])
        c_lead = pick_col(df, ["领涨股票", "领涨股"])
        df[c_pct] = pd.to_numeric(df[c_pct], errors="coerce")
        df = df.sort_values(c_pct, ascending=False)
        today_top = df.head(10)[c_name].astype(str).tolist()
        w(f"  ◆ 行业涨幅前15（源：{src}）：")
        for _, r in df.head(15).iterrows():
            name = str(r[c_name])
            tag = "🔥持续" if name in prev_top else "🆕新面孔"
            lead = f" 领涨:{r[c_lead]}" if c_lead else ""
            w(f"    {name} | {r[c_pct]}%{lead} | {tag}")
        w("  ◆ 行业跌幅前5：")
        for _, r in df.tail(5).iloc[::-1].iterrows():
            w(f"    {r[c_name]} | {r[c_pct]}%")
    safe_run("行业板块榜", _industry)

    def _concept():
        src, df = multi_source("概念榜", [
            ("东财", lambda: ak.stock_board_concept_name_em()),
        ])
        if df is None:
            raise RuntimeError("概念榜失败")
        c_name = pick_col(df, ["板块名称", "名称"])
        c_pct = pick_col(df, ["涨跌幅"])
        c_lead = pick_col(df, ["领涨股票", "领涨股"])
        df[c_pct] = pd.to_numeric(df[c_pct], errors="coerce")
        df = df.sort_values(c_pct, ascending=False)
        w(f"  ◆ 概念涨幅前15（源：{src}）：")
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


# ========== 四、板块资金流（东财主源+同花顺备源） ==========

def scan_sector_flow():
    w("\n【四、板块资金流向】（亿元）")

    def _em(stype):
        return ak.stock_sector_fund_flow_rank(indicator="今日", sector_type=stype)

    def _do():
        src, df = multi_source("行业资金流", [
            ("东财", lambda: _em("行业资金流")),
            ("同花顺", lambda: ak.stock_fund_flow_industry(symbol="即时")),
        ])
        if df is None:
            raise RuntimeError("行业资金流双源失败")
        c_name = pick_col(df, ["名称", "行业"])
        c_pct = pick_col(df, ["涨跌幅", "行业指数涨跌", "涨跌"])
        c_flow = pick_col(df, ["主力净流入-净额", "主力净流入", "净额", "流入资金"])
        df[c_flow] = pd.to_numeric(df[c_flow], errors="coerce")
        if df[c_flow].abs().max() and df[c_flow].abs().max() > 1e6:
            df[c_flow] = (df[c_flow] / 1e8).round(2)  # 东财单位是元
        df = df.sort_values(c_flow, ascending=False)
        w(f"  ◆ 行业净流入前10（源：{src}）：")
        for _, r in df.head(10).iterrows():
            w(f"    {r[c_name]} | {r[c_pct]}% | +{r[c_flow]}亿")
        w("  ◆ 行业净流出前5：")
        for _, r in df.tail(5).iloc[::-1].iterrows():
            w(f"    {r[c_name]} | {r[c_pct]}% | {r[c_flow]}亿")
    safe_run("板块资金流", _do)


# ========== 五、涨停池 ==========

def scan_zt_pool():
    w("\n【五、涨停池】")

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


# ========== 六、龙虎榜 ==========

def scan_lhb():
    w("\n【六、龙虎榜】（约18点后更新）")

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


# ========== 七、北向资金 ==========

def scan_north():
    w("\n【七、北向资金】")

    def _do():
        df = with_retry(lambda: ak.stock_hsgt_fund_flow_summary_em())
        for _, r in df.iterrows():
            w("    " + " | ".join(f"{c}:{r[c]}" for c in df.columns[:6]))
    safe_run("北向资金", _do)


# ========== 八、新闻流 ==========

def scan_news():
    w("\n【八、新闻电报流】全谱信息面")
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
        time.sleep(2)
    if got == 0:
        w("  [报空] 所有新闻源均失败")


# ========== 主程序 ==========

def main():
    bj = now_beijing()
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][bj.weekday()]
    intraday = bj.weekday() < 5 and (9 <= bj.hour < 15)
    mode = "盘中快照" if intraday else "盘后全扫描"

    w("=" * 60)
    w(f"A股作战扫描器V1.3多源版 | {bj.strftime('%Y-%m-%d %H:%M')} {weekday} | {mode}")
    w("=" * 60)

    scan_regime_gate()
    scan_breadth()
    scan_spot()
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
    print("\n✅ V1.3扫描完成 reports/latest.txt")


if __name__ == "__main__":
    main()

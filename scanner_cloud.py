# -*- coding: utf-8 -*-
"""
A股作战扫描器 · 云端版 V1.6（2026-07-14·冷低早筛选 + 我的清单版）
V1.6：1.全市场快照加备源 2.新增冷低早候选筛选器(缩量+低位+主力暗流) 3.我的清单模块(读txt,买卖不改代码)
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
WATCH_FILE = "我的清单.txt"
SPOT_DF = None          # 全市场快照缓存，一次拉取多处复用
SPOT_SRC = None


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
    time.sleep(2)


def get_spot():
    """东财快照被封，直接用新浪（含turnoverratio换手率）"""
    global SPOT_DF, SPOT_SRC
    if SPOT_DF is not None:
        return SPOT_DF
    try:
        SPOT_DF = with_retry(ak.stock_zh_a_spot, tries=3, wait=5, timeout=120)
        SPOT_SRC = "新浪"
    except Exception as e:
        w(f"  [报空] 新浪快照失败：{type(e).__name__}")
        SPOT_DF = None
    return SPOT_DF




# ========== 零、状态门 ==========

def scan_regime_gate():
    w("\n【零、状态门】昨日涨停股今日表现（正=可开仓，负=禁开仓）")

    def _do():
        date = now_beijing().strftime("%Y%m%d")
        df = with_retry(lambda: ak.stock_zt_pool_previous_em(date=date))
        if df is None or len(df) == 0:
            w("  暂无数据")
            return
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


# ========== 我的清单·盯盘（读 我的清单.txt） ==========

def scan_watchlist():
    w("\n【我的清单·盯盘】（买卖只改 我的清单.txt，不动代码）")

    if not os.path.exists(WATCH_FILE):
        w(f"  未找到 {WATCH_FILE}（在仓库根目录新建即可）")
        return

    def _do():
        spot = get_spot()
        c_code = pick_col(spot, ["代码"]) if spot is not None else None
        c_price = pick_col(spot, ["最新价"]) if spot is not None else None
        c_pct = pick_col(spot, ["涨跌幅"]) if spot is not None else None

        def live(code):
            if spot is None or c_code is None:
                return None, None
            row = spot[spot[c_code].astype(str).str.zfill(6) == str(code).zfill(6)]
            if len(row) == 0:
                return None, None
            return (pd.to_numeric(row.iloc[0][c_price], errors="coerce"),
                    pd.to_numeric(row.iloc[0][c_pct], errors="coerce"))

        groups = {}
        with open(WATCH_FILE, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                p = line.split()
                if len(p) < 5:
                    continue
                code, name, cost, qty, tag = p[0], p[1], p[2], p[3], p[4]
                stop = p[5] if len(p) >= 6 else None
                groups.setdefault(tag, []).append((code, name, cost, qty, stop))

        for tag, items in groups.items():
            w(f"  ◆ {tag}：")
            for code, name, cost, qty, stop in items:
                price, pct = live(code)
                cost_f = pd.to_numeric(cost, errors="coerce")
                qty_f = pd.to_numeric(qty, errors="coerce")
                seg = f"    {name}({code}) "
                if price is not None:
                    seg += f"现价{price} 今日{pct}%"
                    if cost_f and qty_f and qty_f > 0:
                        pnl = (price - cost_f) / cost_f * 100
                        seg += f" | 成本{cost} 盈亏{pnl:+.1f}%"
                    else:
                        seg += f" | 荐入/观察{cost}"
                    if stop:
                        stop_f = pd.to_numeric(stop, errors="coerce")
                        gap = (price - stop_f) / stop_f * 100
                        flag = "⚠️已破位" if price <= stop_f else f"距止损{gap:+.1f}%"
                        seg += f" | 止损{stop} {flag}"
                else:
                    seg += "（快照缺价，稍后重跑或截图核）"
                w(seg)
    safe_run("我的清单", _do)


# ========== 一、市场广度 ==========

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
        df2 = get_spot()
        c_pct = pick_col(df2, ["涨跌幅"])
        df2[c_pct] = pd.to_numeric(df2[c_pct], errors="coerce")
        w(f"  （数据源：{SPOT_SRC}计算）涨{(df2[c_pct]>0).sum()} : 跌{(df2[c_pct]<0).sum()}")
    safe_run("市场广度", _do)


# ========== 二、全市场快照 ==========

def scan_spot():
    w("\n【二、全市场快照与暗流筛选】")

    def _do():
        df = get_spot()
        if df is None:
            raise RuntimeError("全市场快照双源均失败")
        c_name = pick_col(df, ["名称"])
        c_code = pick_col(df, ["代码"])
        c_pct = pick_col(df, ["涨跌幅"])
        c_lb = pick_col(df, ["量比"])
        d = df[~df[c_name].astype(str).str.contains("ST", na=False)].copy()
        d[c_pct] = pd.to_numeric(d[c_pct], errors="coerce")
        w(f"  ◆ 涨幅前15（源：{SPOT_SRC}）：")
        for _, r in d.sort_values(c_pct, ascending=False).head(15).iterrows():
            lb = f" 量比{r[c_lb]}" if c_lb else ""
            w(f"    {r[c_name]}({r[c_code]}) {r[c_pct]}%{lb}")
    safe_run("全市场快照", _do)


# ========== 二·5、冷低早候选筛选器（核心） ==========

def _hist_close(code, symbol=None):
    if symbol:
        try:
            k = with_retry(lambda: ak.stock_zh_a_daily(symbol=symbol), tries=1, timeout=25)
            if k is not None and len(k) >= 45:
                return k, pick_col(k, ["close", "收盘"])
        except Exception:
            pass
    try:
        end = now_beijing().strftime("%Y%m%d")
        start = (now_beijing() - datetime.timedelta(days=120)).strftime("%Y%m%d")
        k = with_retry(lambda: ak.stock_zh_a_hist(symbol=code, period="daily",
                       start_date=start, end_date=end, adjust="qfq"), tries=1, timeout=25)
        if k is not None and len(k) >= 45:
            return k, pick_col(k, ["收盘", "close"])
    except Exception:
        pass
    return None, None


def scan_cold_low():
    w("\n★★★【冷低早候选·暗流吸筹筛选】★★★（冷+低+主力暗流，宁缺毋滥）")

    def _do():
        spot = get_spot()
        if spot is None:
            raise RuntimeError("快照缺失")
        w(f"  （源：{SPOT_SRC} 列名：{list(spot.columns)[:10]}）")
        c_code = pick_col(spot, ["代码", "code", "symbol"])
        c_name = pick_col(spot, ["名称", "name"])
        c_price = pick_col(spot, ["最新价", "trade"])
        c_pct = pick_col(spot, ["涨跌幅", "changepercent"])
        if not all([c_code, c_name, c_price, c_pct]):
            w("  [报空] 快照缺必要字段")
            return

        d = spot.copy()
        d = d[~d[c_name].astype(str).str.contains("ST|退|N ", na=False)]
        for c in [c_price, c_pct]:
            d[c] = pd.to_numeric(d[c], errors="coerce")
        d = d.dropna(subset=[c_pct, c_price])
        d["_code6"] = d[c_code].astype(str).str.extract(r"(\d{6})")[0]
        d = d.dropna(subset=["_code6"])
        d = d[~d["_code6"].str.startswith(("8", "4", "9"))]

        cand = d[(d[c_pct] >= -4) & (d[c_pct] <= 2) &
                 (d[c_price] >= 3) & (d[c_price] <= 100)].copy()
        w(f"  ①横盘微跌+价格区间：{len(cand)}只")

                fl, fsrc = None, None
        try:
            f = with_retry(lambda: ak.stock_individual_fund_flow_rank(indicator="今日"),
                           tries=3, wait=8, timeout=90)
            fc = pick_col(f, ["代码"])
            fn = pick_col(f, ["今日主力净流入-净额", "主力净流入-净额", "主力净流入"])
            fl = f[[fc, fn]].copy()
            fl.columns = ["_c", "_net"]
            fsrc = "东财"
        except Exception as e:
            w(f"  [切换] 东财资金流({type(e).__name__})，试同花顺...")
            try:
                f = with_retry(lambda: ak.stock_fund_flow_individual(symbol="即时"),
                               tries=2, wait=5, timeout=90)
                fc = pick_col(f, ["股票代码", "代码"])
                fn = pick_col(f, ["净额"])
                fl = f[[fc, fn]].copy()
                fl.columns = ["_c", "_net"]
                fsrc = "同花顺"
            except Exception as e2:
                w(f"  [报空] 资金流双源均失败({type(e2).__name__})")
                return

        fl["_code6"] = fl["_c"].astype(str).str.extract(r"(\d{6})")[0]
        fl["主力净流入"] = pd.to_numeric(fl["_net"], errors="coerce")
        fl = fl.dropna(subset=["_code6", "主力净流入"])
        cand = cand.merge(fl[["_code6", "主力净流入"]], on="_code6", how="inner")
        cand = cand[cand["主力净流入"] > 0].sort_values("主力净流入", ascending=False)
        w(f"  ②主力暗流净流入>0（源：{fsrc}）：{len(cand)}只")


        w("  ③低位(60日跌>12%) ④缩量(5日/60日均量<0.8)：")
        got = 0
        for _, r in cand.head(50).iterrows():
            if got >= 8:
                break
            code6 = r["_code6"]
            sym = ("sh" if code6.startswith("6") else "sz") + code6
            k, kc = _hist_close(code6, sym)
            if k is None or kc is None:
                continue
            try:
                now_p = pd.to_numeric(k.iloc[-1][kc], errors="coerce")
                p60 = pd.to_numeric(k.iloc[-45][kc], errors="coerce")
                if not p60:
                    continue
                chg60 = (now_p - p60) / p60 * 100
                if chg60 > -12:
                    continue
                kv = pick_col(k, ["volume", "成交量"])
                vtxt = ""
                if kv:
                    v5 = pd.to_numeric(k[kv].tail(5), errors="coerce").mean()
                    v60 = pd.to_numeric(k[kv].tail(45), errors="coerce").mean()
                    if v60 and v5 / v60 >= 0.8:
                        continue
                    vtxt = f" | 量能{v5/v60:.2f}倍缩量"
                w(f"    {r[c_name]}({code6}) {r[c_price]} 今{r[c_pct]}% | "
                  f"60日{chg60:.1f}%{vtxt} | 主力净流入{r['主力净流入']/1e4:.0f}万")
                got += 1
            except Exception:
                continue
            time.sleep(0.4)

        if got == 0:
            w("    本次无标的 —— 这是特征不是故障。")
        else:
            w(f"  ※ 命中{got}只。③早(日期催化)⑤止损由你我集中分析定。")
    safe_run("冷低早筛选", _do)




# ========== 三、板块全景榜 ==========

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


# ========== 四、板块资金流 ==========

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
            df[c_flow] = (df[c_flow] / 1e8).round(2)
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
    w("\n【六、龙虎榜·个股】（约18:35后更新）")

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


# ========== 七、游资席位 ==========

def scan_hot_money():
    w("\n【七、游资席位·活跃营业部】（谁在扫货/出货，约18:35后完整）")

    def _do():
        date = now_beijing().strftime("%Y%m%d")
        df = with_retry(lambda: ak.stock_lhb_hyyyb_em(start_date=date, end_date=date))
        if df is None or len(df) == 0:
            w("  今日活跃营业部暂未发布（18:35后再看）")
            return
        c_name = pick_col(df, ["营业部名称", "营业部"])
        c_net = pick_col(df, ["总买卖净额", "净额", "净买"])
        c_stock = pick_col(df, ["买入股票", "买入个股"])
        if c_net:
            df[c_net] = pd.to_numeric(df[c_net], errors="coerce")
            if df[c_net].abs().max() and df[c_net].abs().max() > 1e6:
                df[c_net] = (df[c_net] / 1e8).round(2)
            df = df.sort_values(c_net, ascending=False)
        w("  ◆ 净买入最猛席位前10（游资进攻）：")
        for _, r in df.head(10).iterrows():
            stock = f" 主买:{r[c_stock]}" if c_stock else ""
            net = f" 净{r[c_net]}亿" if c_net else ""
            w(f"    {r[c_name]}{net}{stock}")
    safe_run("游资席位", _do)


# ========== 八、北向资金 ==========

def scan_north():
    w("\n【八、北向资金】")

    def _do():
        df = with_retry(lambda: ak.stock_hsgt_fund_flow_summary_em())
        for _, r in df.iterrows():
            w("    " + " | ".join(f"{c}:{r[c]}" for c in df.columns[:6]))
    safe_run("北向资金", _do)


# ========== 九、新闻流 + 关键词雷达 ==========

NEWS_RADAR = {
    "① 名人喊话": ["马斯克", "黄仁勋", "特朗普", "鲍威尔", "巴菲特", "伯里", "段永平", "奥特曼", "库克", "贝索斯"],
    "② 政策·国内": ["国务院", "发改委", "财政部", "央行", "证监会", "工信部", "十五五", "国常会", "补贴", "规划", "部署"],
    "③ 政策·海外": ["白宫", "美联储", "加息", "降息", "关税", "出口管制", "商务部", "外交部", "制裁", "欧盟"],
    "④ 科技·产业": ["AI", "算力", "半导体", "芯片", "光模块", "CPO", "机器人", "商业航天", "卫星", "固态电池", "创新药", "存储", "英伟达", "台积电", "阿斯麦", "液冷", "光刻"],
    "⑤ 大宗·地缘": ["石油", "原油", "黄金", "铜", "稀土", "战争", "霍尔木兹", "伊朗", "以色列", "地缘", "OPEC", "天然气", "冲突"],
    "⑥ 资金·事件": ["打新", "IPO", "长鑫", "并购", "重组", "预增", "增持", "减持", "回购", "举牌", "分红", "中标"],
}


def _fetch_news_source(fn):
    df = with_retry(fn, tries=2, wait=3)
    if df is None or len(df) == 0:
        return []
    c_title = pick_col(df, ["标题", "内容", "新闻", "摘要"])
    c_time = pick_col(df, ["发布时间", "时间", "日期"])
    out = []
    for _, r in df.iterrows():
        title = str(r[c_title]).strip() if c_title else ""
        t = str(r[c_time])[:16] if c_time else ""
        if title and title != "nan":
            out.append((t, title))
    return out


def scan_news():
    w("\n【九、新闻电报流 + 关键词雷达】全谱信息面")

    sources = [
        ("财联社", lambda: ak.stock_info_global_cls(symbol="全部")),
        ("东财", lambda: ak.stock_info_global_em()),
        ("新浪", lambda: ak.stock_info_global_sina()),
        ("同花顺", lambda: ak.stock_info_global_ths()),
        ("富途", lambda: ak.stock_info_global_futu()),
    ]

    all_news, ok_src = [], []
    for name, fn in sources:
        try:
            items = _fetch_news_source(fn)
            if items:
                all_news.extend(items)
                ok_src.append(f"{name}({len(items)})")
        except Exception as e:
            w(f"  [跳过] {name}：{type(e).__name__}")
        time.sleep(2)

    if not all_news:
        w("  [报空] 所有新闻源均失败")
        return

    seen, uniq = set(), []
    for t, title in all_news:
        key = title[:30]
        if key not in seen:
            seen.add(key)
            uniq.append((t, title))
    try:
        uniq.sort(key=lambda x: x[0], reverse=True)
    except Exception:
        pass

    w(f"  （合并去重：{'、'.join(ok_src)} → 共{len(uniq)}条）")
    w("\n  ★★★ 关键情报雷达 ★★★")
    any_hit = False
    for cat, kws in NEWS_RADAR.items():
        hits, hseen = [], set()
        for t, title in uniq:
            if any(kw in title for kw in kws) and title[:30] not in hseen:
                hseen.add(title[:30])
                hits.append((t, title))
        if hits:
            any_hit = True
            w(f"  【{cat}】")
            for t, title in hits[:12]:
                w(f"    [{t}] {title[:75]}")
    if not any_hit:
        w("  （本次无命中关注关键词）")

    w("\n  ◆ 全量新闻流（最近100条）：")
    for t, title in uniq[:100]:
        w(f"    [{t}] {title[:70]}")


# ========== 主程序 ==========

def main():
    bj = now_beijing()
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][bj.weekday()]
    weekend = bj.weekday() >= 5
    intraday = (not weekend) and (9 <= bj.hour < 15)
    if weekend:
        mode = "周末新闻扫描"
    elif intraday:
        mode = "盘中快照"
    else:
        mode = "盘后全扫描"

    w("=" * 60)
    w(f"A股作战扫描器V1.6多源版 | {bj.strftime('%Y-%m-%d %H:%M')} {weekday} | {mode}")
    w("=" * 60)

    if weekend:
        scan_news()
    else:
        scan_regime_gate()
        scan_watchlist()
        scan_breadth()
        scan_spot()
        scan_cold_low()
        scan_board_rank()
        scan_sector_flow()
        if not intraday:
            scan_zt_pool()
            scan_lhb()
            scan_hot_money()
            scan_north()
        scan_news()

    os.makedirs("reports", exist_ok=True)
    text = "\n".join(REPORT)
    date = bj.strftime('%Y%m%d')
    prefix = "盘中" if intraday else ("周末" if weekend else "盘后")

    for path in [f"reports/{prefix}_最新.txt", f"reports/{prefix}_{date}.txt", "reports/latest.txt"]:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    print(f"\n✅ V1.6完成 {prefix}_最新.txt")


if __name__ == "__main__":
    main()


# -*- coding: utf-8 -*-
"""
A股作战扫描器 · 云端版 V1.7.2（2026-07-20 政策雷达+财联社备源）
V1.7新增：
  1. 概念板块历史库（独立文件），概念榜三源轮试，修复"概念缺字段"
  2. 次日环境预判（风险分0-8，把描述变成指令）
  3. 冷低早：⓪大盘闸门 + ⑥板块闸门（防止板块崩了还推票）
  4. 行业/概念 均支持：连涨天数 + 3日累计 + 排名变化🚀
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
CONCEPT_FILE = "reports/top_concepts.json"
WATCH_FILE = "我的清单.txt"
SPOT_DF = None
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
    raise CallTimeout("接口超时")


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
            r = with_retry(fn)
            if r is not None and len(r) > 0:
                return src_name, r
        except Exception as e:
            w(f"  [切换] {title}·{src_name}失败({type(e).__name__})，尝试备源...")
    return None, None


def safe_run(title, func):
    try:
        func()
    except Exception as e:
        w(f"  [报空] {title}：{type(e).__name__}: {str(e)[:90]}")
    time.sleep(2)


def get_spot():
    """全市场快照：东财对海外服务器封锁，直接用新浪"""
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


# ========== 次日环境预判（风险分） ==========

def scan_tomorrow_gate():
    w("\n🚨【次日环境预判】（不是描述今天，是判断明天能不能动）")

    def _do():
        score = 0
        reasons = []
        try:
            df = with_retry(lambda: ak.stock_market_activity_legu())
            m = {str(r.iloc[0]): str(r.iloc[1]) for _, r in df.iterrows()}
            up = float(m.get("上涨", 0))
            dn = float(m.get("下跌", 0))
            dt = float(m.get("跌停", 0))
            act = float(str(m.get("活跃度", "0")).replace("%", ""))
            ratio = up / (up + dn) * 100 if (up + dn) else 0
            w(f"  今日：涨{up:.0f} 跌{dn:.0f} 上涨占比{ratio:.1f}% | 跌停{dt:.0f}只 | 活跃度{act:.1f}%")
            if ratio < 40:
                score += 2
                reasons.append(f"广度恶化(占比{ratio:.0f}%)")
            if dt >= 30:
                score += 2
                reasons.append(f"跌停{dt:.0f}只=恐慌")
            elif dt >= 15:
                score += 1
                reasons.append(f"跌停{dt:.0f}只偏多")
            if act < 50:
                score += 2
                reasons.append(f"活跃度{act:.0f}%低迷")
            elif act < 60:
                score += 1
        except Exception as e:
            w(f"  [跳过] 广度：{type(e).__name__}")

        try:
            df = with_retry(lambda: ak.stock_zt_pool_previous_em(
                date=now_beijing().strftime("%Y%m%d")))
            c_pct = pick_col(df, ["涨跌幅"])
            avg = pd.to_numeric(df[c_pct], errors="coerce").mean()
            w(f"  昨日涨停今日平均：{avg:.2f}%")
            if avg < -1:
                score += 2
                reasons.append(f"涨停股退潮({avg:.1f}%)")
            elif avg < 1:
                score += 1
                reasons.append("赚钱效应中性")
        except Exception:
            pass

        w(f"\n  🚨 风险分：{score}/8　{'｜'.join(reasons) if reasons else '无警报'}")
        if score >= 5:
            w("  >>> 【明日高危】一票不碰，盈利仓主动减半锁利，破位无条件走")
        elif score >= 3:
            w("  >>> 【明日偏弱】不开新仓，只减不加")
        elif score >= 1:
            w("  >>> 【明日中性】仅最高确定性半仓")
        else:
            w("  >>> 【明日健康】可按七关开仓")
    safe_run("次日预判", _do)


# ========== 我的清单 ==========

def scan_watchlist():
    w("\n【我的清单·盯盘】（买卖只改 我的清单.txt，不动代码）")

    if not os.path.exists(WATCH_FILE):
        w(f"  未找到 {WATCH_FILE}（在仓库根目录新建即可）")
        return

    def _do():
        spot = get_spot()
        if spot is None:
            w("  快照缺失，无法盯盘")
            return
        c_code = pick_col(spot, ["代码", "code"])
        c_price = pick_col(spot, ["最新价", "trade"])
        c_pct = pick_col(spot, ["涨跌幅", "changepercent"])

        def live(code):
            try:
                key = str(code).zfill(6)
                row = spot[spot[c_code].astype(str).str.contains(key, na=False)]
                if len(row) == 0:
                    return None, None
                return (pd.to_numeric(row.iloc[0][c_price], errors="coerce"),
                        pd.to_numeric(row.iloc[0][c_pct], errors="coerce"))
            except Exception:
                return None, None

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
                if price is not None and pd.notna(price):
                    seg += f"现价{price} 今日{pct}%"
                    if pd.notna(cost_f) and cost_f > 0 and pd.notna(qty_f) and qty_f > 0:
                        pnl = (price - cost_f) / cost_f * 100
                        seg += f" | 成本{cost} 盈亏{pnl:+.1f}%"
                    else:
                        seg += f" | 荐入/观察{cost}"
                    if stop:
                        stop_f = pd.to_numeric(stop, errors="coerce")
                        if pd.notna(stop_f) and stop_f > 0:
                            gap = (price - stop_f) / stop_f * 100
                            flag = "⚠️已破位!!!" if price <= stop_f else f"距止损{gap:+.1f}%"
                            seg += f" | 止损{stop} {flag}"
                else:
                    seg += "（快照无此代码，请核对）"
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
        c_pct = pick_col(df2, ["涨跌幅", "changepercent"])
        df2[c_pct] = pd.to_numeric(df2[c_pct], errors="coerce")
        w(f"  （数据源：{SPOT_SRC}计算）涨{(df2[c_pct]>0).sum()} : 跌{(df2[c_pct]<0).sum()}")
    safe_run("市场广度", _do)


# ========== 二、全市场快照 ==========

def scan_spot():
    w("\n【二、全市场快照】")

    def _do():
        df = get_spot()
        if df is None:
            raise RuntimeError("快照失败")
        c_name = pick_col(df, ["名称", "name"])
        c_code = pick_col(df, ["代码", "code"])
        c_pct = pick_col(df, ["涨跌幅", "changepercent"])
        d = df[~df[c_name].astype(str).str.contains("ST", na=False)].copy()
        d[c_pct] = pd.to_numeric(d[c_pct], errors="coerce")
        d = d.dropna(subset=[c_pct])
        w(f"  ◆ 涨幅前15（源：{SPOT_SRC}）：")
        for _, r in d.sort_values(c_pct, ascending=False).head(15).iterrows():
            w(f"    {r[c_name]}({r[c_code]}) {r[c_pct]}%")
    safe_run("全市场快照", _do)


# ========== 冷低早筛选 ==========

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


def _get_industry_map():
    src, df = multi_source("行业榜(冷低早)", [
        ("东财", lambda: ak.stock_board_industry_name_em()),
        ("同花顺", lambda: ak.stock_board_industry_summary_ths()),
        ("同花顺资金流", lambda: ak.stock_fund_flow_industry(symbol="即时")),
    ])
    if df is None:
        return {}
    c_name = pick_col(df, ["板块名称", "板块", "名称", "行业"])
    c_pct = pick_col(df, ["涨跌幅", "涨跌"])
    if not c_name or not c_pct:
        return {}
    m = {}
    for _, r in df.iterrows():
        try:
            v = pd.to_numeric(r[c_pct], errors="coerce")
            if pd.notna(v):
                m[str(r[c_name])] = float(v)
        except Exception:
            continue
    return m


def _stock_industry(code6):
    try:
        info = with_retry(lambda: ak.stock_individual_info_em(symbol=code6),
                          tries=1, timeout=20)
        if info is None:
            return None
        for _, r in info.iterrows():
            if "行业" in str(r.iloc[0]):
                return str(r.iloc[1])
    except Exception:
        pass
    return None


def scan_cold_low():
    w("\n★★★【冷低早候选·暗流吸筹】★★★（大盘闸+冷+低+缩量+涨日放量+板块闸）")

    def _do():
        spot = get_spot()
        if spot is None:
            raise RuntimeError("快照缺失")
        c_code = pick_col(spot, ["代码", "code"])
        c_name = pick_col(spot, ["名称", "name"])
        c_price = pick_col(spot, ["最新价", "trade"])
        c_pct = pick_col(spot, ["涨跌幅", "changepercent"])
        c_amt = pick_col(spot, ["成交额", "amount"])
        if not all([c_code, c_name, c_price, c_pct]):
            w("  [报空] 快照缺必要字段")
            return

        d = spot.copy()
        d = d[~d[c_name].astype(str).str.contains("ST|退|N ", na=False)]
        for c in [c_price, c_pct]:
            d[c] = pd.to_numeric(d[c], errors="coerce")
        d = d.dropna(subset=[c_pct, c_price])

        up = int((d[c_pct] > 0).sum())
        dn = int((d[c_pct] < 0).sum())
        ratio = up / (up + dn) * 100 if (up + dn) else 0
        w(f"  ⓪大盘环境闸门：涨{up} 跌{dn} 上涨占比{ratio:.1f}%")
        if ratio < 25:
            w("  ⚠️【闸门触发】上涨占比<25% = 系统性杀跌日")
            w("  >>> 今日不输出任何候选。形态再好，板块崩了照样跟着崩。")
            return
        if ratio < 35:
            w("  ⚠️ 环境偏弱(占比<35%)，以下候选仅供观察，不建议当日开仓")

        d["_code6"] = d[c_code].astype(str).str.extract(r"(\d{6})")[0]
        d = d.dropna(subset=["_code6"])
        d = d[~d["_code6"].str.startswith(("8", "4", "9"))]

        cand = d[(d[c_pct] >= -3.5) & (d[c_pct] <= 0.5) &
                 (d[c_pct].abs() > 0.05) &
                 (d[c_price] >= 3) & (d[c_price] <= 100)].copy()
        w(f"  ①横盘微跌(排停牌僵尸)：{len(cand)}只")

        if c_amt:
            cand[c_amt] = pd.to_numeric(cand[c_amt], errors="coerce")
            cand = cand.dropna(subset=[c_amt])
            cand = cand[(cand[c_amt] > 3e7) & (cand[c_amt] < 8e8)]
            cand = cand.sort_values(c_amt, ascending=False)
            w(f"  ②成交额3千万-8亿(排僵尸/排爆炒)：{len(cand)}只")
        else:
            cand = cand.reindex(cand[c_pct].abs().sort_values().index)

        w("  ③低位(60日跌>12%) ④缩量(5日/60日<0.8) ⑤涨日放量(暗流)：")
        hits = []
        for _, r in cand.head(120).iterrows():
            if len(hits) >= 10:
                break
            code6 = r["_code6"]
            sym = ("sh" if code6.startswith("6") else "sz") + code6
            k, kc = _hist_close(code6, sym)
            if k is None or kc is None:
                continue
            try:
                kv = pick_col(k, ["volume", "成交量"])
                if not kv:
                    continue
                now_p = pd.to_numeric(k.iloc[-1][kc], errors="coerce")
                p60 = pd.to_numeric(k.iloc[-45][kc], errors="coerce")
                if not p60 or pd.isna(now_p):
                    continue
                chg60 = (now_p - p60) / p60 * 100
                if chg60 > -12:
                    continue
                v5 = pd.to_numeric(k[kv].tail(5), errors="coerce").mean()
                v60 = pd.to_numeric(k[kv].tail(45), errors="coerce").mean()
                if not v60 or v5 / v60 >= 0.8:
                    continue
                k20 = k.tail(20).copy()
                k20["_c"] = pd.to_numeric(k20[kc], errors="coerce")
                k20["_v"] = pd.to_numeric(k20[kv], errors="coerce")
                k20["_chg"] = k20["_c"].pct_change()
                upv = k20[k20["_chg"] > 0]["_v"].mean()
                dnv = k20[k20["_chg"] < 0]["_v"].mean()
                if not dnv or pd.isna(upv) or upv / dnv < 1.1:
                    continue
                hits.append({
                    "code": code6, "name": str(r[c_name]), "price": r[c_price],
                    "pct": r[c_pct], "chg60": chg60, "vr": v5 / v60, "ud": upv / dnv,
                })
                w(f"    候选：{r[c_name]}({code6}) {r[c_price]} 今{r[c_pct]}% | "
                  f"60日{chg60:.1f}% | 缩量{v5/v60:.2f} | 涨跌量比{upv/dnv:.2f}")
            except Exception:
                continue
            time.sleep(0.4)

        if not hits:
            w("    本次无标的 —— 这是特征不是故障。")
            return

        w("\n  ⑥板块环境闸门（所属板块跌超1.5%的直接否决）：")
        imap = _get_industry_map()
        if not imap:
            w("    [报空] 行业榜拿不到，本关跳过（上面候选未经板块验证，慎用）")
            return
        passed = 0
        for h in hits:
            ind = _stock_industry(h["code"])
            ipct = imap.get(ind) if ind else None
            if ipct is None:
                w(f"    ❓ {h['name']}({h['code']}) 行业[{ind or '未知'}] 无板块数据，存疑")
                continue
            if ipct < -1.5:
                w(f"    ❌ {h['name']}({h['code']}) 板块[{ind}]{ipct:+.2f}% 逆风 → 否决")
                continue
            flag = "✅顺风" if ipct > 0 else "⚠️板块微跌"
            w(f"    {flag} {h['name']}({h['code']}) {h['price']} 今{h['pct']}% | "
              f"板块[{ind}]{ipct:+.2f}% | 60日{h['chg60']:.1f}% | "
              f"缩量{h['vr']:.2f} | 量比{h['ud']:.2f}")
            passed += 1
            time.sleep(0.5)

        if passed == 0:
            w("    ⚠️ 全部候选被板块闸门否决 → 今日无标的")
        else:
            w(f"  ※ 最终{passed}只过关。⑦催化日期 ⑧止损由你我集中分析定。")
    safe_run("冷低早筛选", _do)


# ========== 三、板块全景榜（行业 + 概念，都有历史库） ==========

def _load_hist(path):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                h = json.load(f)
                if isinstance(h, dict) and "days" in h:
                    return h
    except Exception:
        pass
    return {"days": {}}


def _fmt_tag(hist, name, today, rank_now, pct_now):
    if not hist["days"]:
        return " | 🆕库空(今日起积累)"
    ds = sorted([d for d in hist["days"] if d < today], reverse=True)
    streak = 0
    for d in ds:
        rec = hist["days"][d].get(name)
        if rec and rec.get("pct", 0) > 0:
            streak += 1
        else:
            break
    days = streak + 1 if pct_now > 0 else 0
    cum = pct_now
    for d in ds[:2]:
        rec = hist["days"][d].get(name)
        if rec:
            cum += rec.get("pct", 0)
    prev = None
    if ds:
        rec = hist["days"][ds[0]].get(name)
        if rec:
            prev = rec.get("rank")
    if days == 0:
        tag = "今日转跌"
    elif days == 1:
        tag = "🆕第1天(刚启动)"
    elif days >= 5:
        tag = f"🔥连{days}天 ⚠️高潮慎追"
    elif days >= 3:
        tag = f"🔥连{days}天"
    else:
        tag = f"连{days}天(仍早)"
    c3 = f" 3日{cum:+.1f}%" if len(ds) >= 2 else ""
    rk = ""
    if prev:
        if prev - rank_now >= 8:
            rk = f" 🚀{prev}→{rank_now}名"
        elif rank_now - prev >= 8:
            rk = f" 📉{prev}→{rank_now}名"
        else:
            rk = f" {prev}→{rank_now}名"
    return f" | {tag}{c3}{rk}"


def scan_board_rank():
    w("\n【三、板块全景榜】板块|涨跌|领涨股|连涨天数|3日累计|排名变化")
    bj = now_beijing()
    today = bj.strftime("%Y-%m-%d")
    is_intra = (bj.weekday() < 5) and (9 <= bj.hour < 15)
    # 只有交易日收盘后(15点起)才写库；凌晨/盘前跑的数据属于上一交易日，写入会污染历史库
    can_save = (bj.weekday() < 5) and (bj.hour >= 15)
    if not is_intra and not can_save:
        w("  ⚠️ 当前非收盘时段(数据属上一交易日)，本次只读不写库")
    hist_ind = _load_hist(HIST_FILE)
    hist_con = _load_hist(CONCEPT_FILE)
    w(f"  （行业库{len(hist_ind['days'])}天 | 概念库{len(hist_con['days'])}天）")

    saved_ind = {}
    saved_con = {}

    def _rank(title, sources, hist, store):
        src, df = multi_source(title, sources)
        if df is None:
            raise RuntimeError(f"{title}全源失败")
        c_name = pick_col(df, ["板块名称", "概念名称", "板块", "名称", "行业"])
        c_pct = pick_col(df, ["涨跌幅", "涨跌"])
        c_lead = pick_col(df, ["领涨股票", "领涨股"])
        if not c_name or not c_pct:
            raise RuntimeError(f"{title}缺字段 列名={list(df.columns)[:8]}")
        df = df.copy()
        df[c_pct] = pd.to_numeric(df[c_pct], errors="coerce")
        df = df.dropna(subset=[c_pct]).sort_values(c_pct, ascending=False)
        w(f"  ◆ {title}涨幅前15（源：{src}，共{len(df)}个）：")
        for i, (_, r) in enumerate(df.head(15).iterrows(), 1):
            nm = str(r[c_name])
            lead = f" 领涨:{r[c_lead]}" if c_lead else ""
            w(f"    {nm} | {r[c_pct]}%{lead}{_fmt_tag(hist, nm, today, i, r[c_pct])}")
        w(f"  ◆ {title}跌幅前5：")
        for _, r in df.tail(5).iloc[::-1].iterrows():
            w(f"    {r[c_name]} | {r[c_pct]}%")
        if can_save:
            for i, (_, r) in enumerate(df.iterrows(), 1):
                store[str(r[c_name])] = {"pct": round(float(r[c_pct]), 2), "rank": i}

    def _industry():
        _rank("行业", [
            ("东财", lambda: ak.stock_board_industry_name_em()),
            ("同花顺", lambda: ak.stock_board_industry_summary_ths()),
            ("同花顺资金流", lambda: ak.stock_fund_flow_industry(symbol="即时")),
        ], hist_ind, saved_ind)
    safe_run("行业板块榜", _industry)

    def _concept():
        _rank("概念", [
            ("东财", lambda: ak.stock_board_concept_name_em()),
            ("同花顺资金流", lambda: ak.stock_fund_flow_concept(symbol="即时")),
            ("同花顺", lambda: ak.stock_board_concept_summary_ths()),
        ], hist_con, saved_con)
    safe_run("概念板块榜", _concept)

    def _save(store, hist, path, label):
        if not store or not can_save:
            return
        try:
            hist["days"][today] = store
            ks = sorted(hist["days"])[-40:]
            hist["days"] = {k: hist["days"][k] for k in ks}
            os.makedirs("reports", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(hist, f, ensure_ascii=False)
            w(f"  ✅ 已记录{today} {label}{len(store)}个，库{len(hist['days'])}天")
        except Exception as e:
            w(f"  [跳过] {label}写入：{type(e).__name__}")

    _save(saved_ind, hist_ind, HIST_FILE, "行业")
    _save(saved_con, hist_con, CONCEPT_FILE, "概念")


# ========== 四、板块资金流 ==========

def scan_sector_flow():
    w("\n【四、板块资金流向】（亿元）")

    def _do():
        src, df = multi_source("行业资金流", [
            ("东财", lambda: ak.stock_sector_fund_flow_rank(
                indicator="今日", sector_type="行业资金流")),
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
    "① 名人喊话": ["马斯克", "黄仁勋", "特朗普", "鲍威尔", "沃什", "巴菲特", "伯里",
                "段永平", "奥特曼", "孙正义", "库克", "雷军", "习近平", "李强"],
    "② 政策·国内": ["国务院", "发改委", "财政部", "央行", "证监会", "工信部", "十五五",
                 "国常会", "补贴", "规划", "部署", "统计局", "医保", "国新办", "市场监管总局"],
    "③ 政策·海外": ["白宫", "美联储", "加息", "降息", "关税", "出口管制", "商务部",
                 "外交部", "制裁", "欧盟", "CPI", "非农"],
    "④ 科技·产业": ["AI", "算力", "半导体", "芯片", "光模块", "CPO", "PCB", "机器人",
                 "商业航天", "卫星", "固态电池", "创新药", "存储", "英伟达", "台积电",
                 "阿斯麦", "液冷", "光刻", "覆铜板", "昇腾", "脑机接口", "具身"],
    "⑤ 大宗·地缘": ["石油", "原油", "黄金", "铜", "锂", "稀土", "煤", "战争", "霍尔木兹",
                 "伊朗", "以色列", "地缘", "OPEC", "天然气", "曼德海峡"],
    "⑥ 资金·事件": ["打新", "IPO", "长鑫", "并购", "重组", "预增", "增持", "减持",
                 "回购", "举牌", "分红", "中标", "定增", "ETF"],
    "⑦ 消费·养殖": ["白酒", "消费", "生猪", "猪价", "养殖", "宠物", "零售", "旅游",
                 "免税", "影视", "票房"],
    "⑧ 政策·产业(专项)": ["锂电池", "锂电", "钠离子", "钠电", "消费税", "征税", "免税",
                 "退税", "出清", "供给侧", "反内卷", "涨价", "限产", "减产", "关税",
                 "出口管制", "反倾销", "专项债", "特别国债", "以旧换新", "设备更新",
                 "收储", "涨电价", "电价", "集采", "国家队", "汇金", "平准", "增持回购"],
}


def _fetch_news(fn):
    df = with_retry(fn, tries=2, wait=3)
    if df is None or len(df) == 0:
        return []
    c_title = pick_col(df, ["标题", "内容", "新闻", "摘要"])
    c_time = pick_col(df, ["发布时间", "时间", "日期"])
    out = []
    for _, r in df.iterrows():
        t = str(r[c_title]).strip() if c_title else ""
        tm = str(r[c_time])[:16] if c_time else ""
        if t and t != "nan":
            out.append((tm, t))
    return out


def scan_news():
    w("\n【九、新闻电报流 + 关键词雷达】全谱信息面")

    sources = [
        ("财联社", lambda: ak.stock_info_global_cls(symbol="全部")),
        ("财联社2", lambda: ak.stock_info_cjzc_em()),
        ("东财", lambda: ak.stock_info_global_em()),
        ("新浪", lambda: ak.stock_info_global_sina()),
        ("同花顺", lambda: ak.stock_info_global_ths()),
        ("富途", lambda: ak.stock_info_global_futu()),
    ]

    allnews, ok = [], []
    for name, fn in sources:
        try:
            items = _fetch_news(fn)
            if items:
                allnews.extend(items)
                ok.append(f"{name}({len(items)})")
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

    w(f"  （合并去重：{'、'.join(ok)} → 共{len(uniq)}条）")
    w("\n  ★★★ 关键情报雷达 ★★★")
    any_hit = False
    for cat, kws in NEWS_RADAR.items():
        hits, hseen = [], set()
        for tm, t in uniq:
            if any(k in t for k in kws) and t[:30] not in hseen:
                hseen.add(t[:30])
                hits.append((tm, t))
        if hits:
            any_hit = True
            w(f"  【{cat}】")
            for tm, t in hits[:12]:
                w(f"    [{tm}] {t[:75]}")
    if not any_hit:
        w("  （本次无命中关注关键词）")

    w("\n  ◆ 全量新闻流（最近100条）：")
    for tm, t in uniq[:100]:
        w(f"    [{tm}] {t[:70]}")


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
    w(f"A股作战扫描器V1.7.2 | {bj.strftime('%Y-%m-%d %H:%M')} {weekday} | {mode}")
    w("=" * 60)

    if weekend:
        scan_news()
    else:
        scan_regime_gate()
        scan_tomorrow_gate()
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
    date = bj.strftime("%Y%m%d")
    prefix = "盘中" if intraday else ("周末" if weekend else "盘后")

    for path in [f"reports/{prefix}_最新.txt", f"reports/{prefix}_{date}.txt",
                 "reports/latest.txt"]:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    print(f"\n✅ V1.7.2完成 {prefix}_最新.txt")


if __name__ == "__main__":
    main()

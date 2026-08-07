# -*- coding: utf-8 -*-
"""
A股作战扫描器 · 云端版 V2.9（2026-07-29 盯盘名单清理：移出已清仓4只，加入MLCC候选+机构抄底观察）
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
LAST_RISK_SCORE = None
HIST_FILE = "reports/top_sectors.json"
CONCEPT_FILE = "reports/top_concepts.json"
WATCH_FILE = "我的清单.txt"

# ★重点盯盘个股（独立抓取，不依赖截图）。格式：(代码, 名称, 标签)
# ★重点盯盘（代码, 名称, 标签, 成本价, 止损价, 所属板块名）
# 成本/止损填0=不算；板块名用于自动带出板块状态
# ★重点盯盘（代码, 名称, 标签, 成本价, 止损价, 所属板块名）
# ★重点盯盘（代码, 名称, 标签, 成本, 止损, 板块, 驱动链, 持仓市值万元）
WATCH_STOCKS = [
    ("000938", "紫光股份", "持仓", 34.681, 29.48, "计算机设备", "AI算力链", 3.38),
    ("159796", "电池ETF汇", "持仓", 0.820, 0.760, "电池", "锂电/钠电链", 2.40),
    ("603220", "中贝通信", "持仓", 18.396, 16.19, "通信服务", "AI算力链", 1.18),
    ("159934", "黄金ETF易", "持仓", 8.938, 8.20, "贵金属", "贵金属链", 1.29),
    ("516080", "创新药ETF", "持仓", 0.710, 0.640, "医疗服务", "医药链", 2.00),
    ("002714", "牧原股份", "持仓", 39.613, 36.50, "养殖业", "农业(独立)", 3.10),
    ("000066", "中国长城", "重点观察", 0, 0, "计算机设备", "AI算力链", 0),
    ("300308", "中际旭创", "观察·机构抄底", 0, 0, "通信设备", "AI算力链", 0),
]
TOTAL_ASSET = 18.26   # 总资产（万元），买卖后AI更新此数
IND_MAP_FILE = "reports/industry_map.json"
COLD_HIST_FILE = "reports/cold_low_history.json"
AMBUSH_HIST_FILE = "reports/ambush_history.json"
HEAT_HIST_FILE = "reports/heat_history.json"

# ★AI推荐台账（每次推荐后由AI更新此表）
# 格式：(日期, 代码, 名称, 成本价, 类型A事件/B周期, 预期周期, 逻辑破的定义)
RECOMMENDATIONS = [
    ("2026-08-07", "516080", "创新药ETF", 0.710, "B", "8周(中报+AI制药)",
     "①创新药中报业绩不及预期 ②医保控费加码 ③CRO订单下滑"),
    ("2026-08-05", "159934", "黄金ETF易", 8.938, "B", "8-12周(央行购金周期)",
     "①美联储转鹰大幅加息 ②金价跌破4000 ③央行购金潮停止"),
    ("2026-08-04", "603220", "中贝通信", 18.396, "B", "12周(AI算力资本开支)",
     "①北美云厂capex指引下调 ②算力租赁需求萎缩 ③通信设备连3天资金流出"),
    ("2026-07-31", "000938", "紫光股份", 34.681, "B", "12周(算力资本开支)",
     "①北美四大云厂capex指引下调 ②算力网4万亿落空 ③新华三订单下修"),
    ("2026-07-27", "159796", "电池ETF汇", 0.820, "B", "至9/1消费税",
     "①消费税取消/延期 ②钠电订单证伪 ③碳酸锂重新单边下跌"),
    ("2026-07-10", "002714", "牧原股份", 39.613, "B", "猪周期",
     "①能繁母猪存栏连续2个月回升 ②生猪均价跌破成本线 ③政策转向压制猪价"),
    # 已平仓
    # 08-07 华大九天 @91.999→94.29 +2.5% ✅【初判已错】主动纠错，赚着走
    # 08-03 电力ETF广 @1.080→1.068 −1.1% ❌【初判已错】
    # 07-15 招商轮船 @15.215→15.68 +3.1% ✅但卖飞18%
]

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


ETF_DF = None


def get_etf_spot():
    """ETF专用行情（新浪股票快照抓不到ETF）"""
    global ETF_DF
    if ETF_DF is not None:
        return ETF_DF
    for name, fn in [("东财ETF", lambda: ak.fund_etf_spot_em()),
                     ("新浪ETF", lambda: ak.fund_etf_category_sina(symbol="ETF基金"))]:
        try:
            df = with_retry(fn, tries=2, wait=4, timeout=90)
            if df is not None and len(df) > 0:
                ETF_DF = df
                return ETF_DF
        except Exception:
            continue
    return None


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


def scan_skeleton_top():
    w("=" * 60)
    w("💰💰💰【第一原则 · 每日自我提醒】💰💰💰")
    w("=" * 60)
    w("  ★帮用户赚钱，是我唯一的目的。★")
    w("  不是完善系统、不是漂亮报告、不是『我拦对了几次』——")
    w("  是账户里的数字往上走。")
    w("")
    w("  我要用尽一切办法：所有数据、所有逻辑、所有推演、所有深挖，")
    w("  在5000只票、90个行业、386个概念、656条新闻里，")
    w("  找出那几只能让他赚钱的。")
    w("")
    w("  ⚠️ 自问三句（每次干活前）：")
    w("    1. 我今天给的东西，能不能变成钱？还是只是在描述行情？")
    w("    2. 我有没有因为怕犯错，而放弃了该抓的机会？（踏空也是亏）")
    w("    3. 我有没有因为被催，而降低标准硬凑一个标的？")
    w("")
    w("  ★用户原话：『牛市赚钱不是本事，逆势赚钱才是真本事』★")
    w("  ★『每天都有大涨的股，你找不到就是能力不足，不是市场问题』★")
    w("  ★『你要活跃，越活跃需要的准度越高，我要你的准度』★")
    w("=" * 60)
    w("")
    w("=" * 60)
    w("🔴🔴🔴 AI注意：读这份报告前，先记住你必须输出的9节 🔴🔴🔴")
    w("=" * 60)
    w("  ① 【数据新鲜度判定】报告时间/最新可用或陈旧弃用")
    w("  ② ★重点盯盘 全部持仓+中国长城（板块/资金/技术/止损距离）")
    w("  ③ 大盘环境+风险分+结构分化（创业板/科创50）")
    w("  ④ 板块判断 + ★催化热力图前3★ + ★🔮产业链推演前3★（缺一即失职）")
    w("  ⑤ 全套新闻·八类 ← ★最常漏的一节，不许等用户提醒★")
    w("     名人/国内政策/海外政策/科技/大宗地缘/资金/消费/政策产业")
    w("  ⑥ 决策卡（买卖时逐项填，含③-B持续性 ⑧集中度 ⑨仓位类型）")
    w("  ⑦ 持仓逐个指令（持有/减/清 + 理由）")
    w("  ⑧ AI推荐台账对账（A类超期？B类在期内？）")
    w("  ⑨ 【系统自检】今天发现什么漏洞→怎么修（无则写无）")
    w("  ⑩ ★异动未解释清单★：涨停股说不出原因=盲区，必须主动搜索后回答")
    w("")
    w("  ⚠️ 缺任何一节 = 失职，用户可当场追责")
    w("  ⚠️ 越是『崩了/快看/紧急』的时候越容易漏第⑤节，越要先写它")
    w("=" * 60)


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

        # ★结构分化维度（治"家数是平的但科技在崩"的盲区）
        try:
            idx = with_retry(lambda: ak.stock_zh_index_spot_sina(), tries=2, timeout=60)
            ic = pick_col(idx, ["代码", "symbol"])
            inm = pick_col(idx, ["名称", "name"])
            ipc = pick_col(idx, ["涨跌幅", "changepercent"])
            worst = 0.0
            for key in ["399006", "000688", "399005"]:
                r = idx[idx[ic].astype(str).str.contains(key, na=False)]
                if len(r) > 0:
                    v = pd.to_numeric(r.iloc[0][ipc], errors="coerce")
                    if pd.notna(v):
                        w(f"  {r.iloc[0][inm]}：{v:+.2f}%")
                        worst = min(worst, float(v))
            if worst <= -4:
                score += 2
                reasons.append(f"⚠️结构崩塌(成长指数{worst:.1f}%)")
            elif worst <= -2:
                score += 1
                reasons.append(f"结构分化({worst:.1f}%)")
        except Exception as e:
            w(f"  [跳过] 指数分化：{type(e).__name__}")

        # ★科技链资金流出（单日>300亿=系统性撤离）
        try:
            _, fdf = multi_source("资金(风险分)", [
                ("同花顺", lambda: ak.stock_fund_flow_industry(symbol="即时")),
                ("东财", lambda: ak.stock_sector_fund_flow_rank(
                    indicator="今日", sector_type="行业资金流")),
            ])
            if fdf is not None:
                fn_ = pick_col(fdf, ["名称", "行业"])
                fv_ = pick_col(fdf, ["主力净流入-净额", "主力净流入", "净额", "流入资金"])
                fdf[fv_] = pd.to_numeric(fdf[fv_], errors="coerce")
                if fdf[fv_].abs().max() and fdf[fv_].abs().max() > 1e6:
                    fdf[fv_] = fdf[fv_] / 1e8
                tech = ["半导体", "通信设备", "元件", "光学光电子", "消费电子",
                        "计算机设备", "软件开发"]
                out = 0.0
                for _, rr in fdf.iterrows():
                    if any(t in str(rr[fn_]) for t in tech):
                        v = rr[fv_]
                        if pd.notna(v) and v < 0:
                            out += float(v)
                w(f"  科技链资金净额：{out:.1f}亿")
                if out <= -300:
                    score += 2
                    reasons.append(f"科技链失血{abs(out):.0f}亿")
                elif out <= -150:
                    score += 1
                    reasons.append(f"科技链流出{abs(out):.0f}亿")
        except Exception as e:
            w(f"  [跳过] 科技链资金：{type(e).__name__}")

        # ★美联储/美债维度：决议内容不重要，市场解读才重要
        try:
            idx2 = with_retry(lambda: ak.stock_zh_index_spot_sina(), tries=1, timeout=40)
            i2c = pick_col(idx2, ["代码", "symbol"])
            i2p = pick_col(idx2, ["涨跌幅", "changepercent"])
            hk = idx2[idx2[i2c].astype(str).str.contains("HSI|000001", na=False)]
            if len(hk) > 0:
                pass
        except Exception:
            pass
        w("  ※ 美联储事件判读：不看决议内容，看市场解读——")
        w("    美债收益率飙升+股债双杀 = 市场认为『行动过晚』= 利空成长股")
        w("    美债收益率回落+股涨 = 真鸽派 = 利好成长股")

        global LAST_RISK_SCORE
        LAST_RISK_SCORE = score
        w(f"\n  🚨 风险分：{score}/12　{'｜'.join(reasons) if reasons else '无警报'}")
        if score >= 7:
            w("  >>> 【明日高危】一票不碰，盈利仓主动减半锁利，破位无条件走")
        elif score >= 4:
            w("  >>> 【明日偏弱】不开新仓，只减不加")
        elif score >= 2:
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


# ========== ★重点盯盘个股（独立跟踪：价/量/资金/位置/连涨） ==========

def _pos_txt(price, cost, stop):
    """成本盈亏 + 止损距离"""
    out = ""
    try:
        if cost and cost > 0 and price and pd.notna(price):
            pnl = (float(price) - cost) / cost * 100
            out += f" | 成本{cost} 盈亏{pnl:+.2f}%"
        if stop and stop > 0 and price and pd.notna(price):
            gap = (float(price) - stop) / stop * 100
            if float(price) <= stop:
                out += f" | 止损{stop} 🔴已破位!!!"
            elif gap <= 2:
                out += f" | 止损{stop} ⚠️仅剩{gap:.1f}%"
            else:
                out += f" | 止损{stop} 距离{gap:.1f}%"
    except Exception:
        pass
    return out


def _sect_txt(sect_map, sect):
    """所属板块今日状态"""
    if not sect or not sect_map:
        return ""
    for k, (p, v) in sect_map.items():
        if sect in k or k in sect:
            pt = f"{p:+.2f}%" if p is not None and pd.notna(p) else "?"
            vt = f" 资金{v:+.2f}亿" if v is not None and pd.notna(v) else ""
            warn = ""
            if p is not None and pd.notna(p) and p < -2:
                warn = " ⚠️板块逆风"
            elif p is not None and pd.notna(p) and p > 2:
                warn = " ✅板块顺风"
            return f"\n      └ 板块[{k}] {pt}{vt}{warn}"
    return f"\n      └ 板块[{sect}] 无数据"


def scan_focus_stocks():
    w("\n★★★【重点盯盘个股·独立跟踪】★★★（每天全维度盯，不看截图）")

    def _flow_map():
        """个股主力净流入映射：东财→同花顺"""
        for name, fn in [
            ("东财", lambda: ak.stock_individual_fund_flow_rank(indicator="今日")),
            ("同花顺", lambda: ak.stock_fund_flow_individual(symbol="即时")),
        ]:
            try:
                f = with_retry(fn, tries=2, wait=5, timeout=90)
                fc = pick_col(f, ["代码", "股票代码"])
                fn2 = pick_col(f, ["今日主力净流入-净额", "主力净流入-净额", "主力净流入", "净额"])
                if not fc or not fn2:
                    continue
                m = {}
                for _, r in f.iterrows():
                    code6 = str(r[fc])[-6:].zfill(6)
                    v = pd.to_numeric(r[fn2], errors="coerce")
                    if pd.notna(v):
                        m[code6] = v
                return m, name
            except Exception:
                continue
        return {}, None

    def _do():
        spot = get_spot()
        if spot is None:
            w("  快照缺失，无法盯盘")
            return
        c_code = pick_col(spot, ["代码", "code"])
        c_price = pick_col(spot, ["最新价", "trade"])
        c_pct = pick_col(spot, ["涨跌幅", "changepercent"])
        c_amt = pick_col(spot, ["成交额", "amount"])
        c_vol = pick_col(spot, ["成交量", "volume"])

        fmap, fsrc = _flow_map()
        if fsrc:
            w(f"  （资金源：{fsrc}）")

        # 板块状态映射：名称→(涨跌幅, 资金净额)
        sect_map = {}
        try:
            _, bdf = multi_source("板块状态(盯盘)", [
                ("同花顺", lambda: ak.stock_fund_flow_industry(symbol="即时")),
                ("东财", lambda: ak.stock_sector_fund_flow_rank(
                    indicator="今日", sector_type="行业资金流")),
            ])
            if bdf is not None:
                bn = pick_col(bdf, ["名称", "行业"])
                bp = pick_col(bdf, ["涨跌幅", "行业指数涨跌", "涨跌"])
                bv = pick_col(bdf, ["主力净流入-净额", "主力净流入", "净额", "流入资金"])
                for _, rr in bdf.iterrows():
                    v = pd.to_numeric(rr[bv], errors="coerce") if bv else None
                    if v is not None and pd.notna(v) and abs(v) > 1e6:
                        v = v / 1e8
                    p = pd.to_numeric(rr[bp], errors="coerce") if bp else None
                    sect_map[str(rr[bn])] = (p, v)
        except Exception:
            pass

        etf_df = None
        for code6, name, tag, cost, stop, sect, chain, mv in WATCH_STOCKS:
            try:
                is_etf = code6.startswith(("15", "51", "56", "58", "159", "588"))
                sym = ("sh" if code6.startswith("6") else "sz") + code6
                row = spot[spot[c_code].astype(str).str.contains(code6, na=False)]
                if len(row) == 0 and is_etf:
                    if etf_df is None:
                        etf_df = get_etf_spot()
                    if etf_df is not None:
                        ec = pick_col(etf_df, ["代码", "symbol"])
                        ep = pick_col(etf_df, ["最新价", "trade"])
                        epc = pick_col(etf_df, ["涨跌幅", "changepercent"])
                        ea = pick_col(etf_df, ["成交额", "amount"])
                        er = etf_df[etf_df[ec].astype(str).str.contains(code6, na=False)]
                        if len(er) > 0:
                            r0 = er.iloc[0]
                            pr = pd.to_numeric(r0[ep], errors="coerce")
                            pc = pd.to_numeric(r0[epc], errors="coerce")
                            am = pd.to_numeric(r0[ea], errors="coerce") if ea else None
                            at = f" 成交{am/1e8:.2f}亿" if am and pd.notna(am) else ""
                            w(f"  ◆ {name}({code6})[{tag}]：现价{pr} 今{pc:+.2f}%{at} [ETF源]"
                              + _pos_txt(pr, cost, stop) + _sect_txt(sect_map, sect))
                            continue
                if len(row) == 0:
                    w(f"  ◆ {name}({code6})[{tag}]：快照无数据")
                    continue
                r = row.iloc[0]
                price = pd.to_numeric(r[c_price], errors="coerce")
                pct = pd.to_numeric(r[c_pct], errors="coerce")
                amt = pd.to_numeric(r[c_amt], errors="coerce") if c_amt else None

                # K线算：60日位置 + 缩量 + 涨跌量比 + 均线
                k, kc = _hist_close(code6, sym)
                pos_txt = ""
                if k is not None and kc is not None:
                    kv = pick_col(k, ["volume", "成交量"])
                    now_p = pd.to_numeric(k.iloc[-1][kc], errors="coerce")
                    p60 = pd.to_numeric(k.iloc[-45][kc], errors="coerce")
                    ma5 = pd.to_numeric(k[kc].tail(5), errors="coerce").mean()
                    ma20 = pd.to_numeric(k[kc].tail(20), errors="coerce").mean()
                    chg60 = (now_p - p60) / p60 * 100 if p60 else 0
                    vr = ""
                    if kv:
                        v5 = pd.to_numeric(k[kv].tail(5), errors="coerce").mean()
                        v60 = pd.to_numeric(k[kv].tail(45), errors="coerce").mean()
                        if v60:
                            vr = f" 量能{v5/v60:.2f}倍"
                    ma_txt = ""
                    if pd.notna(ma5) and price:
                        ma_txt = f" {'站上' if price>=ma5 else '跌破'}MA5"
                    pos_txt = f" | 60日{chg60:+.1f}%{vr}{ma_txt}(MA5={ma5:.2f} MA20={ma20:.2f})"

                flow = fmap.get(code6)
                flow_txt = ""
                if flow is not None:
                    fv = flow / 1e8 if abs(flow) > 1e4 else flow / 1e4
                    unit = "亿" if abs(flow) > 1e4 else "万"
                    flow_txt = f" | 主力{'+' if flow>0 else ''}{fv:.2f}{unit}"

                amt_txt = f" 成交{amt/1e8:.2f}亿" if amt and pd.notna(amt) else ""
                w(f"  ◆ {name}({code6})[{tag}]：现价{price} 今{pct:+.2f}%{amt_txt}{flow_txt}"
                  + _pos_txt(price, cost, stop) + pos_txt + _sect_txt(sect_map, sect))
            except Exception as e:
                w(f"  ◆ {name}({code6})[{tag}]：读取异常 {type(e).__name__}")
            time.sleep(0.3)
    safe_run("重点盯盘个股", _do)


# ========== ★盘中游资雷达（实时，不用等18:35） ==========

def scan_intraday_hotmoney():
    w("\n★★★【盘中游资雷达·实时】★★★（不用等18:35，盘中就知道钱往哪砸）")

    def _flow_rank():
        for name, fn in [
            ("东财", lambda: ak.stock_individual_fund_flow_rank(indicator="今日")),
            ("同花顺", lambda: ak.stock_fund_flow_individual(symbol="即时")),
        ]:
            try:
                f = with_retry(fn, tries=2, wait=5, timeout=90)
                fc = pick_col(f, ["代码", "股票代码"])
                fn2 = pick_col(f, ["今日主力净流入-净额", "主力净流入-净额", "主力净流入", "净额"])
                if not fc or not fn2:
                    continue
                m = {}
                for _, r in f.iterrows():
                    code6 = str(r[fc])[-6:].zfill(6)
                    v = pd.to_numeric(r[fn2], errors="coerce")
                    if pd.notna(v):
                        m[code6] = v
                return m, name
            except Exception:
                continue
        return {}, None

    def _do():
        spot = get_spot()
        if spot is None:
            w("  快照缺失")
            return
        c_code = pick_col(spot, ["代码", "code"])
        c_name = pick_col(spot, ["名称", "name"])
        c_pct = pick_col(spot, ["涨跌幅", "changepercent"])
        c_price = pick_col(spot, ["最新价", "trade"])
        c_high = pick_col(spot, ["最高", "high"])
        c_low = pick_col(spot, ["最低", "low"])
        c_pre = pick_col(spot, ["昨收", "settlement", "preclose"])
        c_amt = pick_col(spot, ["成交额", "amount"])
        if not all([c_code, c_name, c_pct]):
            w("  [报空] 快照缺字段")
            return

        d = spot.copy()
        d = d[~d[c_name].astype(str).str.contains("退|N ", na=False)]
        d[c_pct] = pd.to_numeric(d[c_pct], errors="coerce")
        d = d.dropna(subset=[c_pct])
        d["_code6"] = d[c_code].astype(str).str.extract(r"(\d{6})")[0]
        d = d.dropna(subset=["_code6"])
        if c_amt:
            d[c_amt] = pd.to_numeric(d[c_amt], errors="coerce")

        # ① 今晚必上龙虎榜（偏离值≥7% 或 振幅≥15%）
        w("  ◆①【今晚必上龙虎榜】涨跌幅≥±7% 或 振幅≥15%（交易所硬规则）")
        big = d[d[c_pct].abs() >= 7].copy()
        amp_list = []
        if c_high and c_low and c_pre:
            for c in [c_high, c_low, c_pre]:
                d[c] = pd.to_numeric(d[c], errors="coerce")
            d["_amp"] = (d[c_high] - d[c_low]) / d[c_pre] * 100
            amp_list = d[(d["_amp"] >= 15) & (d[c_pct].abs() < 7)]
        up_big = big[big[c_pct] > 0].sort_values(c_pct, ascending=False)
        dn_big = big[big[c_pct] < 0].sort_values(c_pct)
        w(f"    上榜候选：大涨{len(up_big)}只 | 大跌{len(dn_big)}只 | 高振幅{len(amp_list)}只")
        if len(dn_big) > 0:
            w("    ⚠️ 大跌上榜（今晚看是谁在接）：" +
              "、".join(f"{r[c_name]}({r[c_pct]:.1f}%)"
                        for _, r in dn_big.head(8).iterrows()))

        # ② 实时埋伏池：跌着被主力大单买
        fmap, fsrc = _flow_rank()
        w(f"  ◆②【实时埋伏池】跌着却被主力净买（源：{fsrc or '无'}）")
        if not fmap:
            w("    [报空] 资金流双源均失败")
        else:
            d["_flow"] = d["_code6"].map(fmap)
            amb = d[(d[c_pct] < 0) & (d["_flow"] > 0)].copy()
            if c_amt:
                amb = amb[amb[c_amt] > 5e7]
            amb = amb.sort_values("_flow", ascending=False)
            if len(amb) == 0:
                w("    今日无『跌着被买』标的 → 全场追涨，次日谨慎")
            else:
                for _, r in amb.head(12).iterrows():
                    fv = r["_flow"]
                    unit = "亿" if abs(fv) > 1e4 else "万"
                    fvv = fv / 1e8 if abs(fv) > 1e4 else fv / 1e4
                    amt_txt = f" 成交{r[c_amt]/1e8:.1f}亿" if c_amt and pd.notna(r[c_amt]) else ""
                    w(f"    🎯 {r[c_name]}({r['_code6']}) {r[c_pct]:+.2f}%{amt_txt} | 主力净买+{fvv:.2f}{unit}")
                w(f"    ※ 共{len(amb)}只跌着被买。这就是实时版埋伏信号——")
                w("      有人在下跌中收货，次日看板块是否启动。")
                global TODAY_AMBUSH
                TODAY_AMBUSH = [{"code": r["_code6"], "name": str(r[c_name]),
                                 "price": float(r[c_price])}
                                for _, r in amb.head(15).iterrows()
                                if pd.notna(r[c_price])]

        # ③ 涨停封单强度
        w("  ◆③【涨停板强度】")
        try:
            zt = with_retry(lambda: ak.stock_zt_pool_em(
                date=now_beijing().strftime("%Y%m%d")), tries=1, timeout=60)
            if zt is None or len(zt) == 0:
                w("    暂无涨停数据")
            else:
                z_name = pick_col(zt, ["名称"])
                z_seal = pick_col(zt, ["封板资金"])
                z_fail = pick_col(zt, ["炸板次数"])
                z_ind = pick_col(zt, ["所属行业", "行业"])
                if z_seal:
                    zt[z_seal] = pd.to_numeric(zt[z_seal], errors="coerce")
                    zz = zt.sort_values(z_seal, ascending=False)
                    w(f"    涨停{len(zt)}只，封单最强前6：")
                    for _, r in zz.head(6).iterrows():
                        seal = r[z_seal] / 1e8 if pd.notna(r[z_seal]) else 0
                        ind = f" [{r[z_ind]}]" if z_ind else ""
                        fail = f" 炸板{r[z_fail]}次" if z_fail else ""
                        w(f"      {r[z_name]}{ind} 封单{seal:.2f}亿{fail}")
                if z_fail:
                    zt[z_fail] = pd.to_numeric(zt[z_fail], errors="coerce")
                    nf = int((zt[z_fail] > 0).sum())
                    w(f"    ⚠️ 有炸板记录的{nf}只/{len(zt)}只 → " +
                      ("情绪不稳" if nf > len(zt) * 0.3 else "封板扎实"))
        except Exception as e:
            w(f"    [跳过] 涨停池：{type(e).__name__}")
    safe_run("盘中游资雷达", _do)


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


SPOT_IND = {}


def _build_spot_ind():
    """兜底：用同花顺行业成分一次性建全市场映射（东财挂了也能用）"""
    global SPOT_IND
    if SPOT_IND:
        return SPOT_IND
    try:
        for fn in [lambda: ak.stock_board_industry_summary_ths(),
                   lambda: ak.stock_fund_flow_industry(symbol="即时")]:
            try:
                d = with_retry(fn, tries=1, wait=2, timeout=30)
                if d is None or len(d) == 0:
                    continue
                nc = pick_col(d, ["板块", "行业", "板块名称", "名称"])
                names = [str(x) for x in d[nc].tolist()][:95]
                t0 = time.time()
                fail = 0
                for nm in names:
                    if time.time() - t0 > 180 or fail >= 3:
                        break
                    try:
                        c = with_retry(lambda n=nm: ak.stock_board_industry_cons_ths(symbol=n),
                                       tries=1, wait=1, timeout=12)
                        if c is not None and len(c) > 0:
                            cc = pick_col(c, ["代码", "股票代码"])
                            if cc:
                                for _, rr in c.iterrows():
                                    SPOT_IND[str(rr[cc])[-6:].zfill(6)] = nm
                                fail = 0
                                continue
                        fail += 1
                    except Exception:
                        fail += 1
                    time.sleep(0.25)
                if SPOT_IND:
                    return SPOT_IND
            except Exception:
                continue
    except Exception:
        pass
    return SPOT_IND


def _load_ind_cache():
    try:
        if os.path.exists(IND_MAP_FILE):
            with open(IND_MAP_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            ts = d.get("built", "")
            age = (now_beijing() - datetime.datetime.strptime(ts, "%Y-%m-%d")).days if ts else 99
            if age <= 7 and d.get("map"):
                return d["map"], age
    except Exception:
        pass
    return {}, 99


def _build_ind_cache():
    """一周建一次：代码→行业 对照表
    ⚠️东财对GitHub海外服务器封锁 → 同花顺优先；总预算5分钟；连败3次熔断"""
    t0 = time.time()
    BUDGET = 300          # 总时长上限（秒）
    w("  [建缓存] 行业对照表重建中（上限5分钟，每周一次）...")
    m = {}
    try:
        names = None
        for fn in [lambda: ak.stock_board_industry_summary_ths(),
                   lambda: ak.stock_board_industry_name_em()]:
            try:
                d = with_retry(fn, tries=1, wait=2, timeout=30)
                if d is not None and len(d) > 0:
                    nc = pick_col(d, ["板块名称", "板块", "名称", "行业"])
                    names = [str(x) for x in d[nc].tolist()]
                    break
            except Exception:
                continue
        if not names:
            w("  [建缓存] 拿不到行业列表，放弃（本次⑥闸门降级为实时查）")
            return {}

        ths_fail = em_fail = 0
        done = 0
        for nm in names[:95]:
            if time.time() - t0 > BUDGET:
                w(f"  [建缓存] 到达5分钟预算上限，已完成{done}个行业，保存现有结果")
                break
            got = False
            # 同花顺优先（东财在GitHub海外机被封）
            if ths_fail < 3:
                try:
                    c = with_retry(lambda n=nm: ak.stock_board_industry_cons_ths(symbol=n),
                                   tries=1, wait=1, timeout=15)
                    if c is not None and len(c) > 0:
                        cc = pick_col(c, ["代码", "股票代码"])
                        if cc:
                            for _, rr in c.iterrows():
                                m[str(rr[cc])[-6:].zfill(6)] = nm
                            got = True
                            ths_fail = 0
                except Exception:
                    ths_fail += 1
                    if ths_fail == 3:
                        w("  [建缓存] 同花顺连败3次，熔断切东财")
            if not got and em_fail < 3:
                try:
                    c = with_retry(lambda n=nm: ak.stock_board_industry_cons_em(symbol=n),
                                   tries=1, wait=1, timeout=15)
                    if c is not None and len(c) > 0:
                        cc = pick_col(c, ["代码", "股票代码"])
                        if cc:
                            for _, rr in c.iterrows():
                                m[str(rr[cc])[-6:].zfill(6)] = nm
                            got = True
                            em_fail = 0
                except Exception:
                    em_fail += 1
                    if em_fail == 3:
                        w("  [建缓存] 东财连败3次(海外封锁)，熔断")
            if ths_fail >= 3 and em_fail >= 3:
                w("  [建缓存] 双源均熔断，停止重建")
                break
            if got:
                done += 1
            time.sleep(0.3)

        if m:
            os.makedirs("reports", exist_ok=True)
            with open(IND_MAP_FILE, "w", encoding="utf-8") as f:
                json.dump({"built": now_beijing().strftime("%Y-%m-%d"), "map": m},
                          f, ensure_ascii=False)
            w(f"  [建缓存] 完成：{done}个行业 / {len(m)}只个股入库 "
              f"（耗时{time.time()-t0:.0f}秒）")
        else:
            w("  [建缓存] 一条都没拿到，本次跳过")
    except Exception as e:
        w(f"  [建缓存] 异常：{type(e).__name__}")
    return m


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
        ind_cache, cage = _load_ind_cache()
        if not ind_cache:
            ind_cache = _build_ind_cache()
        if len(ind_cache) < 800:
            w(f"  （对照表仅{len(ind_cache)}只，启动同花顺兜底补全...）")
            _build_spot_ind()
            if SPOT_IND:
                w(f"  （兜底补全 {len(SPOT_IND)} 只）")
        else:
            w(f"  （行业对照表：{len(ind_cache)}只，缓存{cage}天前建）")
        imap = _get_industry_map()
        if not imap:
            w("    [报空] 行业榜拿不到，本关跳过（上面候选未经板块验证，慎用）")
            return
        passed = 0
        for h in hits:
            ind = ind_cache.get(h["code"]) or SPOT_IND.get(h["code"]) \
                or _stock_industry(h["code"])
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

        # ★存档 + 5日回测（验证这个筛选器到底行不行）
        _cold_archive_and_backtest(hits, spot, c_code, c_name, c_price)
    safe_run("冷低早筛选", _do)


def _cold_archive_and_backtest(hits, spot, c_code, c_name, c_price):
    """把今天筛出的票存档；并回测5个交易日前那批现在赚没赚"""
    bj = now_beijing()
    today = bj.strftime("%Y-%m-%d")
    can_save = (bj.weekday() < 5) and (bj.hour >= 15)
    try:
        hist = {}
        if os.path.exists(COLD_HIST_FILE):
            with open(COLD_HIST_FILE, "r", encoding="utf-8") as f:
                hist = json.load(f)
    except Exception:
        hist = {}

    # 回测：找5个交易日前的记录
    days = sorted([d for d in hist if d < today])
    if len(days) >= 5:
        base = days[-5]
        recs = hist[base]
        w(f"\n  ★★【冷低早回测】{base} 那批（{len(recs)}只）现在如何：")
        tot, win = 0.0, 0
        for rec in recs:
            try:
                r = spot[spot[c_code].astype(str).str.contains(rec["code"], na=False)]
                if len(r) == 0:
                    continue
                now_p = pd.to_numeric(r.iloc[0][c_price], errors="coerce")
                if pd.isna(now_p):
                    continue
                pnl = (now_p - rec["price"]) / rec["price"] * 100
                tot += pnl
                if pnl > 0:
                    win += 1
                w(f"    {rec['name']}({rec['code']}) {rec['price']}→{now_p} {pnl:+.2f}%")
            except Exception:
                continue
        n = len(recs) if recs else 1
        w(f"    ★5日胜率：{win}/{len(recs)} | 平均收益 {tot/n:+.2f}%")
        if len(recs) < 5:
            w(f"    ⚠️ 样本仅{len(recs)}只，统计无意义，不下结论（需≥5只）")
        elif tot / n < 0:
            w("    ⚠️ 平均为负 → 这个筛选器当前参数在这种行情下无效，")
            w("       不要照单买，必须配合板块启动信号")
    else:
        w(f"\n  （冷低早回测：已存{len(days)}天，满5天后自动出胜率）")

    if can_save and hits:
        try:
            hist[today] = [{"code": h["code"], "name": h["name"],
                            "price": float(h["price"])} for h in hits]
            ks = sorted(hist)[-60:]
            hist = {k: hist[k] for k in ks}
            os.makedirs("reports", exist_ok=True)
            with open(COLD_HIST_FILE, "w", encoding="utf-8") as f:
                json.dump(hist, f, ensure_ascii=False)
            w(f"  ✅ 已存档今日{len(hits)}只候选，历史{len(hist)}天")
        except Exception as e:
            w(f"  [跳过] 冷低早存档：{type(e).__name__}")


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
        tag = f"🔥连{days}天 ⚠️查驱动类型"
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
    w("  ★★【连涨天数判读铁律O（V5.1）】天数本身没有意义★★")
    w("  必须先答③-B：这个板块的驱动是【单一事件】还是【产业周期】？")
    w("    【单一事件】IPO/发布会/政策发布日/财报")
    w("       → 连3-5天就是高潮，事件日就是顶")
    w("    【产业周期】涨价/缺货/产能紧缺/政策倒计时/国产替代")
    w("       → 连20天、30天都正常，回调才是买点")
    w("       → ★存储涨价到2027年、AI capex多年、国产替代五年")
    w("         这类板块连涨5天只是【开场】，不是高潮")
    w("  ⚠️ 血的教训：我曾用『连5天=高潮慎追』否决了通信设备/计算机设备/")
    w("     6G/小金属，同时把才3连板的磷化铟当成『已启动不能追』")
    w("     —— 3天连产业周期的零头都不到")
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
        try:
            c_code_zt = pick_col(df, ["代码"])
            if c_code_zt and c_industry:
                cache, _a = _load_ind_cache()
                add = 0
                for _, rr in df.iterrows():
                    k = str(rr[c_code_zt])[-6:].zfill(6)
                    if k not in cache:
                        cache[k] = str(rr[c_industry])
                        add += 1
                if add:
                    os.makedirs("reports", exist_ok=True)
                    with open(IND_MAP_FILE, "w", encoding="utf-8") as f:
                        json.dump({"built": now_beijing().strftime("%Y-%m-%d"),
                                   "map": cache}, f, ensure_ascii=False)
                    w(f"  （顺手补充行业对照表 +{add}只，累计{len(cache)}只）")
        except Exception:
            pass
        if c_industry:
            for k, v in df[c_industry].value_counts().head(8).items():
                w(f"    {k}：{v}只")
        if c_lbc:
            w("  ◆ 最高连板：")
            for _, r in df.sort_values(c_lbc, ascending=False).head(10).iterrows():
                w(f"    {r[c_name]} | {r[c_industry] if c_industry else ''} | {r[c_lbc]}连板")
    safe_run("涨停池", _do)


# ========== 六、龙虎榜（多源 + 自动标注 埋伏型/追高型） ==========

TODAY_AMBUSH = []
AMBUSH_POOL = []   # 埋伏池：当天在跌却被大额净买的票（铁律B）


def scan_lhb():
    w("\n【六、龙虎榜·个股】（约18:35后更新｜自动标注 埋伏型/追高型）")

    def _do():
        today = now_beijing().strftime("%Y%m%d")
        src, df = multi_source("龙虎榜", [
            ("东财", lambda: ak.stock_lhb_detail_em(start_date=today, end_date=today)),
            ("新浪", lambda: ak.stock_lhb_detail_daily_sina(
                date=today, symbol="涨幅偏离值达7%的证券")),
            ("东财机构", lambda: ak.stock_lhb_jgmmtj_em(
                start_date=today, end_date=today)),
        ])
        if df is None or len(df) == 0:
            w("  今日龙虎榜暂未发布（18:35后再看）")
            return

        c_name = pick_col(df, ["名称", "股票简称", "简称"])
        c_code = pick_col(df, ["代码", "股票代码"])
        c_pct = pick_col(df, ["涨跌幅", "涨跌幅度", "收盘涨跌幅"])
        c_reason = pick_col(df, ["上榜原因", "解读", "指标"])
        c_net = pick_col(df, ["净买额", "龙虎榜净买额", "机构买入净额", "净额"])

        if not c_name:
            w(f"  [报空] 龙虎榜(源:{src})缺名称列，实际列名={list(df.columns)[:10]}")
            return

        df = df.copy()
        if c_net:
            df[c_net] = pd.to_numeric(df[c_net], errors="coerce")
            if df[c_net].abs().max() and df[c_net].abs().max() > 1e6:
                df[c_net] = (df[c_net] / 1e8).round(2)
            df = df.sort_values(c_net, ascending=False)
        if c_pct:
            df[c_pct] = pd.to_numeric(df[c_pct], errors="coerce")

        w(f"  （源：{src}，共{len(df)}条）")
        ambush, chase = [], []
        for _, r in df.head(20).iterrows():
            nm = str(r[c_name])
            pct = r[c_pct] if c_pct else None
            net = r[c_net] if c_net else None
            code = str(r[c_code])[-6:] if c_code else ""
            tag = ""
            if pct is not None and pd.notna(pct):
                if pct < 0:
                    tag = "✅埋伏型(跌着被买)"
                    if net is None or (pd.notna(net) and net > 0):
                        ambush.append((nm, code, pct, net))
                elif pct >= 9.8:
                    tag = "⚠️追高型(涨停被买)"
                    chase.append((nm, code, pct, net))
                else:
                    tag = "中性"
            pct_txt = f" {pct:+.2f}%" if pct is not None and pd.notna(pct) else ""
            net_txt = f" 净买{net}亿" if net is not None and pd.notna(net) else ""
            reason = str(r[c_reason])[:18] if c_reason else ""
            w(f"    {nm}({code}){pct_txt}{net_txt} {tag} {reason}")

        global AMBUSH_POOL
        AMBUSH_POOL = ambush
        w("")
        w("  ★★★【埋伏池·铁律B】游资在『当天下跌』的票上砸钱 = 明天最可能启动 ★★★")
        if ambush:
            for nm, code, pct, net in ambush[:10]:
                net_txt = f" 净买{net}亿" if net is not None and pd.notna(net) else ""
                w(f"    🎯 {nm}({code}) 今{pct:+.2f}%{net_txt}")
            w(f"    ※ 共{len(ambush)}只。次日重点验证：所属板块是否启动、是否放量。")
        else:
            w("    今日无『跌着被买』标的（全是追涨停接力）→ 次日谨慎")
        if chase:
            w(f"  ⚠️ 追高型{len(chase)}只（涨停被买，次日易炸板）：" +
              "、".join(n for n, _, _, _ in chase[:8]))
    safe_run("龙虎榜", _do)


# ========== 七、游资席位（多源 + 列名自诊断） ==========

def scan_hot_money():
    w("\n【七、游资席位·活跃营业部】（谁在扫货/出货，约18:35后完整）")

    def _do():
        date = now_beijing().strftime("%Y%m%d")
        src, df = multi_source("游资席位", [
            ("东财", lambda: ak.stock_lhb_hyyyb_em(start_date=date, end_date=date)),
            ("新浪", lambda: ak.stock_lhb_yytj_sina(symbol="近一月")),
            ("东财机构", lambda: ak.stock_lhb_jgstatistic_em(symbol="近一月")),
        ])
        if df is None or len(df) == 0:
            w("  今日活跃营业部暂未发布（18:35后再看）")
            return

        c_name = pick_col(df, ["营业部名称", "营业部", "机构名称"])
        c_net = pick_col(df, ["总买卖净额", "净额", "净买", "买入总金额"])
        c_stock = pick_col(df, ["买入股票", "买入个股", "买入股票代码"])

        if not c_name:
            w(f"  [报空] 游资(源:{src})缺营业部列，实际列名={list(df.columns)[:10]}")
            return

        df = df.copy()
        if c_net:
            df[c_net] = pd.to_numeric(df[c_net], errors="coerce")
            if df[c_net].abs().max() and df[c_net].abs().max() > 1e6:
                df[c_net] = (df[c_net] / 1e8).round(2)
            df = df.sort_values(c_net, ascending=False)

        w(f"  ◆ 净买入最猛席位前10（源：{src}）：")
        for _, r in df.head(10).iterrows():
            stock = f" 主买:{str(r[c_stock])[:60]}" if c_stock else ""
            net = f" 净{r[c_net]}亿" if c_net and pd.notna(r[c_net]) else ""
            w(f"    {r[c_name]}{net}{stock}")
        w("  ※ 判读：席位集中买『当天在跌』的方向=埋伏，明天看它启动；")
        w("    集中买『当天涨停』的=追高接力，次日易崩。")
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



# ★催化热力图词典：新闻→板块映射（治"催化分散在不同类目导致漏看"）
SECTOR_KEYWORDS = {
    "电力/核电/特高压": ["特高压", "核电", "华龙一号", "电网", "用电负荷", "迎峰度夏",
                    "输配电", "电力设备", "储能电站", "抽水蓄能", "绿电", "节能降碳",
                    "国家电网", "南方电网", "虚拟电厂", "配电网"],
    "算力/云计算": ["算力", "数据中心", "云计算", "AWS", "Azure", "服务器", "交换机",
                "IDC", "智算", "超算", "capex", "资本开支", "英伟达", "GPU"],
    "半导体设备/材料": ["半导体设备", "光刻", "刻蚀", "薄膜沉积", "CMP", "封测",
                  "先进封装", "晶圆", "12英寸", "国产替代", "中微", "北方华创"],
    "存储芯片": ["存储", "DRAM", "NAND", "HBM", "闪存", "内存", "美光", "海力士",
              "长鑫", "铠侠", "颗粒"],
    "光模块/CPO": ["光模块", "CPO", "硅光", "800G", "1.6T", "光芯片", "光引擎"],
    "软件/EDA/AI应用": ["EDA", "工业软件", "操作系统", "信创", "大模型", "AI应用",
                   "智能体", "Agent", "开源模型", "国产软件"],
    "机器人": ["人形机器人", "具身智能", "机器人", "灵巧手", "谐波减速", "伺服"],
    "锂电/钠电": ["锂电", "钠电", "钠离子", "碳酸锂", "正极", "负极", "电解液",
              "固态电池", "储能电池", "消费税"],
    "创新药/医药": ["创新药", "临床", "获批上市", "BD授权", "License-out", "集采",
                "医保", "减肥药", "ADC", "仿制药"],
    "★AI+制药/CXO": ["AI制药", "AI+医疗", "AI药物", "AI辅助研发", "靶点发现",
                 "分子设计", "AlphaFold", "蛋白质结构", "药物设计", "CXO",
                 "CRO", "CDMO", "药明", "临床前", "虚拟筛选", "干实验室",
                 "生物计算", "医疗大模型", "AI诊断", "智能影像", "脑机接口"],
    "军工/航天": ["军工", "航天", "卫星", "导弹", "国防", "低空经济", "商业航天"],
    "油气/煤炭": ["原油", "布伦特", "WTI", "OPEC", "炼化", "油服", "煤炭", "焦煤",
               "天然气", "霍尔木兹"],
    "有色/稀土": ["稀土", "铜", "铝", "锂矿", "黄金", "白银", "钨", "钼", "磁材"],
    "消费/食饮": ["白酒", "乳制品", "食品饮料", "免税", "餐饮", "消费券", "以旧换新"],
    "汽车/新能源车": ["新能源车", "汽车销量", "交付量", "比亚迪", "特斯拉", "智驾",
                 "充电桩", "800V"],
    "养殖/农业": ["生猪", "猪价", "养殖", "饲料", "粮食", "农产品"],
    "影视/传媒/游戏": ["票房", "暑期档", "电影", "游戏", "版号", "传媒", "短剧"],
}


# 多空判定词（判断一条催化是利多还是利空）
TODAY_HEAT_TOP3 = []
TODAY_ANNOUNCE = {}

BULL_WORDS = ["涨价", "上调", "提价", "缺货", "紧缺", "短缺", "供不应求", "满产",
              "扩产", "增产能", "新增产能", "订单", "中标", "签约", "获批", "并网",
              "投产", "量产", "创新高", "增长", "暴增", "大增", "翻倍", "超预期",
              "回购", "增持", "利好", "受益", "突破", "领先", "第一", "开源",
              "规划", "支持", "补贴", "减税", "宽松", "降准", "降息", "扩内需",
              "净利润同比增", "预增", "反弹", "修复", "回暖", "复苏", "看好", "增配"]

BEAR_WORDS = ["暴跌", "大跌", "下跌", "跌破", "跌超", "下滑", "下降", "减产",
              "停产", "关停", "裁员", "亏损", "预亏", "下修", "下调", "砍单",
              "取消", "推迟", "延期", "叫停", "禁止", "制裁", "封锁", "调查",
              "处罚", "罚款", "爆仓", "强平", "去杠杆", "抛售", "净流出", "减持",
              "溢价风险", "过剩", "降价", "压价", "集采", "降本", "缩水", "warning",
              "加息", "紧缩", "衰退", "风险", "利空", "承压", "疲软", "低迷"]


FOREIGN_WORDS = ["匈牙利", "希腊", "西班牙", "葡萄牙", "意大利", "法国", "德国",
                 "英国", "俄罗斯", "乌克兰", "波兰", "瑞典", "挪威", "芬兰",
                 "印度", "印尼", "越南", "泰国", "菲律宾", "马来西亚", "巴西",
                 "阿根廷", "墨西哥", "土耳其", "埃及", "南非", "澳大利亚",
                 "新西兰", "加拿大", "智利", "秘鲁", "尼日利亚", "肯尼亚",
                 "克罗地亚", "斯洛文尼亚", "亚美尼亚", "刚果", "阿森松岛"]


def _is_foreign(text):
    """外国新闻不计入A股板块评分（如匈牙利核电停机≠A股电力利空）"""
    if any(f in text for f in FOREIGN_WORDS):
        cn = ["中国", "A股", "国内", "我国", "央行", "发改委", "工信部",
              "出口", "进口", "对华", "中方", "国产"]
        if not any(c in text for c in cn):
            return True
    return False


def _news_polarity(text):
    """判断一条新闻的多空方向：+1利多 / -1利空 / 0中性"""
    b = sum(1 for w_ in BULL_WORDS if w_ in text)
    r = sum(1 for w_ in BEAR_WORDS if w_ in text)
    if b > r:
        return 1
    if r > b:
        return -1
    return 0


def scan_catalyst_heat(uniq_news):
    """催化热力图 V2：新闻映射板块 + 多空方向识别，按【净利多】排序"""
    w("\n" + "=" * 60)
    w("🔥🔥【催化热力图·多空版】新闻→板块 + 方向识别 🔥🔥")
    w("=" * 60)
    w("  （V3.4：净利多排序 + 外国新闻已过滤，不污染A股板块评分）")
    w("  （V3.2升级：只数条数会误判——油价暴跌10条也是10条，")
    w("    但那是利空。现在按【净利多 = 利多条数 − 利空条数】排序）")

    hits = {}
    for sect, kws in SECTOR_KEYWORDS.items():
        bull, bear, neu, seen = [], [], [], set()
        for tm, t in uniq_news:
            if _is_foreign(t):
                continue
            for k in kws:
                if k in t and t[:26] not in seen:
                    seen.add(t[:26])
                    p = _news_polarity(t)
                    (bull if p > 0 else bear if p < 0 else neu).append((tm, t, k))
                    break
        if bull or bear or neu:
            hits[sect] = (bull, bear, neu)
    if not hits:
        w("  本期无命中")
        return

    ranked = sorted(hits.items(), key=lambda x: len(x[1][0]) - len(x[1][1]), reverse=True)

    global TODAY_HEAT_TOP3
    TODAY_HEAT_TOP3 = [k for k, (b, r, n) in ranked[:3] if len(b) - len(r) > 0]
    w("\n  ★ 净利多排行（利多↑ 利空↓ 中性=）：")
    for i, (sect, (bu, be, ne)) in enumerate(ranked, 1):
        net = len(bu) - len(be)
        if net >= 5:
            flag = " 🔥🔥🔥催化爆发·重点关注"
        elif net >= 3:
            flag = " 🔥🔥催化密集"
        elif net >= 1:
            flag = " 🔥有催化"
        elif net <= -3:
            flag = " ❄️❄️利空密集·回避"
        elif net <= -1:
            flag = " ❄️偏空"
        else:
            flag = " ⚖️多空平衡"
        w(f"    {i}. {sect}：净{net:+d}（↑{len(bu)} ↓{len(be)} ={len(ne)}）{flag}")

    w("\n  ★ 净利多前3名的具体利多催化：")
    shown = 0
    for sect, (bu, be, ne) in ranked:
        if len(bu) - len(be) < 1 or shown >= 3:
            continue
        shown += 1
        w(f"\n  ◆ 【{sect}】利多{len(bu)}条 / 利空{len(be)}条")
        for tm, t, k in bu[:6]:
            w(f"      ↑[{tm}] ({k}) {t[:58]}")
        if be:
            w("      ── 该板块的利空（对冲项）──")
            for tm, t, k in be[:3]:
                w(f"      ↓[{tm}] ({k}) {t[:58]}")
    if shown == 0:
        w("    ⚠️ 本期无任何板块净利多为正 → 全市场偏空，谨慎")

    w("\n  ★ 利空最密集的板块（明确回避）：")
    for sect, (bu, be, ne) in ranked[-3:]:
        net = len(bu) - len(be)
        if net < 0:
            w(f"    ❄️ {sect}：净{net:+d}")
            for tm, t, k in be[:3]:
                w(f"        ↓[{tm}] ({k}) {t[:58]}")

    w("\n  ⚠️ 判读：净利多≠立刻买，仍需过决策卡①②④⑤")
    w("     但【净利多前3】不许在候选里漏掉；【净利空】不许推荐")
    w("=" * 60)


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

    scan_catalyst_heat(uniq)
    scan_deduction(uniq, TODAY_HEAT_TOP3)
    scan_all_sector_cross(uniq)
    scan_deep_meaning(uniq, TODAY_AMBUSH)
    scan_stock_picker()
    scan_announcements()
    scan_unexplained()



def _bt_load(path):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _bt_save(path, data):
    try:
        ks = sorted(data)[-60:]
        data = {k: data[k] for k in ks}
        os.makedirs("reports", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def backtest_ambush(today_pool):
    """埋伏池回测：验证铁律B(机构/游资在跌时买入=明天机会)到底有没有用"""
    w("\n" + "=" * 60)
    w("📊【埋伏池回测】铁律B到底成不成立 —— 用胜率说话")
    w("=" * 60)
    bj = now_beijing()
    today = bj.strftime("%Y-%m-%d")
    can_save = (bj.weekday() < 5) and (bj.hour >= 15)
    hist = _bt_load(AMBUSH_HIST_FILE)
    spot = get_spot()
    if spot is None:
        w("  快照缺失，无法回测")
        return
    c_code = pick_col(spot, ["代码", "code"])
    c_price = pick_col(spot, ["最新价", "trade"])

    days = sorted([d for d in hist if d < today])
    for lag, label in [(1, "次日"), (5, "5日")]:
        if len(days) < lag:
            continue
        base = days[-lag]
        recs = hist[base]
        win, tot, n = 0, 0.0, 0
        detail = []
        for r in recs:
            try:
                row = spot[spot[c_code].astype(str).str.contains(r["code"], na=False)]
                if len(row) == 0:
                    continue
                now_p = pd.to_numeric(row.iloc[0][c_price], errors="coerce")
                if pd.isna(now_p) or not r.get("price"):
                    continue
                pnl = (now_p - r["price"]) / r["price"] * 100
                tot += pnl
                n += 1
                if pnl > 0:
                    win += 1
                detail.append((r["name"], pnl))
            except Exception:
                continue
        if n:
            wr = win / n * 100
            avg = tot / n
            if n < 5:
                verdict = f"⚠️样本仅{n}只，统计无意义，不下结论（需≥5只）"
            elif wr >= 55 and avg > 0:
                verdict = "✅铁律B成立，可信"
            elif wr >= 45:
                verdict = "⚠️边缘，谨慎用"
            else:
                verdict = "❌铁律B在当前行情不成立，停止依赖"
            w(f"\n  ◆ {base} 那批（{n}只）{label}后：")
            w(f"    胜率 {win}/{n} = {wr:.1f}% | 平均收益 {avg:+.2f}% → {verdict}")
            for nm, p in sorted(detail, key=lambda x: -x[1])[:5]:
                w(f"      {nm} {p:+.2f}%")
    if not days:
        w("  首次运行，今日起积累（需1天出次日胜率，5天出5日胜率）")

    if can_save and today_pool:
        hist[today] = today_pool
        _bt_save(AMBUSH_HIST_FILE, hist)
        w(f"  ✅ 已存档今日埋伏池{len(today_pool)}只，历史{len(hist)}天")


HEAT_TO_SECTOR = {
    "算力/云计算": ["计算机设备", "通信设备", "IT服务", "软件开发"],
    "存储芯片": ["半导体", "元件", "电子化学品"],
    "半导体设备/材料": ["半导体", "电子化学品", "非金属材料"],
    "光模块/CPO": ["通信设备", "光学光电子"],
    "软件/EDA/AI应用": ["软件开发", "IT服务"],
    "电力/核电/特高压": ["电力", "电网设备", "输变电设备", "其他电源设备"],
    "锂电/钠电": ["电池", "能源金属", "小金属"],
    "机器人": ["自动化设备", "通用设备", "电机"],
    "创新药/医药": ["医疗服务", "化学制药", "生物制品", "中药"],
    "军工/航天": ["航天装备", "航空装备", "军工电子", "地面兵装"],
    "油气/煤炭": ["油气开采", "炼化及贸易", "煤炭开采", "焦炭"],
    "有色/稀土": ["小金属", "工业金属", "贵金属", "能源金属"],
    "消费/食饮": ["白酒", "食品加工", "饮料乳品", "休闲食品"],
    "汽车/新能源车": ["汽车整车", "汽车零部件", "汽车服务"],
    "养殖/农业": ["养殖业", "饲料", "农产品加工"],
    "影视/传媒/游戏": ["影视院线", "游戏", "广告营销", "出版"],
}


def backtest_heat(top3):
    """热力图回测：净利多前3的板块，之后真的跑赢吗"""
    w("\n" + "=" * 60)
    w("📊【热力图回测】净利多前3 到底跑不跑赢 —— 用超额说话")
    w("=" * 60)
    bj = now_beijing()
    today = bj.strftime("%Y-%m-%d")
    can_save = (bj.weekday() < 5) and (bj.hour >= 15)
    hist = _bt_load(HEAT_HIST_FILE)

    _, bdf = multi_source("板块回测", [
        ("同花顺", lambda: ak.stock_fund_flow_industry(symbol="即时")),
        ("东财", lambda: ak.stock_board_industry_name_em()),
    ])
    cur = {}
    if bdf is not None:
        bn = pick_col(bdf, ["名称", "行业", "板块"])
        bp = pick_col(bdf, ["涨跌幅", "行业指数涨跌", "涨跌"])
        if bn and bp:
            for _, r in bdf.iterrows():
                v = pd.to_numeric(r[bp], errors="coerce")
                if pd.notna(v):
                    cur[str(r[bn])] = float(v)

    days = sorted([d for d in hist if d < today])
    if days and cur:
        base = days[-1]
        rec = hist[base]
        w(f"\n  ◆ {base} 的净利多前3 → 今日表现：")
        hit = 0
        for sect in rec.get("top3", []):
            targets = HEAT_TO_SECTOR.get(sect, sect.replace("/", " ").split())
            matched = []
            for k, v in cur.items():
                if any(t in k or k in t for t in targets):
                    matched.append((k, v))
            if matched:
                # 取该组板块的平均涨跌，比只取第一个准
                avg = sum(x[1] for x in matched) / len(matched)
                k = "、".join(x[0] for x in matched[:3])
                v = avg
                flag = "✅跑赢" if v > 0 else "❌未兑现"
                w(f"    {sect} → 对应[{k}] {v:+.2f}% {flag}")
                if v > 0:
                    hit += 1
            else:
                w(f"    {sect} → 无对应板块数据")
        w(f"    ★命中 {hit}/3")
        w("    ⚠️ 连续5次命中<1/3 → 热力图排序无效，需调整词典权重")
    else:
        w("  首次运行或板块数据缺失，今日起积累")

    if can_save and top3:
        hist[today] = {"top3": top3}
        _bt_save(HEAT_HIST_FILE, hist)
        w(f"  ✅ 已存档今日净利多前3：{'、'.join(top3)}")


def scan_rule_scorecard():
    """规则记分卡：哪条规则真的有用，一目了然"""
    w("\n" + "=" * 60)
    w("📊【规则记分卡】我编的规则，哪条经得起检验")
    w("=" * 60)
    w("  规则                     验证方式              当前状态")
    w("  ─────────────────────────────────────────────")
    for name, how, f in [
        ("铁律B·埋伏池", "次日/5日胜率", AMBUSH_HIST_FILE),
        ("热力图·净利多前3", "次日板块涨跌", HEAT_HIST_FILE),
        ("冷低早·六关", "5日胜率", COLD_HIST_FILE),
    ]:
        d = _bt_load(f)
        n = len(d)
        total_samples = sum(len(v) if isinstance(v, list) else
                            len(v.get("top3", [])) if isinstance(v, dict) else 0
                            for v in d.values())
        st = (f"已积累{n}天/{total_samples}个样本" +
              ("（够了，看上面胜率）" if n >= 5 and total_samples >= 15
               else "（需≥5天且≥15样本）"))
        w(f"  {name:<22} {how:<18} {st}")
    w("\n  ⚠️ 铁律：任何规则连续验证胜率<45%，立即停用，不许再拿它推荐")
    w("  ⚠️ AI不许说『这条规则有用』，只许说『它的历史胜率是X%』")
    w("=" * 60)


# ========== ★仓位建议 + 驱动链集中度 + 组合健康度 ==========

def scan_position_advice(risk_score=None):
    w("\n" + "=" * 60)
    w("💰【仓位建议 + 驱动链集中度 + 组合健康度】")
    w("=" * 60)

    if risk_score is not None:
        if risk_score <= 1:
            adv, txt = "70-80%", "环境健康，可进攻"
        elif risk_score <= 3:
            adv, txt = "50-60%", "中性，正常持仓"
        elif risk_score <= 6:
            adv, txt = "30-40%", "偏弱，只减不加"
        elif risk_score <= 9:
            adv, txt = "20%以下", "高危，大幅降仓"
        else:
            adv, txt = "空仓", "极端风险，清仓观望"
        w(f"  ★风险分 {risk_score}/12 → 建议仓位 【{adv}】（{txt}）")
    else:
        w("  ★风险分未取到，仓位建议跳过")

    held = [(n, ch, mv) for _, n, t, _, _, _, ch, mv in WATCH_STOCKS
            if t == "持仓" and mv > 0]
    if not held:
        w("  无持仓数据")
        return
    total_mv = sum(m for _, _, m in held)
    pos_pct = total_mv / TOTAL_ASSET * 100 if TOTAL_ASSET else 0
    w(f"  ★当前仓位：{total_mv:.1f}万 / {TOTAL_ASSET:.1f}万 = {pos_pct:.0f}%")
    if risk_score is not None:
        lo = {0: 70, 1: 70, 2: 50, 3: 50, 4: 30, 5: 30, 6: 30,
              7: 0, 8: 0, 9: 0}.get(risk_score, 0)
        hi = {0: 80, 1: 80, 2: 60, 3: 60, 4: 40, 5: 40, 6: 40,
              7: 20, 8: 20, 9: 20}.get(risk_score, 0)
        if pos_pct > hi:
            w(f"  🔴 超出建议上限{hi}% → 应减 {(pos_pct-hi)/100*TOTAL_ASSET:.1f}万")
        elif pos_pct < lo:
            w(f"  🟡 低于建议下限{lo}% → 可加 {(lo-pos_pct)/100*TOTAL_ASSET:.1f}万")
        else:
            w("  ✅ 仓位在建议区间内")

    w("\n  ★驱动链集中度（同一条链>40%=危险，7/28全AI链一起挨打的教训）：")
    chains = {}
    for n, ch, mv in held:
        chains.setdefault(ch, []).append((n, mv))
    warn = False
    for ch, items in sorted(chains.items(), key=lambda x: -sum(i[1] for i in x[1])):
        amt = sum(i[1] for i in items)
        pct = amt / TOTAL_ASSET * 100 if TOTAL_ASSET else 0
        names = " + ".join(f"{n}{m}万" for n, m in items)
        flag = " 🔴超40%危险！" if pct > 40 else (" ⚠️接近40%" if pct > 30 else " ✅")
        if pct > 40:
            warn = True
        w(f"    {ch}：{names} = {amt:.1f}万 / {pct:.0f}%{flag}")
    if warn:
        w("    🔴 一条链超40% → 该链一崩全仓挨打，必须分散")

    score = 100
    notes = []
    if risk_score is not None:
        if risk_score >= 7 and pos_pct > 30:
            score -= 30
            notes.append("高危环境仍重仓")
        elif risk_score >= 4 and pos_pct > 60:
            score -= 15
            notes.append("偏弱环境仓位偏高")
    mx = max((sum(i[1] for i in v) / TOTAL_ASSET * 100) for v in chains.values())
    if mx > 40:
        score -= 25
        notes.append(f"驱动链集中度{mx:.0f}%")
    elif mx > 30:
        score -= 10
        notes.append(f"驱动链{mx:.0f}%偏高")
    if len(chains) < 2:
        score -= 20
        notes.append("只有1条驱动链")
    w(f"\n  ★★组合健康度：{max(score,0)}/100" +
      (f"　问题：{'｜'.join(notes)}" if notes else "　✅无问题"))
    w("=" * 60)


# ========== ★★产业链推演引擎（演绎，不是归纳） ==========
# 核心：热力图管"已发生"（归纳），推演引擎管"必然要发生"（演绎）
# 用法：上游事实一旦出现 → 自动推出2-3层下游 → 找市场还没发现的那层

DEDUCTION_CHAINS = [
    {
        "name": "AI算力 → 散热",
        "trigger": ["AI芯片", "GPU", "英伟达", "算力", "数据中心", "服务器",
                    "capex", "资本开支", "功耗", "TDP"],
        "core": ["液冷", "散热", "冷板", "CDU", "浸没", "风冷", "热管", "均热板"],
        "layers": ["①AI芯片功耗暴涨", "②风冷极限→液冷渗透",
                   "③冷板/CDU/快接头/浸没液", "④氟化液/特种泵阀"],
        "stocks": "英维克/申菱环境/高澜股份/同飞股份/飞荣达/中石科技",
        "verify": ["订单", "中标", "量产", "扩产", "投产", "签约", "供货", "涨价"],
    },
    {
        "name": "AI算力 → 供电",
        "trigger": ["AI芯片", "机架", "数据中心", "算力中心", "超节点"],
        "core": ["800VDC", "HVDC", "固态变压器", "BBU", "母线槽", "UPS",
                 "供配电", "电源模块", "SiC"],
        "layers": ["①单机架功率10kW→100kW", "②传统UPS不够→HVDC/800VDC",
                   "③固态变压器/BBU备电/母线槽", "④SiC功率器件"],
        "stocks": "麦格米特/科华数据/科士达/中恒电气/欧陆通/新雷能",
        "verify": ["订单", "中标", "量产", "扩产", "供货", "定点", "签约"],
    },
    {
        "name": "先进封装 → 玻璃基板",
        "trigger": ["先进封装", "CoWoS", "2.5D", "3D堆叠", "封装产能", "载板"],
        "core": ["玻璃基板", "玻璃基", "TGV", "玻璃通孔", "基板", "载板", "ABF"],
        "layers": ["①摩尔定律见顶→算力靠堆封装", "②有机基板承载不了大尺寸",
                   "③玻璃基板成下一代载板", "④TGV激光钻孔/电镀/高纯石英玻璃"],
        "stocks": "凯盛科技/沃格光电/德龙激光/帝尔激光/长电科技/通富微电",
        "verify": ["中试线", "量产", "投产", "订单", "扩产", "投资", "样品", "送样"],
    },
    {
        "name": "存储涨价 → 传导链",
        "trigger": ["AI", "数据中心", "算力", "服务器"],
        "core": ["存储", "DRAM", "NAND", "HBM", "内存", "闪存", "颗粒",
                 "美光", "海力士", "铠侠", "长鑫", "模组"],
        "layers": ["①AI重塑存储周期→供不应求", "②原厂涨价→模组厂涨价",
                   "③终端涨价(手机/PC)", "④设备/材料需求→扩产"],
        "stocks": "兆易创新/江波龙/德明利/佰维存储/香农芯创/深科技",
        "verify": ["涨价", "提价", "缺货", "紧缺", "长约", "扩产", "满产", "量产"],
    },
    {
        "name": "核电核准 → 设备链",
        "trigger": ["核电", "核准", "华龙一号", "核电机组", "并网"],
        "core": ["核电", "核岛", "核级", "锆", "蒸汽发生器", "压力容器",
                 "核燃料", "可控核聚变"],
        "layers": ["①机组核准→3-5年建设期", "②核岛设备招标",
                   "③核级泵阀/管道/锆材", "④后续燃料+运维"],
        "stocks": "中国核电/东方电气/上海电气/江苏神通/纽威股份/应流股份",
        "verify": ["中标", "订单", "招标", "开工", "投产", "签约", "获批"],
    },
    {
        "name": "特高压 → 设备链",
        "trigger": ["特高压", "电网投资", "十五五电网", "输配电"],
        "core": ["特高压", "换流阀", "GIS", "变压器", "电网设备", "输变电",
                 "柔性直流", "组合电器", "绝缘子"],
        "layers": ["①十五五规模翻倍→投资前置", "②换流阀/变压器/GIS招标",
                   "③电缆/绝缘子/组合电器", "④配网+储能配套"],
        "stocks": "许继电气/平高电气/国电南瑞/思源电气/特变电工/中国西电",
        "verify": ["中标", "招标", "订单", "开工", "投运", "签约", "释放"],
    },
    {
        "name": "锂电消费税 → 钠电替代",
        "trigger": ["锂电", "消费税", "碳酸锂", "储能"],
        "core": ["钠电", "钠离子", "硬碳", "层状氧化物", "普鲁士", "聚阴离子"],
        "layers": ["①9/1锂电征4%消费税，钠电免税", "②成本差拉大→钠电替代加速",
                   "③钠电正极/硬碳负极", "④集流体铝箔替代铜箔"],
        "stocks": "容百科技/振华新材/元力股份/鼎胜新材/华阳股份/传艺科技",
        "verify": ["订单", "量产", "投产", "签单", "中标", "投资", "扩产"],
    },
    {
        "name": "机器人量产 → 零部件",
        "trigger": ["人形机器人", "具身智能", "Optimus", "宇树"],
        "core": ["谐波", "减速器", "丝杠", "无框电机", "灵巧手", "触觉传感",
                 "行星滚柱", "关节模组", "机器人零部件"],
        "layers": ["①量产爬坡→零部件放量", "②谐波/行星滚柱丝杠/无框电机",
                   "③灵巧手(微型丝杠/触觉传感)", "④减速器材料+精密加工"],
        "stocks": "绿的谐波/三花智控/鸣志电器/兆威机电/双环传动/贝斯特",
        "verify": ["定点", "订单", "量产", "送样", "产能", "扩产", "供货"],
    },
    {
        "name": "MLCC涨价 → 被动元件",
        "trigger": ["AI服务器", "被动元件", "电子元件"],
        "core": ["MLCC", "电容", "国巨", "村田", "三星电机", "陶瓷粉", "钽电容"],
        "layers": ["①AI服务器高容MLCC紧缺", "②原厂涨价→渠道跟涨",
                   "③国产替代加速", "④上游陶瓷粉/镍粉"],
        "stocks": "风华高科/三环集团/宏达电子/火炬电子/裕兴股份",
        "verify": ["涨价", "提价", "满产", "产能利用率", "订单", "缺货", "紧缺"],
    },
    {
        "name": "AI+制药 → CXO/算力",
        "trigger": ["AI制药", "AI药物", "靶点", "分子设计", "医疗大模型",
                    "新药研发", "临床前", "生物医药", "AI+医疗"],
        "core": ["CXO", "CRO", "CDMO", "AI制药", "AI药物", "靶点发现",
                 "分子设计", "虚拟筛选", "药物设计", "AlphaFold",
                 "生物计算", "医疗大模型", "临床前研究"],
        "layers": ["①新药研发10年/10亿美元/成功率<10%",
                   "②AI把靶点发现从数年→数月，分子设计成本降一个量级",
                   "③药企敢做更多管线→★CXO订单增加+AI平台收服务费",
                   "④算力需求→医药+算力双属性标的"],
        "stocks": "药明康德/成都先导/泓博医药/皓元医药/美迪西/凯莱英/九洲药业",
        "verify": ["订单", "中标", "签约", "合作", "获批", "临床", "交付",
                   "增长", "落地", "上线", "商业化"],
    },
    {
        "name": "猪周期 → 养殖链",
        "trigger": ["生猪", "猪价", "养殖", "能繁母猪", "出栏", "存栏", "饲料"],
        "core": ["能繁母猪", "生猪存栏", "出栏均价", "猪粮比", "去产能",
                 "养殖成本", "仔猪", "母猪产能"],
        "layers": ["①能繁母猪去化→10个月后供给收缩", "②猪价上行→养殖利润修复",
                   "③龙头出栏放量+成本领先", "④饲料/疫苗/设备跟随"],
        "stocks": "牧原股份/温氏股份/新希望/巨星农牧/神农集团",
        "verify": ["去化", "存栏下降", "价格上涨", "利润修复", "出栏增长", "收储"],
    },
    {
        "name": "光模块 → 上游光芯片",
        "trigger": ["光模块", "CPO", "800G", "1.6T", "数据中心互联"],
        "core": ["光芯片", "EML", "DFB", "硅光", "光引擎", "激光器", "PD",
                 "磷化铟", "InP", "衬底", "砷化镓", "GaAs", "外延片", "高纯铟"],
        "layers": ["①AI数据中心互联需求", "②800G/1.6T光模块放量",
                   "③上游光芯片(EML/DFB)+硅光（市场已炒到这层）",
                   "④★InP磷化铟衬底（全球产能高度集中，扩产周期3年+）",
                   "⑤★衬底原材料：高纯铟/磷源/砷化镓"],
        "stocks": "源杰科技/仕佳光子/长光华芯(光芯片层) | "
                  "★云南锗业/博杰股份/有研新材/中镓半导体链(InP衬底层，最少被发现)",
        "verify": ["产能", "良率", "扩产", "订单", "量产", "供货", "涨价"],
    },
]


ANNOUNCE_KEYS = ["收购", "重组", "中标", "订单", "签署", "合作", "增资",
                 "预增", "扭亏", "业绩", "投资", "定增", "回购", "增持",
                 "资质", "许可", "获批", "量产", "投产", "涨价", "扩产",
                 "英伟达", "华为", "特斯拉", "苹果", "台积电", "算力"]


def scan_stock_picker():
    """个股级选股器：板块顺风 + 个股还没涨 + 主力真进（V5.3核心）"""
    w("\n" + "=" * 60)
    w("🎯🎯【个股级选股器】板块顺风 + 个股还没涨 + 主力真进 🎯🎯")
    w("=" * 60)
    w("  逻辑：ETF是一篮子平均数，永远赚不到10%")
    w("       要10%只能靠个股：找『板块在涨、它还没涨、但钱在进』的")

    def _do():
        spot = get_spot()
        if spot is None:
            w("  [报空] 快照缺失")
            return
        c_code = pick_col(spot, ["代码", "code"])
        c_name = pick_col(spot, ["名称", "name"])
        c_pct = pick_col(spot, ["涨跌幅", "changepercent"])
        c_amt = pick_col(spot, ["成交额", "amount"])
        if not all([c_code, c_name, c_pct, c_amt]):
            w("  [报空] 快照缺字段")
            return

        fmap, fsrc = {}, None
        for nm_, fn in [
            ("同花顺即时", lambda: ak.stock_fund_flow_individual(symbol="即时")),
            ("同花顺3日", lambda: ak.stock_fund_flow_individual(symbol="3日排行")),
            ("东财今日", lambda: ak.stock_individual_fund_flow_rank(indicator="今日")),
            ("东财5日", lambda: ak.stock_individual_fund_flow_rank(indicator="5日")),
        ]:
            try:
                f = with_retry(fn, tries=1, wait=2, timeout=45)
                if f is None or len(f) == 0:
                    continue
                fc = pick_col(f, ["代码", "股票代码"])
                fv = pick_col(f, ["今日主力净流入-净额", "5日主力净流入-净额",
                                  "主力净流入-净额", "主力净流入", "净额",
                                  "流入资金", "净流入"])
                if not fc or not fv:
                    continue
                for _, r in f.iterrows():
                    try:
                        k = str(r[fc])[-6:].zfill(6)
                        v = pd.to_numeric(r[fv], errors="coerce")
                        if pd.notna(v):
                            fmap[k] = float(v)
                    except Exception:
                        continue
                if fmap:
                    fsrc = nm_
                    break
            except Exception:
                continue
        if not fmap:
            w("  ⚠️ 个股资金流双源失败 → 降级为纯技术筛选")

        sect_chg = {}
        try:
            d = with_retry(lambda: ak.stock_fund_flow_industry(symbol="即时"),
                           tries=1, timeout=40)
            n_ = pick_col(d, ["行业", "名称"])
            p_ = pick_col(d, ["涨跌幅", "行业指数涨跌"])
            for _, r in d.iterrows():
                v = pd.to_numeric(r[p_], errors="coerce")
                if pd.notna(v):
                    sect_chg[str(r[n_])] = float(v)
        except Exception:
            pass
        ind_map, _a = _load_ind_cache()

        df = spot.copy()
        df[c_pct] = pd.to_numeric(df[c_pct], errors="coerce")
        df[c_amt] = pd.to_numeric(df[c_amt], errors="coerce")
        df = df.dropna(subset=[c_pct, c_amt])
        df = df[~df[c_name].astype(str).str.contains("退|N |ST", na=False)]
        df["_c6"] = df[c_code].astype(str).str.extract(r"(\d{6})")[0]
        df = df.dropna(subset=["_c6"])
        df = df[(df[c_pct] >= -2.0) & (df[c_pct] <= 3.0)]
        df = df[(df[c_amt] >= 5e7) & (df[c_amt] <= 3e9)]

        cand = []
        for _, r in df.iterrows():
            code6 = r["_c6"]
            flow = fmap.get(code6)
            if fmap and (flow is None or flow <= 0):
                continue
            ind = ind_map.get(code6, "")
            schg = sect_chg.get(ind) if ind else None
            # 板块必须顺风；行业未知时不一票否决（对照表只有513只）
            if schg is not None and schg < 0.5:
                continue
            cand.append((code6, str(r[c_name]), float(r[c_pct]),
                         float(r[c_amt]), flow, ind, schg))
        if fmap:
            cand.sort(key=lambda x: -(x[4] or 0))          # 有资金→按主力净额
        else:
            cand.sort(key=lambda x: -x[3])                  # ★无资金→按成交额，
            w("  ⚠️ 资金流全源失败 → 改用【成交额+涨跌量比】筛选")
        cand = cand[:50]

        picks = []
        for code6, nm, pct, amt, flow, ind, schg in cand:
            d60 = vr = None
            try:
                k, kc = _hist_close(code6, ("sh" if code6.startswith("6") else "sz") + code6)
                if k is not None and kc is not None:
                    now_p = pd.to_numeric(k.iloc[-1][kc], errors="coerce")
                    p60 = pd.to_numeric(k.iloc[-45][kc], errors="coerce")
                    if p60:
                        d60 = (now_p - p60) / p60 * 100
                    kv = pick_col(k, ["volume", "成交量"])
                    if kv:
                        v5 = pd.to_numeric(k[kv].tail(5), errors="coerce").mean()
                        v60 = pd.to_numeric(k[kv].tail(45), errors="coerce").mean()
                        if v60:
                            vr = v5 / v60
            except Exception:
                pass
            # ★涨跌量比（暗流吸筹）——冷低早已验证8天/71样本
            udr = None
            try:
                if k is not None and kc is not None:
                    kv2 = pick_col(k, ["volume", "成交量"])
                    if kv2:
                        kk = k.tail(30).copy()
                        kk["_c"] = pd.to_numeric(kk[kc], errors="coerce")
                        kk["_v"] = pd.to_numeric(kk[kv2], errors="coerce")
                        kk["_chg"] = kk["_c"].pct_change()
                        up = kk[kk["_chg"] > 0]["_v"].mean()
                        dn = kk[kk["_chg"] < 0]["_v"].mean()
                        if dn and dn > 0:
                            udr = up / dn
            except Exception:
                pass
            sc = 0.0
            if schg is not None:
                sc += min(schg, 6)
            sc += 3 if pct < 1 else (1 if pct < 2 else 0)
            if d60 is not None and d60 < -10:
                sc += 2
            if vr is not None and vr < 0.9:
                sc += 2
            if flow:
                sc += min(abs(flow) / 1e8 if abs(flow) > 1e6 else abs(flow) / 1e4, 4)
            elif udr is not None and udr > 1.1:
                sc += min((udr - 1.0) * 10, 4)      # 无资金时用暗流替代
            if udr is not None and udr < 1.0:
                sc -= 2                              # 跌日放量=派发，扣分
            picks.append((sc, nm, code6, pct, flow, ind, schg, d60, vr, udr))
            time.sleep(0.15)

        if not picks:
            w("  今日无符合条件的个股")
            return
        picks.sort(key=lambda x: -x[0])
        w(f"  （源：{fsrc or '无资金'}｜行业表{len(ind_map)}只｜候选{len(picks)}只）")
        w("\n  ★★【板块在涨 · 它还没涨 · 主力在进】前12：")
        for i, (sc, nm, cd, pct, fl, ind, schg, d60, vr, udr) in enumerate(picks[:12], 1):
            ft = ""
            if fl:
                ft = f" 主力+{fl/1e8:.2f}亿" if abs(fl) > 1e6 else f" 主力+{fl/1e4:.0f}万"
            elif udr is not None:
                ft = f" 量比{udr:.2f}"
            st = f" [{ind}{schg:+.1f}%]" if ind and schg is not None else (f" [{ind}]" if ind else "")
            dt = f" 60日{d60:+.0f}%" if d60 is not None else ""
            vt = f" 缩量{vr:.2f}" if vr is not None else ""
            w(f"    {i:2d}. {nm}({cd}) {pct:+.2f}%{ft}{st}{dt}{vt} 得分{sc:.1f}")
        w("\n  ⚠️ 铁律P（V5.3）：★有个股就不许只给ETF★")
        w("    ETF是一篮子平均数，注定跑不出10%")
        w("    仍需过①-B真实驱动 + ⑨逻辑破定义才能推荐")
    safe_run("个股级选股器", _do)


def scan_announcements():
    """公司公告雷达：补快讯盲区（通宇通讯收购案的教训）"""
    w("\n" + "=" * 60)
    w("📢【公司公告雷达】补快讯盲区 —— 涨停背后的真实原因")
    w("=" * 60)
    d = now_beijing().strftime("%Y%m%d")

    def _do():
        df = None
        for fn in [lambda: ak.stock_notice_report_em(symbol="全部", date=d),
                   lambda: ak.stock_notice_report_em(symbol="重大事项", date=d)]:
            try:
                r = with_retry(fn, tries=1, wait=2, timeout=40)
                if r is not None and len(r) > 0:
                    df = r
                    break
            except Exception:
                continue
        if df is None:
            w("  [报空] 公告源不可用")
            return
        c_name = pick_col(df, ["名称", "股票简称", "简称"])
        c_code = pick_col(df, ["代码", "股票代码"])
        c_title = pick_col(df, ["公告标题", "标题"])
        if not c_title:
            w(f"  [报空] 缺标题列 {list(df.columns)[:6]}")
            return
        hits = []
        for _, r in df.iterrows():
            try:
                t = str(r[c_title])
                if any(k in t for k in ANNOUNCE_KEYS):
                    nm = str(r[c_name]) if c_name else ""
                    cd = str(r[c_code])[-6:] if c_code else ""
                    hits.append((nm, cd, t))
            except Exception:
                continue
        w(f"  （共{len(df)}条公告，关键词命中{len(hits)}条）")
        for nm, cd, t in hits[:25]:
            w(f"    ▸ {nm}({cd}) {t[:52]}")
        globals()["TODAY_ANNOUNCE"] = {h[1]: h[2] for h in hits}
    safe_run("公司公告雷达", _do)


def scan_unexplained():
    """异动未解释清单：涨停但说不出原因=盲区，AI必须主动搜"""
    w("\n" + "=" * 60)
    w("❓【异动未解释清单】说不出原因 = 盲区，AI必须主动搜索")
    w("=" * 60)
    w("  ★铁律M：涨停股如果我说不出它为什么涨，就是我的信息盲区")

    def _do():
        ann = globals().get("TODAY_ANNOUNCE", {})
        try:
            zt = with_retry(lambda: ak.stock_zt_pool_em(
                date=now_beijing().strftime("%Y%m%d")), tries=1, timeout=45)
        except Exception:
            zt = None
        if zt is None or len(zt) == 0:
            w("  涨停池无数据")
            return
        z_name = pick_col(zt, ["名称"])
        z_code = pick_col(zt, ["代码"])
        z_ind = pick_col(zt, ["所属行业", "行业"])
        if not z_name or not z_code:
            w("  [报空] 涨停池缺字段")
            return
        explained, unknown = [], []
        for _, r in zt.iterrows():
            try:
                cd = str(r[z_code])[-6:].zfill(6)
                nm = str(r[z_name])
                ind = str(r[z_ind]) if z_ind else ""
                if cd in ann:
                    explained.append((nm, cd, ind, ann[cd][:36]))
                else:
                    unknown.append((nm, cd, ind))
            except Exception:
                continue
        w(f"\n  ✅有公告解释（{len(explained)}只）：")
        for nm, cd, ind, t in explained[:12]:
            w(f"    {nm}({cd})[{ind}] ← {t}")
        w(f"\n  ❓无公告解释（{len(unknown)}只）→ ★AI必须逐个追问★")
        for nm, cd, ind in unknown[:20]:
            w(f"    {nm}({cd})[{ind}] ← 原因未知，需主动搜索")
        w("\n  ⚠️ ①同行业≥3只无解释涨停→板块级消息，去搜行业新闻")
        w("     ②AI必须写『我查了，原因是XXX』或『我查不到』，不许跳过")
    safe_run("异动未解释", _do)


def scan_all_sector_cross(uniq_news):
    """全板块×新闻自动交叉：477个板块逐个扫，绝对不漏（V5.0核心）"""
    w("\n" + "=" * 60)
    w("🌐🌐【全板块 × 新闻 自动交叉】477个板块逐个扫 · 绝对不漏 🌐🌐")
    w("=" * 60)
    w("  逻辑：手工词典必漏；直接用市场公认的行业+概念分类去撞新闻")
    w("       板块有新闻催化 + 位置好(刚启动) = 真机会")

    def _do():
        rows = []
        for tag, fn, nk, pk in [
            ("行业", lambda: ak.stock_fund_flow_industry(symbol="即时"),
             ["行业", "名称", "板块"], ["涨跌幅", "行业指数涨跌", "涨跌"]),
            ("概念", lambda: ak.stock_fund_flow_concept(symbol="即时"),
             ["行业", "概念名称", "名称", "板块"], ["涨跌幅", "行业指数涨跌", "涨跌"]),
        ]:
            try:
                df = with_retry(fn, tries=1, wait=2, timeout=40)
                if df is None or len(df) == 0:
                    w(f"  [跳过] {tag}源空")
                    continue
                nc = pick_col(df, nk)
                pc = pick_col(df, pk)
                if not nc:
                    w(f"  [跳过] {tag}缺名称列 {list(df.columns)[:6]}")
                    continue
                for _, r in df.iterrows():
                    try:
                        v = pd.to_numeric(r[pc], errors="coerce") if pc else None
                        rows.append((tag, str(r[nc]), v))
                    except Exception:
                        continue
            except Exception as e:
                w(f"  [跳过] {tag}：{type(e).__name__}")

        if not rows:
            w("  [报空] 板块数据不可用")
            return
        w(f"  （共扫描 {len(rows)} 个板块）")

        SKIP = {"其他", "综合", "综合Ⅱ", "证金持股", "融资融券", "沪股通",
                "深股通", "标准普尔", "MSCI中国", "富时罗素", "预盈预增",
                "转债标的", "破净股", "低价股", "高送转", "壳资源"}
        results = []
        for kind, name, chg in rows:
            nm = str(name).strip()
            if not nm or nm in SKIP or len(nm) < 2:
                continue
            keys = {nm}
            for suf in ["概念", "行业", "板块", "Ⅱ", "Ⅲ", "指数", "产业"]:
                if nm.endswith(suf) and len(nm) > len(suf) + 1:
                    keys.add(nm[: -len(suf)])
            keys = {k for k in keys if len(k) >= 2}
            bull, bear, seen = [], [], set()
            for tm, t in uniq_news:
                if t[:24] in seen:
                    continue
                try:
                    if _is_foreign(t):
                        continue
                except Exception:
                    pass
                if any(k in t for k in keys):
                    seen.add(t[:24])
                    try:
                        p = _news_polarity(t)
                    except Exception:
                        p = 0
                    (bull if p >= 0 else bear).append((tm, t))
            net = len(bull) - len(bear)
            if len(bull) + len(bear) < 2:
                continue
            pos = 0
            if chg is not None and pd.notna(chg):
                c = float(chg)
                pos = 3 if c < 0 else (2 if c < 1.5 else (1 if c < 4 else -1))
            results.append((net * 2 + pos, kind, nm, chg, net,
                            len(bull), len(bear), bull))

        if not results:
            w("  今日无板块命中≥2条新闻")
            return
        results.sort(key=lambda x: -x[0])
        w("\n  ★★【有催化 且 位置好】前15（净利多×2 + 位置分）：")
        w("    位置分：跌着有催化=3 | 微涨<1.5%=2 | 涨1.5-4%=1 | 涨>4%=-1")
        for i, (sc, kind, nm, chg, net, nb, nr, _) in enumerate(results[:15], 1):
            ct = f"{chg:+.2f}%" if chg is not None and pd.notna(chg) else "?"
            flag = ""
            if chg is not None and pd.notna(chg):
                if float(chg) < 1.5 and net >= 2:
                    flag = " 🔥★有催化但还没涨★"
                elif float(chg) > 4:
                    flag = " ⚠️已大涨"
            w(f"    {i:2d}. [{kind}]{nm} {ct} 新闻净{net:+d}(↑{nb}↓{nr}) 得分{sc}{flag}")
        w("\n  ★前5名的具体新闻催化：")
        for sc, kind, nm, chg, net, nb, nr, bull in results[:5]:
            ct = f"{chg:+.2f}%" if chg is not None and pd.notna(chg) else "?"
            w(f"\n  ◆【{nm}】{ct} 得分{sc}")
            for tm, t in bull[:4]:
                w(f"      ▸[{tm}] {t[:56]}")
        w("\n  ⚠️ 铁律N：★『有催化但还没涨』的板块 = 明天首选★")
        w("    手工词典必漏，全板块交叉才不漏。")
        w("    仍需过①-B：这个板块的驱动，和它涨的原因是同一个吗？")
    safe_run("全板块交叉", _do)


def scan_deduction(uniq_news, heat_top=None):
    """产业链推演：从已发生的事实，推出还没被市场发现的下游"""
    w("\n" + "=" * 60)
    w("🔮🔮【产业链推演引擎】演绎法 · 找市场还没发现的那一层 🔮🔮")
    w("=" * 60)
    w("  逻辑：热力图管『已发生』(归纳)；推演引擎管『必然要发生』(演绎)")
    w("  信息差 ≠ 比别人先看到新闻（新闻是公开的）")
    w("  信息差 = 同一条新闻，比别人多推演两层")

    heat_top = heat_top or []
    results = []
    for ch in DEDUCTION_CHAINS:
        trig, ver, seen = [], [], set()
        core = ch.get("core", [])
        for tm, t in uniq_news:
            if t[:26] in seen:
                continue
            hit_core = any(k in t for k in core)
            hit_ver = any(k in t for k in ch["verify"])
            # ★验证信号必须同时含【板块核心词】AND【验证动作词】
            if hit_core and hit_ver:
                seen.add(t[:26])
                ver.append((tm, t))
            elif hit_core or any(k in t for k in ch["trigger"]):
                seen.add(t[:26])
                trig.append((tm, t))
        if not trig and not ver:
            continue
        # 市场发现度：该链关键词是否已进热力图前列
        found = any(any(x in h for x in ch["name"].split("→")) for h in heat_top)
        score = len(trig) * 1 + len(ver) * 3 + (0 if found else 4)
        results.append((score, ch, trig, ver, found))

    if not results:
        w("  本期无推演链被触发")
        return
    results.sort(key=lambda x: -x[0])

    w("\n  ★推演价值排行（上游事实×验证信号×市场未发现度）：")
    for i, (sc, ch, trig, ver, found) in enumerate(results[:8], 1):
        mk = "⚠️市场已发现" if found else "✅市场还没发现"
        w(f"    {i}. {ch['name']}：{sc}分（触发{len(trig)} 验证{len(ver)}）{mk}")

    w("\n  ★前3条链的完整推演：")
    for sc, ch, trig, ver, found in results[:3]:
        w(f"\n  ══ 【{ch['name']}】{sc}分 " +
          ("⚠️市场已发现，慎追" if found else "✅市场还没发现，可埋伏"))
        w("    推演路径：")
        for lay in ch["layers"]:
            w(f"      {lay}")
        w(f"    A股标的：{ch['stocks']}")
        if trig:
            w("    ── 上游事实（触发信号）──")
            for tm, t in trig[:3]:
                w(f"      ▸[{tm}] {t[:56]}")
        if ver:
            w("    ── ✅验证信号（真实订单/扩产/涨价，最值钱）──")
            for tm, t in ver[:4]:
                w(f"      ✅[{tm}] {t[:56]}")
        else:
            w("    ── ⚠️无验证信号：只有推演逻辑，没有真实订单/扩产/涨价")
            w("       → 属于『故事阶段』，可观察不可重仓")

    w("\n  ⚠️ 推演铁律：")
    w("    1. 每层推演概率衰减（3层×80% = 51%）→ 必须有验证信号才算成立")
    w("    2. 『战略合作/研究/规划』不算验证；")
    w("       『真实订单/中标/扩产投资/涨价/量产』才算")
    w("    3. 市场已发现(已进热力图前列) = 已被消化，慎追")
    w("    4. 推演出的标的仍需过决策卡九项，尤其④位置⑤游资")
    w("=" * 60)


# ========== ★★深层含义解读器（三线交叉：机构×新闻×推演） ==========
# 用户要的核心能力：不是报数据，是从数据读出别人读不出的含义
# 逻辑：机构买的票 → 对应哪条新闻 → 机构在赌什么 → 下一层风口在哪

# 个股→所属产业环节（用于判断机构买的是产业链哪一层）
STOCK_LAYER = {
    "德明利": ("存储", "模组/终端层"), "江波龙": ("存储", "模组层"),
    "兆易创新": ("存储", "设计层"), "佰维存储": ("存储", "模组层"),
    "雅克科技": ("存储", "★上游材料层(前驱体/电子特气)"),
    "长电科技": ("半导体", "★封测层"), "通富微电": ("半导体", "★封测层"),
    "华海清科": ("半导体", "★设备层"), "北方华创": ("半导体", "★设备层"),
    "中际旭创": ("光模块", "模块层"), "新易盛": ("光模块", "模块层"),
    "源杰科技": ("光模块", "★上游光芯片层"),
    "云南锗业": ("光模块", "★★InP衬底层(第4层,最少被发现)"),
    "博杰股份": ("光模块", "★★磷化铟链"),
    "有研新材": ("光模块", "★★衬底材料层"), "仕佳光子": ("光模块", "★上游光芯片"),
    "紫光股份": ("算力", "服务器/交换机层"), "共进股份": ("算力", "交换机层"),
    "英维克": ("算力", "★散热层"), "申菱环境": ("算力", "★散热层"),
    "麦格米特": ("算力", "★供电层"), "科华数据": ("算力", "★供电层"),
    "东山精密": ("PCB", "★载板层"), "胜宏科技": ("PCB", "载板层"),
    "药明康德": ("AI+制药", "CXO龙头层"), "成都先导": ("AI+制药", "★DEL+AI平台层"),
    "泓博医药": ("AI+制药", "★AI药物设计层"), "美迪西": ("AI+制药", "临床前CRO层"),
    "皓元医药": ("AI+制药", "分子砌块层"), "凯莱英": ("AI+制药", "CDMO层"),
    "容百科技": ("锂电", "★钠电正极层"), "华阳股份": ("锂电", "★钠电层"),
}

# 全球新闻→A股传导链（读出"这条新闻对A股哪一层最有意义"）
GLOBAL_IMPACT = [
    {"kw": ["capex", "资本开支", "云厂", "AWS", "Azure", "数据中心投资"],
     "means": "云厂真金白银扩产 = AI需求是真的，不是故事",
     "next": "第一波炒芯片→第二波炒服务器/交换机→★第三波炒散热+供电(市场常滞后)"},
    {"kw": ["NAND", "DRAM", "HBM", "存储涨价", "缺货", "长约"],
     "means": "存储进入涨价周期，原厂议价权回归",
     "next": "原厂涨价→模组厂跟涨→终端涨价→★上游材料/设备紧缺(最后被发现)"},
    {"kw": ["封测", "CoWoS", "先进封装", "载板", "玻璃基"],
     "means": "先进封装是算力瓶颈，产能=硬通货",
     "next": "封测厂满产→★封装设备/材料/载板(A股滞后于台系)"},
    {"kw": ["核电", "特高压", "电网投资", "十五五电力"],
     "means": "算力耗电是硬约束，电力是AI的影子行情",
     "next": "电网投资→设备招标→★核级泵阀/换流阀/储能(订单落地才是真信号)"},
    {"kw": ["消费税", "钠电", "碳酸锂"],
     "means": "政策改变成本结构，替代路线加速",
     "next": "锂电成本↑→★钠电替代→正极/硬碳负极/铝箔集流体"},
    {"kw": ["人形机器人", "具身智能", "量产", "定点"],
     "means": "从demo进入量产爬坡，零部件开始放量",
     "next": "整机厂扩产→★谐波/丝杠/灵巧手/无框电机"},
    {"kw": ["AI制药", "AI药物", "靶点", "CXO", "医疗大模型", "AI+医疗",
            "分子设计", "脑机接口", "AI诊断"],
     "means": "AI改写新药研发范式，研发成本/周期结构性下降",
     "next": "★与集采完全无关！集采杀的是仿制药定价，AI+制药靠的是研发效率\n"
             "       AI平台→CXO订单↑→★算力+生物计算双属性标的(最少被发现)"},
    {"kw": ["美联储", "加息", "降息", "美债收益率"],
     "means": "全球流动性的总闸门，决定成长股估值",
     "next": "加息→杀成长利好银行/红利；降息→利好成长/黄金"},
    {"kw": ["霍尔木兹", "OPEC", "原油", "地缘"],
     "means": "油价是通胀的先行指标，影响利率路径",
     "next": "油涨→通胀→加息→杀成长；油跌→利好成长(与AI链正相关)"},
]


def scan_deep_meaning(uniq_news, ambush_list=None):
    """深层含义：机构买的票在产业链哪一层 + 对应新闻 + 下一个风口"""
    w("\n" + "=" * 60)
    w("🧠🧠【深层含义解读器】机构动向 × 全球新闻 × 产业链推演 🧠🧠")
    w("=" * 60)
    w("  核心问题：机构买的这只票，在产业链的哪一层？它在赌什么？")
    w("           市场在炒第几层？还有哪一层没被发现？")

    # 一、机构买的票在哪一层
    w("\n  ★① 机构/游资埋伏标的 → 产业链层级定位")
    hits = []
    if ambush_list:
        for item in ambush_list:
            nm = item.get("name", "") if isinstance(item, dict) else str(item)
            for k, (chain, layer) in STOCK_LAYER.items():
                if k in nm:
                    hits.append((nm, chain, layer))
                    break
    if hits:
        for nm, chain, layer in hits:
            star = "★★" if "★" in layer else ""
            w(f"    {nm} → [{chain}] {layer} {star}")
        w("    ⚠️ 带★=上游/被忽略层。机构买上游 = 它认为这波不是短炒，是产能周期")
    else:
        w("    （今日埋伏池无数据，或标的不在映射表中）")

    # 二、全球新闻的深层含义 + 下一层
    w("\n  ★② 今日全球新闻 → 深层含义 → 下一个风口在哪一层")
    for g in GLOBAL_IMPACT:
        matched, seen = [], set()
        for tm, t in uniq_news:
            if any(k in t for k in g["kw"]) and t[:26] not in seen:
                seen.add(t[:26])
                matched.append((tm, t))
        if len(matched) < 2:
            continue
        w(f"\n    ◆ 命中 {len(matched)} 条 → 【{g['means']}】")
        for tm, t in matched[:2]:
            w(f"       ▸[{tm}] {t[:52]}")
        w(f"       🔮 下一层：{g['next']}")

    w("\n  ★③ 三线交叉结论（AI必须自己写，不能只列数据）：")
    w("     格式：机构在买【X层】+ 新闻说【Y在发生】+ 市场在炒【Z层】")
    w("          → 结论：还没被炒的是【W层】，那是下一个风口")
    w("")
    w("  ⚠️ 铁律K（V4.2）：★越反常的交易，含义越深★")
    w("    正常交易不含信息（涨停被追/跌了被割，人人都会）")
    w("    反常交易才是信息差：")
    w("      · 跌停板被机构砸几亿买 → 他知道你不知道的")
    w("      · 利好满天飞却有机构净卖 → 这利好是假的")
    w("      · 板块跌但资金大幅流入 → 有人在恐慌里收货")
    w("      · 全场追涨停时某票缩量横盘量比>1.3 → 有人在悄悄吸")
    w("    ★AI亏钱的每一笔都买在『正常』里，赚的机会都在『反常』里")
    w("=" * 60)


# ========== ★买入后复核（防御系统核心：提早发现"我买错了"） ==========
# 用户原话："做错方向不可怕，提早发现做错并及时止损才是真正厉害的地方"
# 卖出卡管的是【逻辑破了】(外部变了)；本模块管的是【我当初就判断错了】(内部错了)

# 买入时的关键判据快照（AI每次推荐后必须填这张表）
ENTRY_SNAPSHOT = {
    "603220": {"name": "中贝通信", "date": "2026-08-04",
               "sector": "通信服务", "sector_fund": "+103.74亿(通信设备全场第一)",
               "sector_day": "连3天", "ambush": "冷低早量比1.31(暗流)",
               "key": "AI算力capex 7500亿 + 冷低早90%胜率"},
    "159934": {"name": "黄金ETF易", "date": "2026-08-05",
               "sector": "贵金属", "sector_fund": "+45.23亿(全场第一)",
               "sector_day": "连2天🚀51→1名",
               "ambush": "⚠️埋伏池为空",
               "key": "金价破4130→4200 + 韩国央行13年首次购金 + 加息概率64.7%→58.4%"},
    "000938": {"name": "紫光股份", "date": "2026-07-31",
               "sector": "计算机设备", "sector_fund": "板块流入",
               "sector_day": "🆕第1天", "ambush": "✅机构净买5.06亿(占92%)",
               "key": "算力网4万亿 + 云厂capex"},
    "159796": {"name": "电池ETF汇", "date": "2026-07-27",
               "sector": "电池", "sector_fund": "+68.14亿(全场第一)",
               "sector_day": "🆕第1天", "ambush": "⚠️埋伏池为空",
               "key": "9/1消费税倒计时"},
    "301269": {"name": "华大九天", "date": "2026-07-27",
               "sector": "软件开发", "sector_fund": "+57.9亿",
               "sector_day": "🆕第1天", "ambush": "⚠️埋伏池为空",
               "key": "国产EDA替代"},
    "002714": {"name": "牧原股份", "date": "2026-07-10",
               "sector": "养殖业", "sector_fund": "—",
               "sector_day": "—", "ambush": "—",
               "key": "⚠️政治局'稳定生猪价格'(事后发现是中性表述，非利好)"},
}


def scan_entry_review():
    """买入后复核：用今天的数据，重新审当初的判断对不对"""
    w("\n" + "=" * 60)
    w("🛡️【买入后复核·防御核心】提早发现『我当初就买错了』")
    w("=" * 60)
    w("  卖出卡管【逻辑破了】(外部变)；本模块管【我判断错了】(内部错)")
    w("  ⚠️ 两者都要走，但触发条件不同：")
    w("     逻辑破 → 按买入时写死的定义走")
    w("     判断错 → 关键判据反转即走，不必等逻辑破")

    def _do():
        _, bdf = multi_source("板块(复核)", [
            ("同花顺", lambda: ak.stock_fund_flow_industry(symbol="即时")),
            ("东财", lambda: ak.stock_sector_fund_flow_rank(
                indicator="今日", sector_type="行业资金流")),
        ])
        cur = {}
        if bdf is not None:
            bn = pick_col(bdf, ["名称", "行业", "板块"])
            bp = pick_col(bdf, ["涨跌幅", "行业指数涨跌", "涨跌"])
            bv = pick_col(bdf, ["主力净流入-净额", "主力净流入", "净额", "流入资金"])
            for _, r in bdf.iterrows():
                v = pd.to_numeric(r[bv], errors="coerce") if bv else None
                if v is not None and pd.notna(v) and abs(v) > 1e6:
                    v = v / 1e8
                p = pd.to_numeric(r[bp], errors="coerce") if bp else None
                cur[str(r[bn])] = (p, v)

        for code, snap in ENTRY_SNAPSHOT.items():
            w(f"\n  ◆ {snap['name']}({code})  买入日 {snap['date']}")
            w(f"     当初理由：{snap['key']}")
            w(f"     当初板块：{snap['sector']} 资金{snap['sector_fund']} {snap['sector_day']}")
            w(f"     当初游资：{snap['ambush']}")
            flags = []
            # 复核1：买入时⑤就是"埋伏池为空/追高型" = 当初判据本身有瑕疵
            if "⚠️" in snap["ambush"]:
                flags.append("买入时⑤游资项就有瑕疵（当时不该给A级）")
            if "⚠️" in snap["key"]:
                flags.append("买入理由本身存疑（事后发现误读）")
            # 复核2：板块资金是否反转
            hit = None
            for k, (p, v) in cur.items():
                if snap["sector"] in k or k in snap["sector"]:
                    hit = (k, p, v)
                    break
            if hit:
                k, p, v = hit
                pt = f"{p:+.2f}%" if p is not None and pd.notna(p) else "?"
                vt = f"{v:+.2f}亿" if v is not None and pd.notna(v) else "?"
                w(f"     今日板块：[{k}] {pt} 资金{vt}")
                if v is not None and pd.notna(v) and v < -10 and "+" in snap["sector_fund"]:
                    flags.append(f"板块资金从流入反转为流出{v:.1f}亿")
            else:
                w("     今日板块：无数据")

            if not flags:
                w("     ✅【初判成立】关键判据未反转，按原计划持有")
            elif len(flags) == 1:
                w(f"     ⚠️【初判存疑】{flags[0]}")
                w("        → 建议：不加仓，反弹减半，止损上移")
            else:
                w("     🔴【初判已错】" + "；".join(flags))
                w("        → 建议：不等逻辑破，直接减仓或退出")
                w("        （这就是『提早发现做错』——比等逻辑破更早）")

        w("\n  ⚠️ 铁律J（V4.1新增）：")
        w("    买入后48小时内，必须用新数据复核一次关键判据")
        w("    ①板块资金反转 ②游资从埋伏变追高 ③买入理由被证伪")
        w("    → 命中2项 = 初判已错 = 立刻减仓，不许等逻辑破")
        w("    ★区别：逻辑破=外部变了(认赔)；初判错=我看错了(认错)")
        w("      认错要比认赔更快，因为错的是起点不是过程")
    safe_run("买入后复核", _do)


# ========== ★埋伏信号转化率（治"识别到却不买"） ==========
# 高价股/买不起的票 → 自动映射到可买的ETF
HIGH_PRICE_ETF = {
    "中际旭创": "光模块/通信ETF：515880通信ETF、159516光模块ETF",
    "新易盛": "光模块/通信ETF：515880通信ETF、159516光模块ETF",
    "天孚通信": "光模块/通信ETF：515880、159516",
    "寒武纪": "科创芯片ETF：588200、589130",
    "海光信息": "科创芯片ETF：588200、589130",
    "北方华创": "半导体设备ETF：159516、561980",
    "中微公司": "半导体设备ETF：159516、561980",
    "长鑫科技": "存储/科创芯片ETF：588200",
    "德明利": "存储芯片ETF、半导体ETF：512480",
    "兆易创新": "存储芯片ETF、半导体ETF：512480",
    "药明康德": "创新药/医疗ETF：512170、159992",
    "宁德时代": "电池ETF：159796、新能源车ETF",
}

# ★埋伏信号台账（AI每次识别到机构埋伏，必须记在这，并注明是否给出可执行标的）
AMBUSH_SIGNALS = [
    # (识别日, 标的, 信号强度, 是否给出可执行标的, 结果)
    ("2026-07-28", "中际旭创/新易盛", "机构37.47亿跌停板买入", "否-只说观察",
     "7/29+4.74% → 8/4累计+19.6% ❌错过"),
    ("2026-07-30", "长电科技", "四大机构3.17亿跌停板买入", "否-只说观察",
     "7/31费半+8.19% ❌错过"),
    ("2026-08-03", "德明利/雅克/通富", "机构8.19亿跌停板买入", "给了信号卡未执行",
     "8/4中际旭创+8.91%、新易盛+9.96% ❌错过"),
]


def scan_signal_conversion():
    """埋伏信号转化率：识别了多少次？真正下单了几次？"""
    w("\n" + "=" * 60)
    w("🎯【埋伏信号转化率】治AI通病：识别到信号却不给可执行标的")
    w("=" * 60)
    if not AMBUSH_SIGNALS:
        w("  暂无记录")
        return
    total = len(AMBUSH_SIGNALS)
    done = sum(1 for x in AMBUSH_SIGNALS if x[3].startswith("是"))
    w(f"  ★累计识别 {total} 次埋伏信号，真正转化为可执行标的 {done} 次")
    w(f"  ★转化率 {done/total*100:.0f}%")
    w("")
    for d, name, sig, conv, res in AMBUSH_SIGNALS:
        flag = "✅已转化" if conv.startswith("是") else "❌未转化"
        w(f"  {d} {name}")
        w(f"     信号：{sig}")
        w(f"     {flag}（{conv}）")
        w(f"     结果：{res}")
    w("")
    w("  ⚠️ 铁律H（V4.0新增）：")
    w("    识别到【机构在跌的票上净买≥1亿】= 必须当场给出可执行标的")
    w("    ① 个股买得起 → 直接给个股 + 买点 + 止损")
    w("    ② 个股太贵(一手>总资产10%) → 必须给对应ETF，不许只说『观察』")
    w("    ③ 不许用『等明天验证』当拖延借口——")
    w("       验证的正确方式是【小仓位试探】，不是【完全不买】")
    w("    ④ 信号次日若下跌，不算信号错，B类仓要给足3个交易日")
    w("")
    w("  ★高价股→可买ETF 映射表（买不起个股就买这个）：")
    for k, v in list(HIGH_PRICE_ETF.items())[:8]:
        w(f"    {k} → {v}")
    w("=" * 60)


# ========== ★AI推荐台账（自动对账，战绩不靠记忆） ==========

def scan_ledger():
    w("\n★★★【AI推荐台账·自动对账】★★★（战绩机器记账，赖不掉）")
    if not RECOMMENDATIONS:
        w("  台账为空")
        return

    def _do():
        spot = get_spot()
        etf = None
        c_code = pick_col(spot, ["代码", "code"]) if spot is not None else None
        c_price = pick_col(spot, ["最新价", "trade"]) if spot is not None else None
        today = now_beijing()
        win = lose = 0
        for d, code, name, cost, typ, period, broken in RECOMMENDATIONS:
            price = None
            try:
                if spot is not None:
                    r = spot[spot[c_code].astype(str).str.contains(code, na=False)]
                    if len(r) > 0:
                        price = pd.to_numeric(r.iloc[0][c_price], errors="coerce")
                if price is None or pd.isna(price):
                    if etf is None:
                        etf = get_etf_spot()
                    if etf is not None:
                        ec = pick_col(etf, ["代码", "symbol"])
                        ep = pick_col(etf, ["最新价", "trade"])
                        r = etf[etf[ec].astype(str).str.contains(code, na=False)]
                        if len(r) > 0:
                            price = pd.to_numeric(r.iloc[0][ep], errors="coerce")
            except Exception:
                pass
            days = (today - datetime.datetime.strptime(d, "%Y-%m-%d")).days
            if price is None or pd.isna(price):
                w(f"  {d} {name}({code}) @{cost} [{typ}类] → 取价失败")
                continue
            pnl = (price - cost) / cost * 100
            # ★胜利标准（V4.4）：≥10%才算赚钱，扣掉手续费/印花税/滑点后才有意义
            if pnl >= 10:
                win += 1
                flag = "✅赚钱"
            elif pnl > 0:
                lose += 0
                flag = "⏳在途(未达10%不算赚)"
            else:
                lose += 1
                flag = "❌"
            extra = ""
            if typ == "A":
                extra = f" ⚠️事件仓已持有{days}天，事件仓不该超3天"
            else:
                extra = f" 周期仓第{days}天/{period}"
            w(f"  {flag} {d} {name}({code}) @{cost}→{price} {pnl:+.2f}% [{typ}类]{extra}")
            w(f"       逻辑破的定义：{broken}")
        w(f"\n  ★战绩：{win}胜(≥10%) {lose}负")
        w("  ⚠️ 胜利标准=盈利≥10%。低于10%只算『在途』，")
        w("     扣手续费/印花税/滑点后基本无利润，不许当成功。")
        w("  ⚠️ A类事件仓超期未走 = 违反铁律，立即处理")
        w("  ⚠️ B类周期仓在期内跌5-8% = 噪音，不许砍（铁律F）")
    safe_run("推荐台账", _do)


# ========== ★卖出决策卡（治"买入用长线逻辑，卖出用短线跌幅"） ==========

def scan_sell_card():
    w("\n" + "=" * 60)
    w("★★★【卖出决策卡 · 想卖之前必须填完】★★★")
    w("=" * 60)
    w("  标的：____________")
    w("")
    w("  ① 当初买入是 A类事件仓 还是 B类周期仓？")
    w("     → ______________________")
    w("")
    w("  ② 当初写死的『逻辑破』定义是什么？（去台账里查，不许现编）")
    w("     → ______________________")
    w("")
    w("  ③ 这个定义现在触发了吗？  □是 → 走  □否 → 看④")
    w("     → ______________________")
    w("")
    w("  ④ 没触发却想卖，理由是什么？")
    w("     『它跌了X%』         → ❌ 不是理由，B类仓5-8%是噪音")
    w("     『我怕』             → ❌ 不是理由")
    w("     『大盘不好』         → ❌ 除非驱动链本身断了")
    w("     『催化取消/证伪』     → ✅ 这才是理由")
    w("     『板块驱动链断裂』    → ✅ 这才是理由")
    w("     『A类事件已兑现』     → ✅ 这才是理由")
    w("     → ______________________")
    w("")
    w("  ⑤ 如果卖了，这笔钱去哪？（说不出去处 = 不该卖）")
    w("     → ______________________")
    w("  ─────────────────────────────────────")
    w("  ⚠️ 填不出④里的✅项 = 不许卖")
    w("  ⚠️ 铁律F：买入用产业周期逻辑，就不许用短线跌幅卖出")
    w("=" * 60)


# ========== ★决策卡（任何买卖建议前必填，防止AI忘记自己的铁律） ==========

def scan_decision_card():
    w("\n" + "=" * 60)
    w("★★★【决策卡 · 买卖前必填，填不满不许出建议】★★★")
    w("=" * 60)
    w("  标的：____________  方向：买 / 卖 / 等")
    w("")
    w("  ① 板块第几天？🆕第1天 | 连2天 | 🔥连≥5天")
    w("     ⚠️★天数必须绑定③-B判读，单独看天数没有意义★")
    w("       产业周期驱动 → 连20-30天都正常，回调是买点")
    w("       单一事件驱动 → 连3-5天就是高潮")
    w("     → ______________________")
    w("")
    w("  ①-B ★★★这只票的【真实驱动】是什么？★★★（V4.5，最易错的一项）")
    w("     ⚠️ 行业分类 ≠ 真实驱动。同一分类里可以有相反的驱动！")
    w("     必须回答两句：")
    w("       a) 这只票靠什么赚钱？（下游客户是谁、需求来自哪）")
    w("       b) 今天板块上涨的原因，和它的驱动是【同一个】吗？")
    w("     ★不是同一个 → 『板块顺风』对它无效 → ①作废")
    w("")
    w("     血的教训（都是同一个错）：")
    w("       · 招商轮船[航运港口] 真实驱动=西芒杜铁矿长约")
    w("         我却用『油气开采跌4%』判它死 → 卖飞18%")
    w("       · 卓胜微[半导体] 真实驱动=手机出货量")
    w("         半导体涨是因为存储涨价/设备/AI算力，与它无关")
    w("         而且存储涨价→手机成本↑→对它是利空")
    w("       · 紫光股份[计算机设备] 真实驱动=云厂capex ✅这个对了")
    w("     → ______________________")
    w("")
    w("  ② 板块资金今日流向？（流入✅ / 流出⚠️，但看③）")
    w("     → ______________________")
    w("")
    w("  ③-A 催化是什么？有没有具体日期？")
    w("     → ______________________")
    w("  ③-B ★★这个催化是【产业周期】还是【单一事件】？★★")
    w("     【产业周期】涨价/缺货/产能紧缺/政策倒计时/国产替代")
    w("        → 能持续几周几月，每天涨也能追，而且该追")
    w("        → 必须填出：预计持续 ____ 周")
    w("     【单一事件】IPO上市/发布会/财报/政策发布日")
    w("        → 事件当天就是顶，事后买必亏")
    w("     ⚠️ 填不出『持续N周』= 当成单一事件 = 不许当趋势买")
    w("     → ______________________")
    w("")
    w("  ④ 位置：60日涨跌 / 均线？")
    w("     → ______________________")
    w("")
    w("  ⑤ 游资：埋伏型(买当天在跌的)✅ / 追高型(买涨停的)⚠️")
    w("     → ______________________")
    w("")
    w("  ⑥ 宏观驱动链冲突？油涨→杀成长；油跌→利好成长")
    w("     → ______________________")
    w("")
    w("  ⑦ 与今天其他建议冲突吗？")
    w("     → ______________________")
    w("")
    w("  ⑧ ★★与现有持仓是不是同一条驱动链？★★")
    w("     同一条链的仓位合计不许超过总仓位40%")
    w("     → ______________________")
    w("")
    w("  ⑨ ★★仓位类型 + 持有周期 + 逻辑破的定义（买入时就写死）★★")
    w("     □ 产业周期仓 → 持有 ____ 周")
    w("        卖出条件：只有『驱动逻辑破了』才走")
    w("        逻辑破 = ____________________（现在就写，不许事后找）")
    w("        ⚠️ 期间跌5-8%是噪音，不许砍")
    w("     □ 事件仓 → 持有 ____ 天，兑现日无条件走")
    w("     → ______________________")
    w("")
    w("  ─────────────────────────────────────")
    w("  ⚠️ 铁律A：有日期的未来催化 > 过去的资金流")
    w("  ⚠️ 铁律B：游资在跌的板块砸钱 = 埋伏 = 明天机会")
    w("  ⚠️ 铁律C：先board再stock，板块逆风一票否决")
    w("  ⚠️ 铁律D：宁可报空，不硬凑标的。一周最多1-2笔")
    w("  ⚠️ 铁律E：踏空也是亏，方向确认就给进攻方案")
    w("  ⚠️ 铁律F：★买入用什么逻辑，卖出就用什么标尺★")
    w("     用产业周期让他买，就不许用短线跌幅让他卖")
    w("  ⚠️ 铁律O：★连涨天数不构成买卖理由★")
    w("     天数只有绑定驱动类型才有意义：")
    w("     产业周期(存储/AI算力/国产替代)连30天都不算高潮")
    w("     单一事件(IPO/发布会)连3天就到顶")
    w("  ⚠️ 铁律L：★推荐前必须先答①-B『真实驱动是什么』★")
    w("     答不出『它靠什么赚钱、需求来自哪』= 不许推荐")
    w("     行业分类只是标签，驱动才是本质")
    w("  ⚠️ 铁律H：★识别到机构埋伏信号=必须给可执行标的★")
    w("     个股太贵就给ETF，不许只说『观察』或『等明天验证』")
    w("     验证的方式是小仓位试探，不是完全不买")
    w("  ⚠️ 铁律I：★决策卡⑤只认『机构专用席位买跌的票』★")
    w("     封单大/炸板0次 ≠ 埋伏型，那只能证明有人封板")
    w("  ⚠️ 铁律G：不许推『今天资金第一』当买入理由——")
    w("     那是收盘后算的，等于买在当天最高点。")
    w("     除非③-B能填出『产业周期·持续N周』")
    w("=" * 60)
    w("")
    w("=" * 60)
    w("★★★【固定输出骨架 · AI每次干活必须全给，缺一节可当场追责】★★★")
    w("=" * 60)
    w("  ① 【数据新鲜度判定】报告时间/距今/最新可用或陈旧弃用")
    w("  ② ★重点盯盘（全部持仓 + 中国长城，逐只：板块/资金/技术/消息）")
    w("  ③ 大盘环境 + 风险分 + 结构分化（创业板/科创50跌幅）")
    w("  ④ 板块判断（先board再stock）")
    w("  ⑤ 全套新闻·八类（名人/国内政策/海外政策/科技/大宗地缘/")
    w("     资金事件/消费养殖/政策产业专项）——不许等用户提醒")
    w("  ⑥ 决策卡（要买卖时逐项填，含③-B ⑧ ⑨）")
    w("  ⑦ 持仓逐个指令（持有/减/清 + 理由）")
    w("  ⑧ AI推荐台账对账（A类超期？B类在期内？）")
    w("  ⑨ 要卖时必填【卖出决策卡】，④里填不出✅项=不许卖")
    w("=" * 60)


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
    w(f"A股作战扫描器V5.4 | {bj.strftime('%Y-%m-%d %H:%M')} {weekday} | {mode}")
    w("=" * 60)

    scan_skeleton_top()

    if weekend:
        scan_news()
    else:
        scan_regime_gate()
        scan_tomorrow_gate()
        scan_watchlist()
        scan_focus_stocks()
        scan_intraday_hotmoney()
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

    if not weekend:
        safe_run("埋伏池回测", lambda: backtest_ambush(TODAY_AMBUSH))
        safe_run("热力图回测", lambda: backtest_heat(TODAY_HEAT_TOP3))
    safe_run("仓位建议", lambda: scan_position_advice(LAST_RISK_SCORE))
    scan_rule_scorecard()
    safe_run("买入后复核", scan_entry_review)
    scan_signal_conversion()
    scan_ledger()
    scan_sell_card()
    scan_decision_card()

    os.makedirs("reports", exist_ok=True)
    text = "\n".join(REPORT)
    date = bj.strftime("%Y%m%d")
    prefix = "盘中" if intraday else ("周末" if weekend else "盘后")

    for path in [f"reports/{prefix}_最新.txt", f"reports/{prefix}_{date}.txt",
                 "reports/latest.txt"]:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    print(f"\n✅ V5.4完成 {prefix}_最新.txt")


if __name__ == "__main__":
    main()

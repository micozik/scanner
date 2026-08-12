# -*- coding: utf-8 -*-
"""
美股夜盘扫描器 · 独立版 V3.3（2026-08-12 修复个股数据滞后2天）
V3.3：个股改用【实时行情接口】，日K只做兜底。
  8/12实测所有个股显示8/10数据（滞后2天）。根因：stock_us_hist是日K接口，
  只有已结算的日线；美股8/11收盘=北京8/12凌晨4点，5:24跑时日K源还没更新。
  → 实时接口拿的是最新价（含刚收盘那一场），这才是【持仓夜盘影响】需要的。
V3.2 两项修复：
  1. 🔴极性误判：『利空出尽』含"利空"→被判利空，把AI算力链(用户25%仓位)
     错标为❄️偏空。同类：『超跌反弹』含"跌"、『跌幅收窄』含"跌"。
     现在先做【反转短语】识别，再数单字关键词。
  2. 🔴A股研报污染：美股→A股映射排第一的【金融】，三条催化全是中信证券
     A股研报，不是美股新闻。美股热力图在吃A股的饭，等于自己给自己
     绕回来一遍，毫无信息增量。现在过滤掉A股券商研报。
V3.0 四项改动：
  1. scan_us_heat 从 scan_news 内剪出 → main() 独立运行
     （原来新闻源全挂就 return，把映射表一起吞掉，和A股止盈同一个病）
  2. ★新增【持仓夜盘影响】：用美股【真实涨跌幅】直接点名你的A股持仓
     （原来只有"存储→A股存储链"这种抽象映射，最后一步靠人脑，
       而招商轮船/卓胜微两次翻车正是错在这一步）
  3. ★新增 us_map_history.json + 次日回测 → 净利多前3到底准不准，机器说了算
  4. 删除不存在的 SKHY；指数/个股加数据日期新鲜度标注；BRK 双写法容错
输出：reports/美股_最新.txt + reports/美股_日期.txt
与A股扫描器完全独立，互不影响
"""

import os, json, time, signal, datetime
import akshare as ak
import pandas as pd

REPORT = []
US_MAP_HIST_FILE = "reports/us_map_history.json"

US_TICKERS = [
    ("英伟达", "NVDA"), ("台积电", "TSM"), ("美光", "MU"), ("AMD", "AMD"),
    ("博通", "AVGO"), ("特斯拉", "TSLA"), ("苹果", "AAPL"),
    ("阿斯麦", "ASML"), ("英特尔", "INTC"), ("阿里巴巴", "BABA"), ("Meta", "META"),
    ("微软", "MSFT"), ("谷歌", "GOOGL"), ("亚马逊", "AMZN"), ("希捷", "STX"),
    ("西部数据", "WDC"), ("闪迪", "SNDK"), ("应用材料", "AMAT"), ("拉姆研究", "LRCX"),
    ("康宁", "GLW"), ("Coherent", "COHR"), ("礼来", "LLY"), ("纽蒙特", "NEM"),
    ("伯克希尔B", "BRK.B"), ("伯克希尔A", "BRK.A"),
    # ★V3.0 删除 SKHY：SK海力士只在韩国上市(000660.KS)，美股无ADR，永远报空白等30秒
]

US_INDEX = [
    ("道琼斯", ".DJI"), ("纳斯达克", ".IXIC"), ("标普500", ".INX"),
    ("费城半导体", ".SOX"),
]

# ★★V3.0 核心新增：A股持仓 → 美股先行标的
# 与 scanner_cloud.py 的 WATCH_STOCKS 驱动链一一对应，买卖后两边一起改。
# 格式：(A股代码, 名称, 驱动链, 成本, 止损, [(美股ticker, 权重), ...])
# 权重：这只美股对该A股的解释力。1.0=直接对标，0.5=同链但间接。
MY_HOLDINGS = [
    ("000938", "紫光股份", "AI算力链", 34.681, 29.48,
     [("NVDA", 1.0), ("AVGO", 0.8), ("AMD", 0.5), ("MSFT", 0.5)]),
    # ★V3.1 修正：Coherent/康宁暴涨由CPO光模块驱动，中贝通信真实驱动是算力租赁/
    #   数据中心建设，两者不是同一驱动（①-B）。旧权重COHR0.6/GLW0.5属于
    #   "拿板块顺风给它加分"，正是铁律L禁止的错误。降到0.2仅作参考。
    ("603220", "中贝通信", "AI算力链", 18.396, 16.19,
     [("NVDA", 0.8), ("AVGO", 0.5), ("MSFT", 0.5), ("AMZN", 0.5),
      ("COHR", 0.2), ("GLW", 0.2)]),
    ("688126", "沪硅产业", "半导体材料链", 26.228, 22.90,
     [("MU", 0.8), ("AMAT", 1.0), ("LRCX", 1.0), ("ASML", 0.8), ("TSM", 0.6)]),
    ("605376", "博迁新材", "MLCC涨价链", 165.223, 144.00,
     [("AAPL", 0.6), ("TSLA", 0.4)]),
    ("159796", "电池ETF汇", "锂电/钠电链", 0.820, 0.760,
     [("TSLA", 1.0)]),
    ("159934", "黄金ETF易", "贵金属链", 8.938, 8.20,
     [("NEM", 1.0)]),
    ("516080", "创新药ETF", "医药链", 0.710, 0.640,
     [("LLY", 0.8)]),
    ("002714", "牧原股份", "农业(独立)", 39.613, 36.50,
     []),   # 猪周期与美股无关，空表示"今夜美股不影响它"
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

# 全局：本次抓到的美股个股行情 {ticker: (涨跌幅, 收盘价, 数据日期)}
US_QUOTE = {}
TODAY_MAP_TOP3 = []


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


def _stale_tag(dstr):
    """★V3.0 数据新鲜度：周一早上拿到的是周五收盘，必须标出来
    错题㉑：周五收盘=周一方向已定，但别把陈旧数据当成今天的"""
    try:
        d = datetime.datetime.strptime(str(dstr)[:10], "%Y-%m-%d")
        gap = (now_beijing().date() - d.date()).days
        if gap <= 1:
            return ""
        return f" ⚠️距今{gap}天(非最新)"
    except Exception:
        return ""


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
        os.makedirs("reports", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


# ========== 一、美股指数 ==========

def scan_index():
    w("\n【一、美股指数】（费城半导体SOX最关键=A股半导体风向标）")

    def _do():
        # ★V3.3 指数实时源（日K同样滞后）
        rt = {}
        for fname in ("index_us_stock_sina_spot", "stock_us_famous_spot_em"):
            fn = getattr(ak, fname, None)
            if fn is None:
                continue
            try:
                d0 = with_retry(fn, tries=1, timeout=30)
                if d0 is not None and len(d0) > 0:
                    w(f"  （实时指数源：{fname}）")
                    break
            except Exception:
                continue
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
                w(f"    {name}：{close}{pct}  [{d}]{_stale_tag(d)}")
            except Exception as e:
                w(f"    {name}：[报空] {type(e).__name__}")
            time.sleep(1)
    safe_run("美股指数", _do)


# ========== 二、重点个股（含伯克希尔） ==========

def _build_us_spot():
    """★★V3.3 美股实时行情映射★★
    ★为什么必须加：8/12实测所有个股数据滞后2天（显示8/10）。
      根因不是接口坏了，是 stock_us_hist 是【日K接口】，
      只有"已结算"的日线。美股8/11收盘=北京8/12凌晨4点，
      扫描器5:24跑时日K源还没更新那一根 → 只能返回8/10。
    ★实时接口拿的是最新价（含刚收盘那一场），才是我们要的。
    返回 {ticker: (最新价, 涨跌幅)}"""
    m = {}
    for fname in ("stock_us_spot_em", "stock_us_spot"):
        fn = getattr(ak, fname, None)
        if fn is None:
            continue
        try:
            df = with_retry(fn, tries=1, wait=3, timeout=60)
            if df is None or len(df) == 0:
                continue
            c_sym = pick_col(df, ["代码", "symbol", "code"])
            c_name = pick_col(df, ["名称", "name"])
            c_p = pick_col(df, ["最新价", "price", "最新"])
            c_pct = pick_col(df, ["涨跌幅", "changepercent", "chg"])
            if not (c_sym and c_p):
                continue
            for _, r in df.iterrows():
                try:
                    sym = str(r[c_sym]).upper()
                    # 东财返回形如 "105.NVDA"，取点号后一段
                    tk = sym.split(".")[-1] if "." in sym else sym
                    px = pd.to_numeric(r[c_p], errors="coerce")
                    pc = pd.to_numeric(r[c_pct], errors="coerce") if c_pct else None
                    if pd.notna(px) and float(px) > 0:
                        m[tk] = (float(px),
                                 float(pc) if pc is not None and pd.notna(pc) else None)
                except Exception:
                    continue
            if len(m) > 100:
                w(f"  ✅ 实时行情源：{fname}（{len(m)}只）→ 个股不再滞后")
                return m
        except Exception as e:
            w(f"  [切换] {fname} 失败({type(e).__name__})")
    if not m:
        w("  ⚠️ 实时行情源全部失败 → 降级为日K接口，数据可能滞后1-2天")
    return m


def scan_stocks():
    w("\n【二、重点个股】（芯片/算力/存储/中概 + 伯克希尔）")
    spot_map = _build_us_spot()

    def _one(tk):
        # ★★V3.3：优先用实时行情，日K只做兜底★★
        key = tk.upper().replace(".", "-")
        for k in (tk.upper(), key, tk.upper().replace(".", "")):
            if k in spot_map:
                px, pc = spot_map[k]
                d = now_beijing().strftime("%Y-%m-%d")
                return px, pc, d, "", "实时"
        # ★V3.0：BRK.A/BRK.B 各源写法不一，双写法容错
        variants = [tk]
        if "." in tk:
            variants.append(tk.replace(".", "-"))
        for cand in variants:
            for fname in ["stock_us_hist", "stock_us_daily"]:
                try:
                    fn = getattr(ak, fname, None)
                    if fn is None:
                        continue
                    if fname == "stock_us_daily":
                        df = with_retry(lambda c=cand, f=fn: f(symbol=c, adjust=""),
                                        tries=1, timeout=30)
                    else:
                        end = now_beijing().strftime("%Y%m%d")
                        start = (now_beijing() - datetime.timedelta(days=12)).strftime("%Y%m%d")
                        df = with_retry(
                            lambda c=cand, f=fn: f(symbol=c, period="daily", start_date=start,
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
                w(f"    {cn}({tk}) {close} {pstr}{vol}  [{d}]{_stale_tag(d)}")
                # ★V3.0 存进全局，供【持仓夜盘影响】用真实涨跌幅
                if pct is not None:
                    US_QUOTE[tk] = (float(pct), float(close), d)
                ok += 1
            else:
                w(f"    {cn}({tk}) [报空]")
            time.sleep(1)
        if ok == 0:
            raise RuntimeError("所有个股接口均失败")
        w(f"  （成功{ok}/{len(US_TICKERS)}只）")
    safe_run("美股个股", _do)


# ========== ★★V3.0 核心新增：持仓夜盘影响 ==========

def scan_holdings_impact():
    """把『美股涨了→A股哪个板块→我哪只票』这条链搬进代码。
    ★用【真实涨跌幅】不用【新闻情绪】：新闻极性是猜的，个股涨跌是事实。
    ★这是招商轮船(运油≠卖油)、卓胜微(手机≠存储)两次翻车的正面防线。"""
    w("\n" + "=" * 60)
    w("🎯🎯【持仓夜盘影响】今夜美股，直接点名你的票 🎯🎯")
    w("=" * 60)
    if not US_QUOTE:
        w("  ⚠️ 个股行情全失败 → 无法计算，本节跳过（不影响其它模块）")
        w("=" * 60)
        return

    w(f"  （基于{len(US_QUOTE)}只美股真实涨跌幅，非新闻情绪）\n")
    rows = []
    for code, name, chain, cost, stop, refs in MY_HOLDINGS:
        if not refs:
            w(f"  ◆ {name}({code}) ← {chain}")
            w(f"     今夜美股无对应标的，方向由A股自身驱动决定")
            w("")
            continue
        num = den = 0.0
        detail = []
        for tk, wt in refs:
            q = US_QUOTE.get(tk)
            if not q:
                continue
            pct = q[0]
            num += pct * wt
            den += wt
            nm = next((c for c, t in US_TICKERS if t == tk), tk)
            detail.append(f"{nm} {pct:+.2f}%")
        if den == 0:
            w(f"  ◆ {name}({code}) ← {chain}")
            w(f"     对应美股全部取价失败")
            w("")
            continue
        net = num / den
        if net >= 2:
            flag, act = "🔥🔥 强偏多", "明日可考虑加仓，但仍需过决策卡①-B"
        elif net >= 0.5:
            flag, act = "🔥 偏多", "持有，顺风"
        elif net <= -3:
            flag, act = "🔴🔴 强偏空", f"⚠️ 明日开盘留意，止损{stop}"
        elif net <= -1:
            flag, act = "❄️ 偏空", f"关注，止损{stop}"
        else:
            flag, act = "⚖️ 中性", "无明确方向"
        w(f"  ◆ {name}({code}) ← {chain}   {flag}  加权净{net:+.2f}%")
        w(f"     {' | '.join(detail)}")
        w(f"     → {act}")
        w("")
        rows.append((net, name, chain))

    if rows:
        rows.sort()
        w("  ── 排序 ──")
        w(f"  最偏空：{rows[0][1]}（{rows[0][0]:+.2f}%）")
        w(f"  最偏多：{rows[-1][1]}（{rows[-1][0]:+.2f}%）")
    w("\n  ⚠️ 铁律K：如果某只票【美股对标大跌但它明天高开】，")
    w("     这不是好消息也不是坏消息，是【反常】= 必须查清原因再动")
    w("  ⚠️ 铁律①-B：加权净值只说明『同链共振』，不等于驱动相同。")
    w("     买卖前仍须回答：它靠什么赚钱？今夜涨的那个原因跟它是同一个吗？")
    w("=" * 60)


# ========== 三、美股新闻 + 聪明钱专区 ==========

# ★美股→A股 板块映射（美股是A股的先行指标）
US_SECTOR_MAP = {
    "存储芯片→A股存储/长鑫链": ["美光", "Micron", "SK海力士", "海力士", "闪迪",
        "SanDisk", "西部数据", "希捷", "铠侠", "DRAM", "NAND", "HBM", "存储"],
    "半导体设备→A股北方华创/中微": ["应用材料", "拉姆", "Lam", "阿斯麦", "ASML",
        "KLA", "科天", "半导体设备", "光刻", "刻蚀"],
    "AI算力→A股紫光/中贝通信": ["英伟达", "NVIDIA", "AMD", "博通", "Broadcom",
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
    "贵金属→A股黄金": ["黄金", "金价", "纽蒙特", "巴里克", "央行购金", "白银"],
}

US_BULL = ["涨", "上调", "创新高", "超预期", "大增", "暴增", "增长", "回购",
           "订单", "扩产", "紧缺", "缺货", "涨价", "提价", "利好", "反弹",
           "看好", "买入", "跑赢", "翻倍", "强劲", "复苏", "突破"]
US_BEAR = ["跌", "下调", "暴跌", "重挫", "不及预期", "下滑", "减产", "裁员",
           "亏损", "砍单", "推迟", "取消", "调查", "制裁", "抛售", "去杠杆",
           "利空", "承压", "疲软", "警告", "泡沫", "回撤", "熊市"]


# ★★V3.2 极性反转短语：整体含义与其中的单字相反，必须先于单字匹配处理
POLARITY_TRAPS = {
    # 短语 → 真实极性 (1利多 / -1利空)
    "利空出尽": 1, "利空已充分": 1, "超跌反弹": 1, "跌幅收窄": 1,
    "跌势放缓": 1, "止跌回升": 1, "跌破前低后反弹": 1, "空头回补": 1,
    "好于预期": 1, "优于预期": 1, "降幅收窄": 1, "底部确认": 1,
    "利好出尽": -1, "利好兑现": -1, "涨势见顶": -1, "涨幅收窄": -1,
    "不及预期": -1, "低于预期": -1, "涨不动": -1, "冲高回落": -1,
}

# ★★V3.2 A股券商研报：这些是A股国内评论，不是美股信息，
# 放进"美股→A股映射"等于把A股观点绕一圈再当成美股先行指标，无信息增量
CN_BROKER = ["中信证券", "银河证券", "东吴证券", "方正证券", "光大证券",
             "中信建投", "国泰海通", "华泰证券", "招商证券", "国信证券",
             "申万宏源", "广发证券", "兴业证券", "中金公司", "十大机构论市"]


def _is_cn_report(t):
    return any(k in str(t) for k in CN_BROKER)


def _pol(t):
    """★V3.2：先处理反转短语，再数单字。
    『利空出尽』整体是利多，但含"利空"二字——旧版把它算成利空，
    直接把用户25%仓位的AI算力链错标为偏空。"""
    txt = str(t)
    b = r = 0
    for ph, poll in POLARITY_TRAPS.items():
        if ph in txt:
            if poll > 0:
                b += 2          # 反转短语权重高于单字
            else:
                r += 2
            txt = txt.replace(ph, "")   # 移除后不再参与单字计数
    b += sum(1 for x in US_BULL if x in txt)
    r += sum(1 for x in US_BEAR if x in txt)
    return 1 if b > r else (-1 if r > b else 0)


def scan_us_heat(uniq):
    """美股催化热力图 → 直接映射到A股对应板块
    ★V3.0：已从 scan_news 内剪出，由 main() 独立调用"""
    global TODAY_MAP_TOP3
    w("\n" + "=" * 60)
    w("🔥【美股催化热力图 → A股映射】美股是A股的先行指标")
    w("=" * 60)
    if not uniq:
        w("  ⚠️ 无新闻数据（新闻源全挂）→ 本节跳过")
        w("  ★但【持仓夜盘影响】用的是真实行情，不受影响，看上面那节")
        w("=" * 60)
        return
    src_n = len(uniq)
    uniq = [(tm, t) for tm, t in uniq if not _is_cn_report(t)]   # ★V3.2
    if src_n != len(uniq):
        w(f"  （已过滤{src_n-len(uniq)}条A股券商研报：那是A股观点，不是美股先行信息）")
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
        w("=" * 60)
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
    w("  ⚠️ 提醒：本排行的准确率见下方【映射回测】，没验证过的规则不许当依据")

    # ★V3.0 存档，供次日回测
    TODAY_MAP_TOP3 = [(s, len(b) - len(e)) for s, (b, e) in ranked[:3]]
    try:
        d = _bt_load(US_MAP_HIST_FILE)
        d[now_beijing().strftime("%Y-%m-%d")] = {
            "top3": [{"sect": s, "net": n} for s, n in TODAY_MAP_TOP3],
            "bottom": [{"sect": s, "net": len(b) - len(e)}
                       for s, (b, e) in ranked[-2:]],
        }
        _bt_save(US_MAP_HIST_FILE, d)
        w(f"  📌 已存档今夜前3 → 次日A股收盘后自动回看")
    except Exception:
        pass
    w("=" * 60)


def backtest_us_map():
    """★V3.0 映射回测：昨夜说的『次日A股跟涨』，到底跟了没有
    A股板块涨跌需 A股扫描器提供，这里先做【天数与样本积累】+ 人工对照清单"""
    w("\n" + "=" * 60)
    w("🔬【美股→A股映射·回测】这条规则准不准，机器说了算")
    w("=" * 60)
    d = _bt_load(US_MAP_HIST_FILE)
    if not d:
        w("  尚无存档，今夜是第1天。")
        w("  ⚠️ 铁律：累计≥5天且≥15样本后出胜率；连续<45% → 立即停用此映射")
        w("=" * 60)
        return
    days = sorted(d.keys(), reverse=True)
    w(f"  已积累 {len(days)} 天 / {sum(len(v.get('top3', [])) for v in d.values())} 个样本")
    w("\n  ── 最近5夜的前3预测（次日请对照A股板块榜自查）──")
    for day in days[:5]:
        t3 = d[day].get("top3", [])
        if t3:
            w(f"  {day}：" + " ｜ ".join(f"{x['sect'].split('→')[0]}(净{x['net']:+d})"
                                        for x in t3))
    w("\n  ⚠️ 对照方法：次日A股盘后扫描器的【板块全景榜】，")
    w("     看这3个板块在不在当日涨幅前20。在=命中。")
    w("  ⚠️ 满5天后把命中结果写进 scanner_cloud 的规则记分卡，一起管理")
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
        return []          # ★V3.0：返回空表而非裸 return，后续模块照常跑

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

    return uniq            # ★V3.0：交给 main() 分发，不再自己调用热力图


# ========== 主程序 ==========

def main():
    bj = now_beijing()
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][bj.weekday()]

    w("=" * 60)
    w(f"美股夜盘扫描器V3.3 | 北京 {bj.strftime('%Y-%m-%d %H:%M')} {weekday} | 美股收盘后")
    w("=" * 60)
    w("★错题㉑：周五收盘 = 周一方向已定，别等周一早上才跑")
    w("★数据带 ⚠️距今N天 标记的，是陈旧数据，不许当成今夜的")

    scan_index()
    scan_stocks()

    # ★★V3.0：持仓穿透用【真实行情】，排在新闻之前，新闻挂了也照跑★★
    safe_run("持仓夜盘影响", scan_holdings_impact)

    uniq = []
    try:
        uniq = scan_news() or []
    except Exception as e:
        w(f"  [报空] 新闻模块：{type(e).__name__}")

    # ★★V3.0：热力图与回测独立运行，不再被新闻源成败绑架★★
    safe_run("美股催化热力图", lambda: scan_us_heat(uniq))
    safe_run("映射回测", backtest_us_map)

    w("\n" + "=" * 60)
    w("★★★【明日A股开盘参考】★★★")
    w("  数据在上，具体操作由AI结合你的持仓在对话中给出。")
    w("  核心看点：①🎯持仓夜盘影响（V3.0新增，直接点名你的票）")
    w("           ②费城半导体SOX → A股半导体/芯片")
    w("           ③英伟达/美光/存储链 → A股算力/存储/CPO/PCB")
    w("           ④美联储/CPI → 成长股整体估值")
    w("           ⑤油价/黄金 → A股资源链")
    w("           ⑥💰聪明钱专区 → 巴菲特等大佬持仓/表态（13F披露日重点看）")
    w("\n  ⚠️ 买卖后，MY_HOLDINGS 与 scanner_cloud 的 WATCH_STOCKS 必须同步改")
    w("=" * 60)

    os.makedirs("reports", exist_ok=True)
    text = "\n".join(REPORT)
    date = bj.strftime("%Y%m%d")
    for p in [f"reports/美股_最新.txt", f"reports/美股_{date}.txt"]:
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    print("\n✅ 美股扫描V3.3完成 reports/美股_最新.txt")


if __name__ == "__main__":
    main()

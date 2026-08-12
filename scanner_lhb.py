# -*- coding: utf-8 -*-
"""
龙虎榜/游资 独立扫描器 V3.3（2026-08-10 账户改读 我的清单.txt，不再写死）
专职：每晚18:45跑，抓当日龙虎榜 + 活跃营业部 + 机构专用席位
核心：自动标注【埋伏型】(跌着被买=明天机会) / 【追高型】(涨停被买=次日易崩)

V3.2 新增（8/10 用户截图当场验出的错误信号）：
  ★★机构净买 ≠ 龙虎榜净买，只报前者会得出完全相反的结论★★
     实例：多氟多(002407) 8/7
        扫描器报「机构净买 3.26亿，全场最大」→ 排下单指令第1位
        同花顺实际显示「08-07入选，龙虎榜净买入 −1475万元」
     两个数都对：机构席位确实买了3.26亿，但游资卖得更多，
     全榜合计是【净卖出】。只看机构那一栏 = 把出货看成建仓。
     修法：scan_lhb 建立 {代码: 龙虎榜净买额} 映射，
          scan_jg 逐只交叉校验，符号相反 → 🔴标冲突 → 逐出下单指令。
  ⚠️ 同时收紧：机构净买信号只在【当日下跌】时才算埋伏（铁律I）。
     多氟多8/7是涨1.25%收的，本就不满足"机构在跌的票上砸钱"。

V3.1 新增（V3.0跑出来之后发现的真问题）：
  0. 🔴🔴合理性校验：8/7实测 益坤电气(北交所小票) 机构净买「54.54亿」排全场第一，
     但同日龙虎榜明细净买最大的中国稀土只有6.32亿，且用户台账记录当日
     全场最大是多氟多3.26亿 —— 三重矛盾，该数为脏数据/单位错乱。
     旧版把它排在下单指令第1位。数值荒谬时，怎么换算都是错的，
     必须有独立于换算的【常识上限】。超限→标🔴可疑→逐出下单指令。
  0b.新股过滤：展芯股份+396.89%(上市首日无涨跌幅限制)被误判为「追高型(涨停20%)」。
     上榜原因含「无价格涨跌幅限制」或涨幅>50% → 按新股处理，不参与埋伏/追高判定。

V3.0 六项修复（按危险程度排）：
  1. 🔴单位事故：旧版用「整列最大值>1e6」判断单位，全场净买额偏小的那天
     不会除1e8，5000万会被当成「5000万亿」直接触发下单指令。改逐值归一化。
  2. 🔴埋伏池静默失效：净买额列缺失时(新浪源没有该列) net=None，
     旧版 gen_order 全部 continue → 永远不出指令，且不报错。现在明确报出原因。
  3. 🔴下单指令无闸门：旧版只要「净买≥1亿且涨幅<3%」就给买点+仓位+止损，
     不查板块顺逆风、不查①-B驱动链、不查与现有持仓集中度、不查可用现金。
     铁律H(必须给标的)和铁律L(必须答驱动)在用户系统里是并存的，代码只实现了H。
     V3.0 保留指令，但每条附【必答闸门】，未答完不构成可执行指令。
  4. 🔴涨停判定错：旧版 pct>=9.8 才算追高型，漏掉创业板/科创板20cm。
     300/301/688/689 开头按 19.8% 判，北交所 30%。
  5. 机构席位「代码」列缺失时静默吞掉全部数据 → 现在显式报出。
  6. 新增 order_history.json：下单指令存档 + 3日回测。
     旧版转化率0%被反复检讨，但从没验证过「转化了会不会赚」——这是缺失的另一半。

输出：reports/龙虎榜_最新.txt + reports/龙虎榜_日期.txt
与A股/美股扫描器完全独立，互不影响
"""
import os, json, time, signal, datetime
import akshare as ak
import pandas as pd

REPORT = []
ORDER_HIST_FILE = "reports/order_history.json"
INST_HIST_FILE = "reports/institution_history.json"   # ★V3.4 机构成绩单

# ★★V3.2 全局：{代码: 龙虎榜净买额(亿)}，由 scan_lhb 填充，scan_jg 交叉校验用
# key "_date" 存数据日期，用于确认两份数据是同一天
LHB_NET_MAP = {}
# ★★V3.5 {代码: 当日收盘价}。数据源就在龙虎榜明细里，
# 不必再去调 spot 快照——8/11实测18:01快照挂了，11条记录全丢价格。
LHB_CLOSE_MAP = {}

# ★★V3.3：账户与持仓改为从 我的清单.txt 读取，不再写死★★
# 8/10实测：报告显示"可用现金286元"，实际已是8,133元——
# scanner_cloud 接了清单，scanner_lhb 没接，两份数据打架。
# 这就是"同一份持仓抄三份"的必然后果：改一处，另两处就变成假数据。
WATCH_FILE = "我的清单.txt"
TOTAL_ASSET_WAN = 18.48     # 缺省值；清单存在时被覆盖
CASH_AVAIL_WAN = 0.81       # ★可用现金(万) → 决定指令能不能真的执行
SINGLE_MAX_PCT = 11         # 单笔上限占总资产%

# ★现有持仓驱动链（查集中度用）。缺省值仅作兜底，
# 清单存在时由 _load_account() 从 我的清单.txt 重算。
MY_CHAINS = {}


def _load_account():
    """★★V3.3 从 我的清单.txt 读取账户与驱动链集中度★★
    格式与 scanner_cloud 完全一致（| 分隔），改一个文件三处生效。"""
    global TOTAL_ASSET_WAN, CASH_AVAIL_WAN, MY_CHAINS
    if not os.path.exists(WATCH_FILE):
        w(f"  ⚠️ 未找到 {WATCH_FILE}，账户数字用代码内缺省值（可能已过期）")
        return
    try:
        chains, acct = {}, {}
        with open(WATCH_FILE, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                p = [x.strip() for x in line.split("|")]
                if len(p) < 3:
                    continue
                if p[0] in ("账户", "account"):
                    try:
                        acct[p[1]] = float(p[2])
                    except Exception:
                        pass
                elif p[0] == "持仓" and len(p) > 7:
                    try:
                        mv = float(p[4]) if p[4] else 0.0
                    except Exception:
                        mv = 0.0
                    ch = p[7] or "未分类"
                    if mv > 0:
                        chains[ch] = chains.get(ch, 0.0) + mv
        if acct.get("总资产"):
            TOTAL_ASSET_WAN = acct["总资产"]
        if acct.get("现金") is not None:
            CASH_AVAIL_WAN = acct["现金"]
        if chains:
            MY_CHAINS = chains
        w(f"  ✅ 已从 {WATCH_FILE} 载入：总资产{TOTAL_ASSET_WAN}万 / "
          f"现金{CASH_AVAIL_WAN}万 / 驱动链{len(MY_CHAINS)}条")
    except Exception as e:
        w(f"  🔴 {WATCH_FILE} 解析失败：{type(e).__name__} → 用缺省值")
CHAIN_MAX_PCT = 40          # 铁律⑧：同一驱动链不许超40%

# ★★V3.1 合理性上限（亿元）。超过即判为脏数据，不参与下单指令。
# 依据：A股单只个股单日龙虎榜净买额历史极值约20亿量级；
#      单个营业部单日净买额极值约20亿量级。超出即为单位错乱或源数据错误。
SANE_MAX_STOCK_YI = 20.0
SANE_MAX_SEAT_YI = 20.0

# ★高价股→可买ETF（一手>总资产10%就给ETF，不许说"买不起"）
HIGH_PRICE_ETF = {
    "中际旭创": "通信ETF 515880 / 光模块ETF 159516",
    "新易盛": "通信ETF 515880 / 光模块ETF 159516",
    "天孚通信": "通信ETF 515880",
    "寒武纪": "科创芯片ETF 588200",
    "海光信息": "科创芯片ETF 588200",
    "北方华创": "半导体设备ETF 561980",
    "中微公司": "半导体设备ETF 561980",
    "长鑫科技": "科创芯片ETF 588200",
    "生益科技": "电子ETF 515260",
    "药明康德": "创新药ETF 516080",
    "德明利": "科创芯片ETF 588200",
    "江波龙": "科创芯片ETF 588200",
}


def now_beijing():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=8)


def w(line=""):
    print(line)
    REPORT.append(str(line))


def pick_col(df, kws):
    for kw in kws:
        for c in df.columns:
            if kw in str(c):
                return c
    return None


class CallTimeout(Exception):
    pass


def _alarm(s, f):
    raise CallTimeout("超时")


def with_retry(fn, tries=3, wait=5, timeout=90):
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


def multi_source(title, sources):
    for name, fn in sources:
        try:
            r = with_retry(fn)
            if r is not None and len(r) > 0:
                return name, r
        except Exception as e:
            w(f"  [切换] {title}·{name}失败({type(e).__name__})")
    return None, None


def _try_dates(max_back=7):
    """从今天往前找，返回候选日期列表(YYYYMMDD)，跳过周末"""
    out = []
    d = now_beijing()
    for _ in range(max_back):
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d -= datetime.timedelta(days=1)
    return out


def _to_yi(v):
    """★★V3.0 单位归一化：任何金额 → 亿元。逐值判断，不看整列最大值。

    🔴旧版事故：if 整列max>1e6: 全列/1e8
       全场净买都偏小的那天(比如max=8e5)，条件不成立 → 不做换算 →
       某只票净买 5,000,000 元 会被当成 5,000,000 亿，直接冲破 amt>=1.0 闸门，
       生成一条「净买500万亿」的下单指令。这是能真花钱的bug。
    A股单只个股龙虎榜净买额区间约 1e5 ~ 5e9 元，绝无可能达到 1e5 亿，
    因此按数量级判断是安全的。"""
    try:
        x = float(v)
    except Exception:
        return None
    if pd.isna(x):
        return None
    ax = abs(x)
    if ax == 0:
        return 0.0
    if ax >= 1e6:          # ≥100万 → 原始单位是「元」
        return round(x / 1e8, 4)
    if ax >= 1e3:          # 1千~100万 → 原始单位大概率是「万元」
        return round(x / 1e4, 4)
    return round(x, 4)     # <1000 → 已经是「亿元」


def _suspect(v, cap, what=""):
    """★V3.1 合理性校验：返回 (是否可疑, 提示文本)
    换算正确 ≠ 数值正确。源数据本身错乱时，唯一的防线是常识上限。"""
    if v is None or pd.isna(v):
        return False, ""
    if abs(float(v)) > cap:
        return True, f" 🔴可疑(>{cap:.0f}亿，超出{what}常识上限，已逐出下单指令)"
    return False, ""


def _is_newstock(pct, reason=""):
    """★V3.1 新股/无涨跌幅限制识别：不参与埋伏型/追高型判定"""
    if reason and ("无价格涨跌幅限制" in str(reason) or "无涨跌幅" in str(reason)):
        return True
    try:
        if pct is not None and pd.notna(pct) and abs(float(pct)) > 50:
            return True
    except Exception:
        pass
    return False


def _limit_pct(code):
    """★V3.0 按板块返回涨停幅度：主板10%、双创20%、北交所30%"""
    c = str(code)[-6:]
    if c.startswith(("300", "301", "688", "689")):
        return 19.8
    if c.startswith(("43", "83", "87", "92")):
        return 29.5
    return 9.8


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


# ========== 一、龙虎榜（埋伏型 vs 追高型） ==========

def scan_lhb():
    w("\n【一、龙虎榜·个股】自动标注 埋伏型/追高型")
    src, df, use_date = None, None, None
    for d in _try_dates(7):
        src, df = multi_source(f"龙虎榜({d})", [
            ("东财明细", lambda dd=d: ak.stock_lhb_detail_em(start_date=dd, end_date=dd)),
            ("东财机构", lambda dd=d: ak.stock_lhb_jgmmtj_em(start_date=dd, end_date=dd)),
            ("新浪偏离7", lambda dd=d: ak.stock_lhb_detail_daily_sina(
                date=dd, symbol="涨幅偏离值达7%的证券")),
        ])
        if df is not None and len(df) > 0:
            use_date = d
            break
        w(f"  {d} 无数据，往前回溯...")
    if df is None or len(df) == 0:
        w("  [报空] 近7个交易日均无龙虎榜数据（接口异常）")
        return [], []
    w(f"  ✅ 命中数据日期：{use_date}")
    LHB_NET_MAP.clear()
    LHB_CLOSE_MAP.clear()
    LHB_NET_MAP["_date"] = use_date
    if use_date != now_beijing().strftime("%Y%m%d"):
        w(f"  ⚠️ 注意：这是【{use_date}】的龙虎榜，不是今天的。")
        w("     今日龙虎榜18:35后发布，届时重跑可得最新。")

    c_name = pick_col(df, ["名称", "股票简称", "简称"])
    c_code = pick_col(df, ["代码", "股票代码"])
    c_pct = pick_col(df, ["涨跌幅", "涨跌幅度", "收盘涨跌幅"])
    c_net = pick_col(df, ["净买额", "龙虎榜净买额", "机构买入净额", "净额"])
    c_reason = pick_col(df, ["上榜原因", "解读", "指标"])
    c_close = pick_col(df, ["收盘价", "收盘", "最新价"])   # ★V3.5
    if not c_name:
        w(f"  [报空] 缺名称列，源={src} 实际列名={list(df.columns)[:12]}")
        return [], []

    # ★V3.0：列缺失显式报出，不再静默导致下游空转
    if not c_net:
        w(f"  🔴 本源【无净买额列】(源={src}) → 埋伏池无金额，")
        w("     下单指令的『≥1亿』闸门无法判定，本次不会产生指令。")
        w(f"     实际列名：{list(df.columns)[:12]}")
    if not c_pct:
        w(f"  🔴 本源【无涨跌幅列】→ 无法区分埋伏型/追高型")

    df = df.copy()
    if c_net:
        df["_net_yi"] = df[c_net].apply(_to_yi)      # ★逐值归一化，不用整列max
        # ★★V3.2 建立 {代码: 龙虎榜净买额} 映射，供 scan_jg 交叉校验★★
        # 同一票可能多行(不同上榜原因)，取绝对值最大的那条作为主口径
        if c_code:
            for _, rr in df.iterrows():
                try:
                    cc = str(rr[c_code])[-6:]
                    # ★V3.5 顺手把收盘价存下来，供机构成绩单结算
                    if c_close and cc:
                        _v = pd.to_numeric(rr[c_close], errors="coerce")
                        if pd.notna(_v) and float(_v) > 0:
                            LHB_CLOSE_MAP[cc] = float(_v)
                    vv2 = rr.get("_net_yi")
                    if cc and vv2 is not None and pd.notna(vv2):
                        old = LHB_NET_MAP.get(cc)
                        if old is None or abs(float(vv2)) > abs(float(old)):
                            LHB_NET_MAP[cc] = float(vv2)
                except Exception:
                    continue
            w(f"  📌 已建立龙虎榜净买额映射 {len(LHB_NET_MAP)-1} 只 → 供机构席位交叉校验")
        df = df.sort_values("_net_yi", ascending=False, na_position="last")
    if c_pct:
        df[c_pct] = pd.to_numeric(df[c_pct], errors="coerce")

    w(f"  （源：{src}，共{len(df)}条）")
    ambush, chase = [], []
    seen = set()
    for _, r in df.head(25).iterrows():
        nm = str(r[c_name])
        code = str(r[c_code])[-6:] if c_code else ""
        if code and code in seen:
            continue          # ★V3.0 同一票多营业部多行，去重
        if code:
            seen.add(code)
        pct = r[c_pct] if c_pct else None
        net = r.get("_net_yi") if c_net else None
        rs = str(r[c_reason])[:24] if c_reason else ""
        bad, badtxt = _suspect(net, SANE_MAX_STOCK_YI, "个股单日净买")
        tag = ""
        if _is_newstock(pct, rs):
            tag = "🆕新股/无涨跌幅限制(不判埋伏追高)"
        elif pct is not None and pd.notna(pct):
            lim = _limit_pct(code)
            if pct < 0:
                tag = "✅埋伏型"
                if not bad and (net is None or (pd.notna(net) and net > 0)):
                    ambush.append((nm, code, float(pct), net))
            elif pct >= lim:
                tag = f"⚠️追高型(涨停{lim:.0f}%)"
                chase.append((nm, code, float(pct), net))
            else:
                tag = "中性"
        p = f" {pct:+.2f}%" if pct is not None and pd.notna(pct) else ""
        n = f" 净买{net:.2f}亿" if net is not None and pd.notna(net) else ""
        w(f"    {nm}({code}){p}{n}{badtxt} {tag} {rs}")

    w("")
    w("  ★★★【埋伏池】游资在『当天下跌』的票上砸钱 = 明天最可能启动 ★★★")
    if ambush:
        for nm, code, pct, net in ambush[:12]:
            n = f" 净买{net:.2f}亿" if net is not None and pd.notna(net) else " (无金额数据)"
            w(f"    🎯 {nm}({code}) 今{pct:+.2f}%{n}")
        w(f"    ※ 共{len(ambush)}只。次日验证：所属板块是否启动、是否放量。")
    else:
        w("    今日无『跌着被买』标的 → 全场追涨接力，次日谨慎")
    if chase:
        w(f"  ⚠️ 追高型{len(chase)}只（涨停被买，次日易炸板）：" +
          "、".join(n for n, _, _, _ in chase[:10]))
    return ambush, chase


# ========== 二、游资席位 ==========

def scan_hot_money():
    w("\n【二、游资席位·活跃营业部】谁在扫货")
    src, df, use_date = None, None, None
    for d in _try_dates(7):
        try:
            r = with_retry(lambda dd=d: ak.stock_lhb_hyyyb_em(start_date=dd, end_date=dd),
                           tries=2, wait=4, timeout=60)
            if r is not None and len(r) > 0:
                src, df, use_date = "东财活跃营业部", r, d
                break
        except Exception:
            pass
    if df is None:
        src, df = multi_source("游资席位(备)", [
            ("东财机构统计", lambda: ak.stock_lhb_jgstatistic_em(symbol="近一月")),
            ("新浪营业部", lambda: ak.stock_lhb_yytj_sina(symbol="近一月")),
        ])
    if df is None or len(df) == 0:
        w("  [报空] 全部数据源失败")
        return
    if use_date:
        w(f"  ✅ 数据日期：{use_date}")
    c_name = pick_col(df, ["营业部名称", "营业部", "机构名称"])
    c_net = pick_col(df, ["总买卖净额", "净额", "净买", "买入总金额"])
    c_stock = pick_col(df, ["买入股票", "买入个股"])
    if not c_name:
        w(f"  [报空] 缺营业部列，源={src} 列名={list(df.columns)[:12]}")
        return
    df = df.copy()
    if c_net:
        df["_net_yi"] = df[c_net].apply(_to_yi)      # ★同样逐值归一化
        df = df.sort_values("_net_yi", ascending=False, na_position="last")
    w(f"  ◆ 净买入前12（源：{src}）：")
    n_bad = 0
    for _, r in df.head(12).iterrows():
        v = r.get("_net_yi") if c_net else None
        bad, badtxt = _suspect(v, SANE_MAX_SEAT_YI, "单营业部单日净买")
        if bad:
            n_bad += 1
        n = f" 净{v:.2f}亿" if v is not None and pd.notna(v) else ""
        s = f" 主买:{str(r[c_stock])[:70]}" if c_stock else ""
        w(f"    {r[c_name]}{n}{badtxt}{s}")
    if n_bad:
        w(f"  🔴 本次有{n_bad}条超出常识上限 → 该源今日金额字段不可信，只看『主买了谁』，不看金额")
    w("  ※ 判读：席位集中买『当天在跌』的=埋伏，次日看启动；")
    w("    集中买『当天涨停』的=追高接力，次日易崩。")


# ========== 三、机构专用席位 ==========

def scan_jg():
    """返回 [(名称, 涨跌幅, 机构净买亿, 代码), ...] 供下单指令使用"""
    w("\n【三、机构专用席位】（机构才是真钱，游资是快钱）")
    out = []
    df, use_date = None, None
    for d in _try_dates(7):
        try:
            r = with_retry(lambda dd=d: ak.stock_lhb_jgmmtj_em(start_date=dd, end_date=dd),
                           tries=1, wait=3, timeout=60)
            if r is not None and len(r) > 0:
                df, use_date = r, d
                break
        except Exception:
            continue
    if df is None or len(df) == 0:
        w("  近7交易日无机构上榜数据")
        return out              # ★V3.0：返回空表而非 None
    try:
        w(f"  ✅ 数据日期：{use_date}")
        c_name = pick_col(df, ["名称", "简称"])
        c_pct = pick_col(df, ["涨跌幅"])
        c_net = pick_col(df, ["机构买入净额", "净额"])
        c_code = pick_col(df, ["代码"])          # ★V3.0：循环外取一次
        if not c_code:
            w(f"  🔴 本源【无代码列】→ 下单指令将缺代码。列名：{list(df.columns)[:12]}")
        df = df.copy()
        if c_net:
            df["_net_yi"] = df[c_net].apply(_to_yi)
            df = df.sort_values("_net_yi", ascending=False, na_position="last")
        _blocked = []          # ★V3.6 被闸门拦下的票，仍要进成绩单以便验证闸门
        map_date = LHB_NET_MAP.get("_date")
        same_day = (map_date == use_date) and len(LHB_NET_MAP) > 1
        if same_day:
            w(f"  ✅ 已启用【龙虎榜净买额】交叉校验（同为{use_date}的数据）")
        else:
            w("  ⚠️ 无法交叉校验（龙虎榜明细缺失或日期不一致）")
            w("     → 本次机构净买额只能单独看，8/7多氟多式的误判风险存在")

        n_conflict = 0
        for _, r in df.head(15).iterrows():
            nm = str(r[c_name]) if c_name else ""
            vv = pd.to_numeric(r[c_pct], errors="coerce") if c_pct else None
            amt_y = r.get("_net_yi") if c_net else None
            cdd = str(r[c_code])[-6:] if c_code else ""
            p = f" {vv:+.2f}%" if vv is not None and pd.notna(vv) else ""
            n = f" 机构净买{amt_y:.2f}亿" if amt_y is not None and pd.notna(amt_y) else ""
            bad, badtxt = _suspect(amt_y, SANE_MAX_STOCK_YI, "个股单日机构净买")

            # ★★V3.2 交叉校验：机构净买为正，但全榜净买为负 = 机构在接，游资在出★★
            conflict = False
            xtxt = ""
            lhb_net = LHB_NET_MAP.get(cdd) if same_day else None
            if lhb_net is not None and amt_y is not None and pd.notna(amt_y):
                xtxt = f" ｜龙虎榜全榜净买{lhb_net:+.2f}亿"
                if amt_y > 0 and lhb_net < 0:
                    conflict = True
                    n_conflict += 1
                    xtxt += " 🔴符号相反(机构在接·游资在出)→逐出下单指令"
                elif amt_y > 0 and lhb_net > 0:
                    xtxt += " ✅方向一致"

            flag = ""
            if not bad and not conflict and vv is not None and pd.notna(vv):
                if vv < 0:
                    flag = " ✅机构在跌时买入=重要埋伏信号"
                elif vv < 3:
                    # ★V3.2 收紧：铁律I原文是"机构在【跌】的票上砸钱"，
                    #   微涨被买只能算参考，不再直接称"真建仓"
                    flag = " ⚠️微涨被机构买入=参考级(非埋伏，铁律I只认跌着被买)"
            w(f"    {nm}({cdd}){p}{n}{xtxt}{badtxt}{flag}")
            # ★★V3.6：被拦下的票【也要进机构成绩单】★★
            # 8/12实测：成绩单里『符号相反』一组永远是空的，
            #   因为 conflict 的票被 continue 掉了，根本没进存档。
            # ★后果：我拦下的票永远不会被记录，也就永远无法证明
            #   我拦对了还是拦错了 —— 一个无法被证伪的闸门 = 信仰不是规则。
            # 今天就拦了4只(百花医药3.89亿/ST威领2.84亿/万邦医药/新大洲A)，
            # 如果它们明天大涨，说明闸门是错的，但我看不到。
            # 修法：conflict/bad 的票照样存档(agree=False)，只是不进下单指令。
            if bad or conflict:
                _blocked.append((nm, cdd,
                                 float(vv) if vv is not None and pd.notna(vv) else None,
                                 float(amt_y) if amt_y is not None and pd.notna(amt_y) else None,
                                 (False if conflict else None)))
                continue          # ★可疑值/冲突值不进下单指令，但已存档
            out.append((nm,
                        float(vv) if vv is not None and pd.notna(vv) else None,
                        float(amt_y) if amt_y is not None and pd.notna(amt_y) else None,
                        cdd))
        # ★★★V3.4 机构成绩单：把机构每天买了什么全存下来，一段时间后算它准不准★★★
        # 用户提问："机构为啥要接盘？不想赚钱吗？" —— 这个问题问对了。
        # "机构接盘"是我用词偷懒。真实可能有五种：
        #   ①时间尺度不同(游资做3天/机构做3月，同一价格含义相反)
        #   ②被动买入(指数纳入/ETF申购，不含判断)
        #   ③机构也会错(中贝5/15主力净流入1.8亿，今天跌39%)
        #   ④大资金买不了涨停，建仓天生就得买在下跌里 = 常态非异常
        #   ⑤义务性买单(定增/解禁/做市对冲)
        # ★这五种事前分不清，只能靠事后统计。所以要这张表。
        try:
            # ★★V3.5：收盘价直接取自【龙虎榜明细自带的收盘价列】★★
            # 8/11教训：我舍近求远去调 spot 快照，18:01接口挂了，
            #   11条记录全部 price=None → 这批数据永远算不出涨跌 = 白存。
            # 而收盘价本来就在龙虎榜那张表里，零额外网络调用。
            def _close(cd):
                return LHB_CLOSE_MAP.get(cd)

            _arch = []
            # ★V3.6：out(放行) + _blocked(拦下) 一起存，才能对比闸门有没有用
            for _r in list(out) + [(x[0], x[2], x[3], x[1], x[4]) for x in _blocked]:
                _nm, _pct, _amt, _cd = _r[0], _r[1], _r[2], _r[3]
                _forced_agree = _r[4] if len(_r) > 4 else None
                if not _cd or _amt is None:
                    continue
                _p0 = _close(_cd)
                if not _p0:
                    continue          # ★V3.5 没价格就不存，废数据比没数据更坏
                _lhb = LHB_NET_MAP.get(_cd)
                _arch.append({
                    "code": _cd, "name": _nm,
                    "pct": _pct if _pct is not None else 0.0,
                    "inst": round(float(_amt), 3),
                    "lhb": (round(float(_lhb), 3) if _lhb is not None else None),
                    # 分类：机构买【跌】的 vs 买【涨停】的 —— 这是要对比的两组
                    "price": _p0,   # ★V3.5 当日收盘价（取自龙虎榜明细）
                    "kind": ("买跌" if (_pct is not None and _pct < 0)
                             else ("买涨停" if (_pct is not None and _pct >= 9.5)
                                   else "买微涨")),
                    "agree": (_forced_agree if _forced_agree is not None
                              else (None if _lhb is None else (_amt > 0 and _lhb > 0))),
                    "blocked": _forced_agree is False,
                })
            if _arch:
                _d = _bt_load(INST_HIST_FILE)
                _d[use_date] = _arch
                _bt_save(INST_HIST_FILE, _d)
                w(f"  📊 已记入【机构成绩单】{len(_arch)}只 → 累计追踪机构对错")
        except Exception as _e:
            w(f"  [机构成绩单存档失败] {type(_e).__name__}")

        if n_conflict:
            w(f"\n  🔴 本次拦下 {n_conflict} 只【机构买但全榜净卖】的票")
            w("     这类票看起来是机构建仓，实际是机构接盘游资出货。")
            w("     8/7多氟多就是这一类：机构净买3.26亿，全榜净买−0.15亿。")
        return out
    except Exception as e:
        w(f"  [报空] 机构席位：{type(e).__name__}: {str(e)[:60]}")
    return out


# ========== 四、下单指令（带闸门） ==========

def gen_order(ambush, jg_rows=None):
    """★把埋伏信号变成可执行的买点+止损+仓位（治转化率0%）
    ★V3.0：保留铁律H(必须给标的)，同时补上铁律L(必须答驱动)与⑧(集中度)。
      旧版只实现了H，等于把『敢不敢买』的问题解决了，
      却把『该不该买』的问题留空 —— 卓胜微/券商两次翻车正是死在这一格。"""
    w("\n" + "=" * 60)
    w("🔫🔫【下单指令】机构在跌的票砸钱 = 直接给买点，不许说观察 🔫🔫")
    w("=" * 60)
    w("  ★铁律H：识别到机构埋伏 = 必须当场给可执行标的★")
    w("  ★触发：①跌着被买≥1亿  ②微涨<3%但机构净买≥1亿")
    w("  ★历史转化率0%：7/28中际旭创(后+19.6%)、7/30长电科技、8/3德明利")
    w("    三次识别全对，三次都只说『观察』→ 全部错过")

    w("  ★V3.1：超出常识上限的金额已在上游逐出（8/7益坤电气54.54亿即此类）")
    w("  ★V3.2：机构净买为正但【龙虎榜全榜净买为负】的，已逐出（8/7多氟多即此类）")
    w("     ⚠️ 铁律I原文：只认『机构专用席位买【跌】的票』。")
    w("        微涨被机构买 = 参考级，不构成埋伏信号。")

    orders = []
    seen_code = set()
    no_amt = 0
    for item in (ambush or []):
        try:
            nm, cd, pct, net = item[0], item[1], item[2], item[3]
        except Exception:
            continue
        amt = float(net) if net is not None and pd.notna(net) else None
        if amt is None:
            no_amt += 1
            continue
        if amt < 1.0 or (pct is not None and pct >= 0):
            continue
        orders.append((amt, nm, cd, pct, "跌着被买"))
        if cd:
            seen_code.add(cd)

    for r in (jg_rows or []):
        try:
            nm, pct, amt, cd = r[0], r[1], r[2], (r[3] if len(r) > 3 else "")
        except Exception:
            continue
        if amt is None or amt < 1.0:
            continue
        if pct is None or pct >= 3.0:
            continue
        if cd and cd in seen_code:
            continue
        orders.append((amt, nm, cd, pct, "微涨被机构重金买入"))
        if cd:
            seen_code.add(cd)

    if no_amt:
        w(f"\n  🔴 埋伏池有{no_amt}只【无净买额数据】被跳过（数据源缺该列）")
        w("     这不是『今天没信号』，是『今天测不出信号』，两者不可混为一谈。")

    if not orders:
        w("\n  今日无【机构/游资在跌的票上净买≥1亿】的标的")
        w("  → 明确结论：今晚不产生下单指令（不硬凑，铁律D）")
        w("=" * 60)
        return
    orders.sort(key=lambda x: -x[0])

    # ★★V3.0 现金约束：指令必须是真能执行的，否则只是纸上谈兵★★
    want_wan = TOTAL_ASSET_WAN * SINGLE_MAX_PCT / 100
    cash_ok = CASH_AVAIL_WAN >= want_wan
    w(f"\n  💰 可用现金 {CASH_AVAIL_WAN*10000:,.0f}元 / 单笔需 {want_wan*10000:,.0f}元 "
      f"→ {'✅够' if cash_ok else '🔴不够'}")
    if not cash_ok:
        w("  🔴 现金不足，下列指令【无法直接执行】。")
        w("     要执行必须先卖出一笔 → 卖出前必须过【卖出卡】：")
        w("     查台账里写死的『逻辑破定义』，破了才准卖，不许因为想买新的而卖旧的。")
        w("     ⚠️ 『为了买A而卖B』是最常见的亏损来源：A是新鲜感，B是已验证的仓位。")

    w(f"\n  ★★今日触发下单条件 {len(orders)} 只 —— 逐个给指令★★\n")
    archive = []
    for i, (amt, nm, cd, pct, why) in enumerate(orders[:5], 1):
        etf = None
        for k, v in HIGH_PRICE_ETF.items():
            if k in nm:
                etf = v
                break
        w(f"  ══════ 指令{i}：{nm}({cd}) ══════")
        w(f"    信号：今日{pct:+.2f}% 被净买 {amt:.2f}亿（{why}=埋伏型）")
        if etf:
            w(f"    ⚠️ 股价高，一手可能>总资产10% → ★改买ETF：{etf}★")
            w("       （铁律H②：个股太贵就给ETF，不许说买不起）")
        else:
            w(f"    🎯 标的：{nm}({cd})")
        w("    ─────────────────────────")
        w("    【买点】次日开盘不追高：")
        w("      · 低开或平开 → 直接买")
        w("      · 高开>5% → 等回踩到分时均价")
        w("      · 高开>9% → 放弃，改等第2个回踩日")
        w(f"    【仓位】{want_wan:.1f}万（总资产{SINGLE_MAX_PCT}%，单笔上限）"
          + ("" if cash_ok else "  🔴现金不足，需先卖出"))
        w("    【止损】-12%（机构建仓要时间，给足空间）")
        w("    【类型】B类周期仓，最少持有3个交易日")
        w("      ★铁律H④：信号次日若下跌，不算信号错，不许当天砍")
        w("    【兑现】+10%减半锁利，剩余移动止盈(最高点回落5%)")
        w("    【逻辑破】①该板块连续3天资金流出 ②机构次日在龙虎榜净卖出")
        w("    ─── ★★下单前必答闸门（V3.0新增，答不出=指令不成立）★★ ───")
        w("    ①-B 这只票靠什么赚钱？下游客户是谁？          → ____________")
        w("        机构今天买它的原因，和这个赚钱方式是同一个吗？")
        w("        ★不是同一个 → 净买额再大也不许买（铁律L）")
        w("        ★教训：卓胜微『半导体+3.8%顺风』→ 实际驱动是手机出货，")
        w("          存储涨价反而抬高它成本，是利空。板块顺风对它无效。")
        w("    ③-B 这是【产业周期】还是【单一事件】？        → ____________")
        w("        产业周期→填『预计持续__周』；单一事件→当天就是顶")
        w("    ⑥  它属于哪条驱动链？我在这条链上已有多少？   → ____________")
        for ch, v in sorted(MY_CHAINS.items(), key=lambda x: -x[1]):
            pc = v / TOTAL_ASSET_WAN * 100
            mark = " 🔴已接近上限" if pc >= CHAIN_MAX_PCT - 8 else ""
            w(f"        现有 {ch}：{v:.2f}万 = {pc:.0f}%{mark}")
        w(f"        ★铁律⑧：同一驱动链合计不许超{CHAIN_MAX_PCT}%")
        w("    ⑨  逻辑破定义（买入当天写死，将来卖出只认这个）→ ____________")
        w("")
        archive.append({"code": cd, "name": nm, "amt": amt, "pct": pct, "why": why})

    w("  ⚠️ 执行纪律：")
    w("    1. 上面是【候选指令】，闸门①-B/③-B/⑥/⑨ 全部答完才成为可执行指令")
    w("    2. 答完了就下单，不许再降级为『观察』『等明天验证』（铁律H）")
    w("    3. 答不出①-B就不许买 —— 这不是谨慎，这是铁律L，答不出说明不懂它")
    w("    4. 若仓位只够一只 → 选净买额最大且①-B答得出的那只")

    # ★V3.0 存档，供 backtest_order 回测
    if archive:
        try:
            d = _bt_load(ORDER_HIST_FILE)
            d[now_beijing().strftime("%Y-%m-%d")] = archive
            _bt_save(ORDER_HIST_FILE, d)
            w(f"\n  📌 已存档{len(archive)}条指令 → 3日后自动回看命中率")
        except Exception:
            pass
    w("=" * 60)


def backtest_institution():
    """★★★V3.4【机构成绩单】机构到底对不对 —— 用户命题★★★

    ★这张表要回答四个问题，每个都是我现在答不出的：
      Q1 机构买入后1/3/5日，涨的多还是跌的多？（机构准不准）
      Q2 机构【买跌】的 vs 【买涨停】的，哪组更准？（铁律B成不成立）
      Q3 机构与全榜【方向一致】vs【符号相反】，哪组更准？（我的闸门有没有用）
      Q4 净买额大小和后续涨幅有没有关系？（金额是不是信号）

    ★为什么必须统计而不能推理：
      同一笔"机构净买"背后可能是——建仓/被动申购/义务买单/看错了/
      时间尺度不同。这五种事前分不清，只有事后胜率能说话。
    """
    w("\n" + "=" * 60)
    w("📊📊【机构成绩单】机构到底对不对 —— 累计追踪 📊📊")
    w("=" * 60)
    w("  ★用户命题：『机构为啥要接盘？不想赚钱吗？』")
    w("  ★答案不能靠想，只能靠统计。这张表就是答案本身。")
    d = _bt_load(INST_HIST_FILE)
    if not d:
        w("\n  尚无数据，今天是第1天。")
        w("  ⚠️ 需≥5个交易日、≥30个样本才出结论。之前的任何断言都是猜的。")
        w("=" * 60)
        return

    # 取当前价
    _sname, spot = multi_source("结算快照", [
        ("东财", lambda: ak.stock_zh_a_spot_em()),
        ("新浪", lambda: ak.stock_zh_a_spot()),
        ("同花顺", lambda: ak.stock_zh_a_spot_ths()),
    ])
    if spot is None:
        days = sorted(d.keys(), reverse=True)
        n = sum(len(v) for v in d.values())
        w(f"\n  已累计 {len(days)}天 / {n}个样本，但快照取价失败，本次无法结算")
        w("=" * 60)
        return
    c_code = pick_col(spot, ["代码", "code"])
    c_price = pick_col(spot, ["最新价", "trade"])
    c_str = spot[c_code].astype(str)

    def _px(cd):
        try:
            r = spot[c_str.str.contains(cd, na=False)]
            if len(r) > 0:
                v = pd.to_numeric(r.iloc[0][c_price], errors="coerce")
                return float(v) if pd.notna(v) else None
        except Exception:
            pass
        return None

    today = now_beijing()
    # 桶：[命中数, 样本数, 累计收益]
    buckets = {"全部": [0, 0, 0.0], "买跌": [0, 0, 0.0],
               "买涨停": [0, 0, 0.0], "买微涨": [0, 0, 0.0],
               "方向一致": [0, 0, 0.0], "符号相反": [0, 0, 0.0],
               "净买≥1亿": [0, 0, 0.0], "净买<1亿": [0, 0, 0.0]}
    rows = []
    for day in sorted(d.keys(), reverse=True)[:20]:
        try:
            dt = datetime.datetime.strptime(day, "%Y%m%d")
        except Exception:
            try:
                dt = datetime.datetime.strptime(day, "%Y-%m-%d")
            except Exception:
                continue
        gap = (today - dt).days
        if gap < 1:
            continue
        for it in d[day]:
            cd = it.get("code", "")
            p1 = _px(cd)
            # 存档时没存价格，用当日涨跌幅反推当日收盘不可靠 → 存价格是V3.5的事
            p0 = it.get("price")
            if not p0 or not p1:
                continue
            chg = (p1 - p0) / p0 * 100
            ok = chg > 3
            def _add(k):
                buckets[k][1] += 1
                buckets[k][0] += 1 if ok else 0
                buckets[k][2] += chg
            _add("全部")
            _add(it.get("kind", "买微涨"))
            if it.get("agree") is True:
                _add("方向一致")
            elif it.get("agree") is False:
                _add("符号相反")
            _add("净买≥1亿" if float(it.get("inst", 0)) >= 1 else "净买<1亿")
            rows.append((day, gap, it.get("name"), it.get("kind"), chg))

    days = sorted(d.keys(), reverse=True)
    n_all = sum(len(v) for v in d.values())
    w(f"\n  已累计 {len(days)} 个交易日 / {n_all} 个样本")

    if buckets["全部"][1] == 0:
        # ★V3.6：区分两种"算不出"，别再误报（8/11把"还没到次日"报成"缺价格"）
        _n_priced = sum(1 for v in d.values() for it in v if it.get("price"))
        if _n_priced == 0:
            w("\n  ⚠️ 存档里缺【当日收盘价】，无法结算。")
            w("     （V3.5起收盘价改从龙虎榜明细直接取，新存档已带价格）")
        else:
            w(f"\n  ⏳ 已有{_n_priced}条带价格的存档，但都还没到次日，无法结算。")
            w("     明天这个时候就会出第一批数字。")
        w("=" * 60)
        return

    w("\n  ── 分组胜率（买入后至今，>3%算命中）──")
    for k in ["全部", "买跌", "买涨停", "买微涨", "方向一致", "符号相反",
              "净买≥1亿", "净买<1亿"]:
        h, n, sm = buckets[k]
        if n:
            w(f"    {k:8s}：{h:>3}/{n:<3} = {h/n*100:5.1f}%  平均{sm/n:+6.2f}%")
    w("")
    w("  ── 结论怎么读 ──")
    w("  · 『全部』<45% → 机构信号整体没有边缘，跟机构这条路走不通")
    w("  · 『买跌』明显>『买涨停』→ 铁律B成立，机构买跌确实是埋伏")
    w("  · 两者差不多 → 大资金建仓本来就得买在下跌里，是常态不是信号")
    w("  · 『方向一致』>『符号相反』→ 我加的交叉校验闸门有价值，保留")
    w("  · 『符号相反』反而更高 → 闸门拦错了，立刻拆掉")
    w("  ⚠️ 样本<30 之前，以上任何一条都不许当结论用")
    w("=" * 60)


def backtest_order():
    """★V3.0：转化率0%被反复检讨，但『转化了会不会赚』从没验证过。
    这才是决定该不该提高转化率的依据。"""
    w("\n" + "=" * 60)
    w("🔬【下单指令·回测】埋伏信号到底值不值得下单")
    w("=" * 60)
    d = _bt_load(ORDER_HIST_FILE)
    if not d:
        w("  尚无存档，今晚是第1天。")
        w("  ⚠️ 铁律：累计≥5天且≥15样本后出胜率；连续<45% → 停用『埋伏必下单』规则")
        w("=" * 60)
        return
    days = sorted(d.keys(), reverse=True)
    n_all = sum(len(v) for v in d.values())
    w(f"  已积累 {len(days)} 天 / {n_all} 条指令")
    w("\n  ── 最近5天发出的指令（请对照次日行情自查）──")
    for day in days[:5]:
        items = d[day]
        w(f"  {day}：" + " ｜ ".join(
            f"{x.get('name')}({x.get('code')}) 净买{x.get('amt', 0):.1f}亿"
            for x in items[:5]))
    w("\n  ⚠️ 对照方法：3日后看这些票涨跌，>3%算命中。")
    w("     命中率 ≥45% → 提高转化率是对的，该更果断")
    w("     命中率 <45% → 转化率0%其实救了你，该改的是信号本身不是执行力")
    w("  ⚠️ 在拿到这个数字之前，『必须下单』和『再观察』都只是态度，不是证据。")
    w("=" * 60)


def main():
    bj = now_beijing()
    wd = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][bj.weekday()]
    w("=" * 60)
    w(f"龙虎榜/游资 独立扫描器V3.6 | {bj.strftime('%Y-%m-%d %H:%M')} {wd}")
    w("=" * 60)
    # ★V3.3：本文件没有 safe_run（那是 scanner_cloud 的），用 try 直接包
    try:
        _load_account()
    except Exception as e:
        w(f"  [报空] 载入账户：{type(e).__name__}: {str(e)[:60]}")
    if bj.weekday() >= 5:
        w("周末无龙虎榜数据（下方为最近一个交易日的回溯结果）")
    elif bj.hour < 18:
        w(f"⚠️ 当前{bj.hour}点，龙虎榜18:35后才发布，本次可能为空")

    ambush, chase = [], []
    try:
        ambush, chase = scan_lhb()
    except Exception as e:
        w(f"  [报空] 龙虎榜模块：{type(e).__name__}: {str(e)[:60]}")
    try:
        scan_hot_money()
    except Exception as e:
        w(f"  [报空] 游资席位模块：{type(e).__name__}: {str(e)[:60]}")
    jg = []
    try:
        jg = scan_jg() or []
    except Exception as e:
        w(f"  [报空] 机构席位模块：{type(e).__name__}: {str(e)[:60]}")

    # ★V3.0：即使前面全挂，下单指令与回测也照常运行并明确报出「无数据」
    try:
        gen_order(ambush, jg)
    except Exception as e:
        w(f"  [报空] 下单指令：{type(e).__name__}: {str(e)[:60]}")
    try:
        backtest_order()
    except Exception as e:
        w(f"  [报空] 指令回测：{type(e).__name__}: {str(e)[:60]}")
    try:
        backtest_institution()
    except Exception as e:
        w(f"  [报空] 机构成绩单：{type(e).__name__}: {str(e)[:60]}")

    w("\n" + "=" * 60)
    w("★★★【明日作战提示】★★★")
    w("  铁律B：游资在『当天下跌』的板块砸钱 = 埋伏 = 明天最可能启动")
    w("  ①先看埋伏池 → ②查它属于哪个板块 → ③板块是否已启动")
    w("  ④催化是『一次性事件』还是『持续趋势』 → ⑤才决定买不买")
    w("  ★铁律K：越反常的交易，含义越深。正常交易不含信息。")
    w(f"\n  💰 可用现金 {CASH_AVAIL_WAN*10000:,.0f}元 —— 不先卖就买不了任何东西")
    w("     卖之前必过卖出卡：查台账写死的逻辑破定义，破了才准卖")
    w("=" * 60)

    os.makedirs("reports", exist_ok=True)
    text = "\n".join(REPORT)
    d = bj.strftime("%Y%m%d")
    for p in [f"reports/龙虎榜_最新.txt", f"reports/龙虎榜_{d}.txt"]:
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    print("\n✅ 龙虎榜扫描V3.6完成")


if __name__ == "__main__":
    main()

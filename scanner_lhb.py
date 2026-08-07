# -*- coding: utf-8 -*-
"""
龙虎榜/游资 独立扫描器 V1.1（2026-07-28 自动回溯最近有数据的交易日）
专职：每晚18:40跑，抓当日龙虎榜 + 活跃营业部
核心：自动标注【埋伏型】(跌着被买=明天机会) / 【追高型】(涨停被买=次日易崩)
输出：reports/龙虎榜_最新.txt + reports/龙虎榜_日期.txt
与A股扫描器完全独立，互不影响
"""
import os, time, signal, datetime
import akshare as ak
import pandas as pd

REPORT = []


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
    if use_date != now_beijing().strftime("%Y%m%d"):
        w(f"  ⚠️ 注意：这是【{use_date}】的龙虎榜，不是今天的。")
        w("     今日龙虎榜18:35后发布，届时重跑可得最新。")

    c_name = pick_col(df, ["名称", "股票简称", "简称"])
    c_code = pick_col(df, ["代码", "股票代码"])
    c_pct = pick_col(df, ["涨跌幅", "涨跌幅度", "收盘涨跌幅"])
    c_net = pick_col(df, ["净买额", "龙虎榜净买额", "机构买入净额", "净额"])
    c_reason = pick_col(df, ["上榜原因", "解读", "指标"])
    if not c_name:
        w(f"  [报空] 缺名称列，源={src} 实际列名={list(df.columns)[:12]}")
        return [], []

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
    for _, r in df.head(25).iterrows():
        nm = str(r[c_name])
        code = str(r[c_code])[-6:] if c_code else ""
        pct = r[c_pct] if c_pct else None
        net = r[c_net] if c_net else None
        tag = ""
        if pct is not None and pd.notna(pct):
            if pct < 0:
                tag = "✅埋伏型"
                if net is None or (pd.notna(net) and net > 0):
                    ambush.append((nm, code, pct, net))
            elif pct >= 9.8:
                tag = "⚠️追高型"
                chase.append((nm, code, pct, net))
            else:
                tag = "中性"
        p = f" {pct:+.2f}%" if pct is not None and pd.notna(pct) else ""
        n = f" 净买{net}亿" if net is not None and pd.notna(net) else ""
        rs = str(r[c_reason])[:18] if c_reason else ""
        w(f"    {nm}({code}){p}{n} {tag} {rs}")

    w("")
    w("  ★★★【埋伏池】游资在『当天下跌』的票上砸钱 = 明天最可能启动 ★★★")
    if ambush:
        for nm, code, pct, net in ambush[:12]:
            n = f" 净买{net}亿" if net is not None and pd.notna(net) else ""
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
        df[c_net] = pd.to_numeric(df[c_net], errors="coerce")
        if df[c_net].abs().max() and df[c_net].abs().max() > 1e6:
            df[c_net] = (df[c_net] / 1e8).round(2)
        df = df.sort_values(c_net, ascending=False)
    w(f"  ◆ 净买入前12（源：{src}）：")
    for _, r in df.head(12).iterrows():
        n = f" 净{r[c_net]}亿" if c_net and pd.notna(r[c_net]) else ""
        s = f" 主买:{str(r[c_stock])[:70]}" if c_stock else ""
        w(f"    {r[c_name]}{n}{s}")
    w("  ※ 判读：席位集中买『当天在跌』的=埋伏，次日看启动；")
    w("    集中买『当天涨停』的=追高接力，次日易崩。")


# ========== 三、机构专用席位 ==========

def scan_jg():
    w("\n【三、机构专用席位】（机构才是真钱，游资是快钱）")
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
    try:
        if df is None or len(df) == 0:
            w("  近7交易日无机构上榜数据")
            return
        w(f"  ✅ 数据日期：{use_date}")
        c_name = pick_col(df, ["名称", "简称"])
        c_pct = pick_col(df, ["涨跌幅"])
        c_buy = pick_col(df, ["机构买入总额", "买入金额"])
        c_net = pick_col(df, ["机构买入净额", "净额"])
        if c_net:
            df[c_net] = pd.to_numeric(df[c_net], errors="coerce")
            df = df.sort_values(c_net, ascending=False)
        for _, r in df.head(15).iterrows():
            nm = r[c_name] if c_name else ""
            p = f" {r[c_pct]}%" if c_pct else ""
            n = f" 机构净买{r[c_net]/1e8:.2f}亿" if c_net and pd.notna(r[c_net]) else ""
            flag = ""
            if c_pct:
                v = pd.to_numeric(r[c_pct], errors="coerce")
                if pd.notna(v) and v < 0:
                    flag = " ✅机构在跌时买入=重要埋伏信号"
            w(f"    {nm}{p}{n}{flag}")
    except Exception as e:
        w(f"  [报空] 机构席位：{type(e).__name__}")



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
}
TOTAL_ASSET_WAN = 18.3      # 总资产(万)，买卖后更新


def gen_order(ambush, jg_rows=None):
    """★强制下单指令：把埋伏信号直接变成可执行的买点+止损+仓位
    治转化率0%：7/28中际旭创+19.6%、7/30长电科技、8/3德明利 三次全错过"""
    w("\n" + "=" * 60)
    w("🔫🔫【强制下单指令】机构在跌的票砸钱 = 直接给买点，不许说观察 🔫🔫")
    w("=" * 60)
    w("  ★铁律H：识别到机构埋伏=必须当场给可执行标的★")
    w("  ★历史转化率0%：7/28中际旭创(后+19.6%)、7/30长电科技、8/3德明利")
    w("    三次识别全对，三次都只说『观察』→ 全部错过")

    orders = []
    for item in (ambush or []):
        try:
            nm, cd, pct, net = item[0], item[1], item[2], item[3]
        except Exception:
            continue
        amt = None
        try:
            amt = float(net) if net is not None else None
        except Exception:
            pass
        # 门槛：净买≥1亿 且 当天下跌
        if amt is None or amt < 1.0 or (pct is not None and pct >= 0):
            continue
        orders.append((amt, nm, cd, pct))

    if not orders:
        w("\n  今日无【机构/游资在跌的票上净买≥1亿】的标的")
        w("  → 明确结论：今晚不产生下单指令（不硬凑，铁律D）")
        return
    orders.sort(key=lambda x: -x[0])

    w(f"\n  ★★今日触发下单条件 {len(orders)} 只 —— 逐个给指令★★\n")
    for i, (amt, nm, cd, pct) in enumerate(orders[:5], 1):
        etf = None
        for k, v in HIGH_PRICE_ETF.items():
            if k in nm:
                etf = v
                break
        w(f"  ══════ 指令{i}：{nm}({cd}) ══════")
        w(f"    信号：今日{pct:+.2f}% 被净买 {amt:.2f}亿（跌着被买=埋伏型）")
        if etf:
            w(f"    ⚠️ 股价高，一手可能>总资产10% → ★改买ETF：{etf}★")
            w("       （铁律H②：个股太贵就给ETF，不许说买不起）")
        else:
            w(f"    🎯 标的：{nm}({cd}) —— 直接买个股")
        w("    ─────────────────────────")
        w("    【买点】次日开盘不追高：")
        w("      · 低开或平开 → 直接买")
        w("      · 高开>5% → 等回踩到分时均价")
        w("      · 高开>9% → 放弃，改等第2个回踩日")
        w(f"    【仓位】{TOTAL_ASSET_WAN*0.11:.1f}万（约总资产11%，单笔上限）")
        w("    【止损】-12%（机构建仓要时间，给足空间）")
        w("    【类型】B类周期仓，最少持有3个交易日")
        w("      ★铁律H④：信号次日若下跌，不算信号错，不许当天砍")
        w("    【兑现】+10%减半锁利，剩余移动止盈(最高点回落5%)")
        w("    【逻辑破】①该板块连续3天资金流出 ②机构次日在龙虎榜净卖出")
        w("")

    w("  ⚠️ 执行纪律（写死，不许绕过）：")
    w("    1. 上面每条指令都是【可直接下单】的，不是建议")
    w("    2. AI在对话里不许把它降级为『观察』『关注』『等明天验证』")
    w("    3. 若因仓位不足只能选一只 → 选净买额最大的那只")
    w("    4. 若全部是高价股 → 买对应ETF，仍然要下单")
    w("=" * 60)


def main():
    bj = now_beijing()
    wd = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][bj.weekday()]
    w("=" * 60)
    w(f"龙虎榜/游资 独立扫描器V2.0 | {bj.strftime('%Y-%m-%d %H:%M')} {wd}")
    w("=" * 60)
    if bj.weekday() >= 5:
        w("周末无龙虎榜数据")
    elif bj.hour < 18:
        w(f"⚠️ 当前{bj.hour}点，龙虎榜18:35后才发布，本次可能为空")

    ambush, chase = scan_lhb()
    scan_hot_money()
    scan_jg()
    gen_order(ambush)

    w("\n" + "=" * 60)
    w("★★★【明日作战提示】★★★")
    w("  铁律B：游资在『当天下跌』的板块砸钱 = 埋伏 = 明天最可能启动")
    w("  ①先看埋伏池 → ②查它属于哪个板块 → ③板块是否已启动")
    w("  ④催化是『一次性事件』还是『持续趋势』 → ⑤才决定买不买")
    w("=" * 60)

    os.makedirs("reports", exist_ok=True)
    text = "\n".join(REPORT)
    d = bj.strftime("%Y%m%d")
    for p in [f"reports/龙虎榜_最新.txt", f"reports/龙虎榜_{d}.txt"]:
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    print("\n✅ 龙虎榜扫描完成")


if __name__ == "__main__":
    main()

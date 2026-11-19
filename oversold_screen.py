# -*- coding: utf-8 -*-
"""
弱市超跌反弹·每日选股（2026-11-18 新建）
依据：reports/个股打法回测.txt（397只×15个月）
  弱市（沪深300<60日线）：M4 超跌＋放量长阳 T+5 +2.12%/55%；M3 超跌 T+10 +2.02%/55%（对照 +0.14%/47%）
  强市：同样信号 −2%/30% → 强市不用本筛选
叠加过滤（板块资金回测）：所在板块近3日大额净流出（≥近期日均|流入|×4）→ 剔除
条件（盘中/尾盘用实时快照）：
  ① 今日涨≥3% 且 量比≥1.5（放量长阳止跌）
  ② 现价在【向下】的20日线下方（20日线比5天前低）
  ③ 近20日涨幅比沪深300低≥10个点
  ④ 非ST、成交额≥1亿、股价≥3元（剔除面值退市风险）
输出 reports/超跌候选.txt
"""
import datetime, json, os, time, traceback
import akshare as ak
import pandas as pd

OUT = "reports/超跌候选.txt"
L = []


def retry(f, n=4, wait=5):
    for k in range(n):
        try:
            return f()
        except Exception:
            if k == n - 1:
                raise
            time.sleep(wait * (k + 1))


# 11/19 练手命中率回测（practice_bt.py）选出的主打变体；候选里命中它的标⭐，练手只从⭐里挑
PRIMARY = "V2"   # 待回测结果更新：V2=M4 V3=+收在高位 V5=+60日回撤≥30% V6=+前5日急跌≥8% V8=+涨幅3–7%
EM_BAN = {"on": False}   # 11/19：东财push2限流→整轮切新浪，不再碰东财（重复调用会延长封禁）


def spot():
    try:
        sp = retry(lambda: ak.stock_zh_a_spot_em(), n=2, wait=5)
        sp = sp.rename(columns={"代码": "code", "名称": "name", "最新价": "px", "涨跌幅": "chg", "量比": "vr", "成交额": "amt", "最高": "hi", "最低": "lo"})
        return sp, "东财"
    except Exception:
        EM_BAN["on"] = True
    sp = retry(lambda: ak.stock_zh_a_spot())          # 新浪，无量比→后面用日线自算
    sp = sp.rename(columns={"代码": "code", "名称": "name", "最新价": "px", "涨跌幅": "chg", "成交额": "amt", "成交量": "vol", "最高": "hi", "最低": "lo"})
    sp["code"] = sp["code"].astype(str).str[-6:]
    sp["vr"] = None
    return sp, "新浪(东财限流)"


def hist(code, start, end):
    """返回 (日期列表, 收盘列表, 成交量列表)；东财被封则用新浪日线"""
    if not EM_BAN["on"]:
        try:
            h = retry(lambda: ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start, end_date=end, adjust="qfq"), n=2, wait=2)
            return h["日期"].astype(str).tolist(), h["收盘"].astype(float).tolist(), h["成交量"].astype(float).tolist()
        except Exception as e:
            if "push2" in str(e) or "限流" in str(e):
                EM_BAN["on"] = True
            else:
                raise
    mk = "sh" if code.startswith("6") else "sz"
    h = retry(lambda: ak.stock_zh_a_daily(symbol=mk + code, start_date=start, end_date=end, adjust="qfq"), n=2, wait=2)
    return h["date"].astype(str).tolist(), h["close"].astype(float).tolist(), (h["volume"].astype(float) / 100).tolist()


def sector_flow():
    p = "reports/sector_flow_hist.json"
    if not os.path.exists(p):
        return {}, {}
    d = json.load(open(p, encoding="utf-8"))
    ks = sorted(d)
    last3 = ks[-3:]
    s3, avg = {}, {}
    for nm in set().union(*[set(d[k]) for k in ks[-20:]]):
        v = [d[k].get(nm) for k in ks[-20:] if d[k].get(nm) is not None]
        if v:
            avg[nm] = sum(abs(x) for x in v) / len(v)
        s3[nm] = sum(d[k].get(nm) or 0 for k in last3)
    return s3, avg


def main():
    bj = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)
    L.append("=" * 72)
    L.append(f"🎯【弱市超跌反弹·候选】北京 {bj:%Y-%m-%d %H:%M}")
    L.append("   依据：个股打法回测 弱市M4 T+5 +2.12%/55%（157笔，样本小）、M3 T+10 +2.02%/55%；强市此法亏")
    L.append("=" * 72)
    idx = retry(lambda: ak.stock_zh_index_daily(symbol="sh000300"))
    ic = idx["close"].astype(float)
    weak = ic.iloc[-1] < ic.rolling(60).mean().iloc[-1]
    ir20 = (ic.iloc[-1] / ic.iloc[-21] - 1) * 100
    L.append(f"  大盘：沪深300 {ic.iloc[-1]:.0f} vs 60日线 {ic.rolling(60).mean().iloc[-1]:.0f} → {'弱市✅本筛选适用' if weak else '强市❌本筛选不适用（回测亏）'} ｜ 沪深300近20日{ir20:+.1f}%")
    sp, src = spot()
    L.append(f"  行情源：{src}")
    for c in ("hi", "lo"):
        if c not in sp.columns:
            sp[c] = None
    for c in ("px", "chg", "vr", "amt", "hi", "lo"):
        sp[c] = pd.to_numeric(sp[c], errors="coerce")
    sp = sp[sp["code"].astype(str).str[:2].isin(["60", "00", "30", "68"]) & ~sp["name"].astype(str).str.contains("ST")]
    novr = sp["vr"].isna().all()
    c1 = sp[(sp["chg"] >= 3) & ((sp["vr"] >= 1.5) | novr) & (sp["amt"] >= 1e8) & (sp["px"] >= 3)]   # 11/18：剔除<3元（面值退市风险）
    c1 = c1.sort_values("chg", ascending=False).head(150)
    L.append(f"  ① 今日涨≥3%且量比≥1.5且成交≥1亿：{len(c1)}只（逐只查K线）")
    s3, avg = sector_flow()
    end = bj.strftime("%Y%m%d")
    start = (bj - datetime.timedelta(days=110)).strftime("%Y%m%d")   # 要算60日高点
    hits = []
    for r in c1.itertuples():
        try:
            ds, cl, vl = hist(r.code, start, end)
            time.sleep(0.2)
        except Exception:
            continue
        vr = r.vr
        if ds[-1][:10] != bj.strftime("%Y-%m-%d"):
            cl.append(r.px)            # 盘中：今天的K线还没进日线，用现价补上
            if pd.isna(vr) and len(vl) >= 5 and getattr(r, "vol", None):
                vr = float(r.vol) / 100 / (sum(vl[-5:]) / 5)   # 新浪：盘中成交量/5日均量（盘中偏低，口径保守）
        elif pd.isna(vr) and len(vl) >= 6:
            vr = vl[-1] / (sum(vl[-6:-1]) / 5)
        if vr is None or pd.isna(vr) or vr < 1.5:
            continue
        if len(cl) < 26:
            continue
        ma20 = sum(cl[-20:]) / 20
        ma20p = sum(cl[-25:-5]) / 20
        r20 = (cl[-1] / cl[-21] - 1) * 100
        if not (cl[-1] < ma20 and ma20 < ma20p and r20 - ir20 <= -10):
            continue
        ind = ""
        try:
            if EM_BAN["on"]:
                raise RuntimeError("东财限流，跳过行业")
            info = retry(lambda: ak.stock_individual_info_em(symbol=r.code), n=2, wait=2)
            ind = str(info[info["item"] == "行业"]["value"].iloc[0])
        except Exception:
            pass
        flow = s3.get(ind)
        big_out = flow is not None and avg.get(ind) and flow <= -4 * avg[ind]
        tag = ("❌板块近3日大额流出%.0f亿→剔除" % flow) if big_out else (
            ("板块近3日%+.0f亿" % flow) if flow is not None else "板块资金：未匹配")
        # 11/19 练手回测变体特征
        rng = (r.hi - r.lo) if pd.notna(r.hi) and pd.notna(r.lo) else None
        hipos = bool(rng and rng > 0 and r.px >= r.lo + 0.8 * rng)
        deep = r.px <= max(cl[-60:]) * 0.7
        r5p = (cl[-2] / cl[-7] - 1) * 100 if len(cl) >= 7 else 0
        var = {"V2": True, "V3": hipos, "V5": deep, "V6": r5p <= -8, "V8": r.chg <= 7}
        feat = "收高位%s 60日回撤%.0f%% 前5日%+.0f%%" % ("✓" if hipos else "✗", (1 - r.px / max(cl[-60:])) * 100, r5p)
        hits.append((r.code, r.name, r.px, r.chg, vr, r20 - ir20, ind, tag, big_out, var.get(PRIMARY, False), feat))
    ok = [x for x in hits if not x[8]]
    L.append(f"  ②③ 在向下20日线下方且20日相对沪深300弱≥10点：{len(hits)}只 ｜ 过板块过滤后：{len(ok)}只")
    L.append("\n【候选】（只是回测优势信号，买前仍须：9项清单＋反方证据≥3＋七步推演＋查股票；单笔≤1.5万；止损＝今日最低价下方）")
    for x in hits:
        L.append(f"  {'✅' if not x[8] else '  '}{'⭐' if x[9] and not x[8] else ''} {x[1]}({x[0]}) 现价{x[2]} 今日{x[3]:+.1f}% 量比{x[4]:.1f} ｜ 20日相对沪深300 {x[5]:+.1f}点 ｜ {x[10]} ｜ {x[6] or '行业未知'} ｜ {x[7]}")
    L.append(f"\n  ⭐=命中练手主打变体 {PRIMARY}（依据 reports/练手命中率回测.txt）；练手A轨只从⭐里挑，没有就空着")
    if not hits:
        L.append("  今天没有符合条件的股票")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        L.append("🔴 失败：" + traceback.format_exc()[-800:])
    os.makedirs("reports", exist_ok=True)
    open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L))

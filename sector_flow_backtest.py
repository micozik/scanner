# -*- coding: utf-8 -*-
"""
板块资金确认打法回测（2026-11-17 新建）
用户问："你是什么逻辑？什么打法？有啥把握？" —— 核心假设"板块连续2天主力净流入后跟进"从没验证过，这里验证。

数据：东财行业板块（ak.stock_sector_fund_flow_hist 日度主力净流入；ak.stock_board_industry_hist_em 板块指数收盘）
     沪深300（ak.stock_zh_index_daily）判断弱市（收盘<60日线）
规则（板块指数代替龙头，持有期看 T+3 / T+5，收盘价进出）：
  R0 基准：任意一天收盘买入
  R1 首日流入：前3天都净流出、今天转净流入 → 今天收盘买（"第1天就冲"——我们之前的亏法）
  R2 连续2天流入：昨天、今天都净流入 → 今天收盘买
  R3 连续2天流入、第3天收盘买（R2 信号次日收盘才进，模拟"第3天回调买"的保守版）
  R4 连续2天流入且两天合计≥该板块近60日|日流入|均值×3（"大资金"） → 今天收盘买
每条规则分 全部 / 弱市 两组统计：样本数、平均收益、胜率、盈亏比
输出 reports/板块资金回测.txt
"""
import datetime, os, time, traceback
import akshare as ak
import pandas as pd

OUT = "reports/板块资金回测.txt"
L = []


def hs300_weak():
    df = ak.stock_zh_index_daily(symbol="sh000300")
    df["d"] = pd.to_datetime(df["date"]).dt.date
    df["ma60"] = df["close"].rolling(60).mean()
    return {r.d: (r.close < r.ma60) for r in df.itertuples() if pd.notna(r.ma60)}


def board_data(name):
    f = ak.stock_sector_fund_flow_hist(symbol=name)
    f = f.rename(columns={"日期": "d", "主力净流入-净额": "flow"})
    f["d"] = pd.to_datetime(f["d"]).dt.date
    f["flow"] = pd.to_numeric(f["flow"], errors="coerce") / 1e8
    start = (min(f["d"]) - datetime.timedelta(days=5)).strftime("%Y%m%d")
    end = datetime.date.today().strftime("%Y%m%d")
    p = ak.stock_board_industry_hist_em(symbol=name, start_date=start, end_date=end, period="日k", adjust="")
    p = p.rename(columns={"日期": "d", "收盘": "close"})
    p["d"] = pd.to_datetime(p["d"]).dt.date
    m = pd.merge(f[["d", "flow"]], p[["d", "close"]], on="d").sort_values("d").reset_index(drop=True)
    return m


def fwd(m, i, k):
    return (m.loc[i + k, "close"] / m.loc[i, "close"] - 1) * 100 if i + k < len(m) else None


def main():
    bj = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
    L.append("=" * 72)
    L.append(f"🧪【板块资金确认打法·回测】北京 {bj}")
    L.append("   东财行业板块；板块指数收盘价进出；弱市＝沪深300收盘<60日线")
    L.append("=" * 72)
    weak = hs300_weak()
    names = ak.stock_board_industry_name_em()["板块名称"].tolist()
    rules = {k: {"all": {3: [], 5: []}, "weak": {3: [], 5: []}} for k in ("R0", "R1", "R2", "R3", "R4")}
    ok = fail = 0
    span = [None, None]
    for nm in names:
        try:
            m = board_data(nm)
            time.sleep(0.4)
        except Exception:
            fail += 1
            time.sleep(1)
            continue
        if len(m) < 30:
            continue
        ok += 1
        span[0] = min(span[0] or m["d"].iloc[0], m["d"].iloc[0])
        span[1] = max(span[1] or m["d"].iloc[-1], m["d"].iloc[-1])
        avg = m["flow"].abs().rolling(60, min_periods=20).mean()
        for i in range(3, len(m)):
            fl = m["flow"]
            sig = {"R0": True,
                   "R1": fl[i] > 0 and fl[i - 1] < 0 and fl[i - 2] < 0 and fl[i - 3] < 0,
                   "R2": fl[i] > 0 and fl[i - 1] > 0,
                   "R4": fl[i] > 0 and fl[i - 1] > 0 and pd.notna(avg[i]) and fl[i] + fl[i - 1] >= 3 * avg[i]}
            for r, s in sig.items():
                if not s:
                    continue
                for k in (3, 5):
                    v = fwd(m, i, k)
                    if v is None:
                        continue
                    rules[r]["all"][k].append(v)
                    if weak.get(m.loc[i, "d"]):
                        rules[r]["weak"][k].append(v)
            # R3：R2 信号次日收盘买
            if fl[i - 1] > 0 and fl[i - 2] > 0:
                for k in (3, 5):
                    v = fwd(m, i, k)
                    if v is None:
                        continue
                    rules["R3"]["all"][k].append(v)
                    if weak.get(m.loc[i, "d"]):
                        rules["R3"]["weak"][k].append(v)
    L.append(f"  板块：成功{ok} 失败{fail} ｜ 区间 {span[0]} → {span[1]}")
    desc = {"R0": "基准：任意一天买",
            "R1": "首日流入就买（前3天流出→今天转流入）",
            "R2": "连续2天流入，第2天收盘买",
            "R3": "连续2天流入，第3天收盘买",
            "R4": "连续2天流入且是大资金（≥近60日均值×3）"}

    def stat(v):
        if not v:
            return "样本0"
        w = [x for x in v if x > 0]
        lz = [x for x in v if x <= 0]
        pl = (sum(w) / len(w)) / abs(sum(lz) / len(lz)) if w and lz and sum(lz) != 0 else float("nan")
        return f"样本{len(v):>5} ｜ 平均{sum(v)/len(v):+.2f}% ｜ 胜率{len(w)/len(v)*100:.0f}% ｜ 盈亏比{pl:.2f}"

    for r in ("R0", "R1", "R2", "R3", "R4"):
        L.append(f"\n◆ {r} {desc[r]}")
        for grp, nm in (("all", "全部"), ("weak", "弱市")):
            for k in (3, 5):
                L.append(f"   {nm} T+{k}：{stat(rules[r][grp][k])}")
    L.append("\n  读法：比基准R0明显更好（平均更高、胜率>55%）才算有优势；弱市那一行才是现在适用的")
    L.append("  ⚠️ 用板块指数代替龙头，忽略手续费与滑点；只说明'跟资金'这件事本身有没有优势")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        L.append("🔴 失败：" + traceback.format_exc()[-800:])
    os.makedirs("reports", exist_ok=True)
    open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L))

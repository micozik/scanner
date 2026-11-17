# -*- coding: utf-8 -*-
"""
业绩高增长回测（2026-11-17 新建）
板块资金回测证明"跟资金"无优势后，验证下一个买入依据：业绩真兑现的股票，公告后买入有没有优势。

数据：ak.stock_yjbb_em(date=报告期) 业绩报表（净利润同比、公告日期、每股经营现金流、每股收益）
     ak.stock_zh_a_hist 个股日线（前复权）
分组（报告期 2026-06-30 半年报、2026-09-30 三季报）：
  G0 对照：同报告期随机抽样的全部股票
  G1 净利同比≥50%
  G2 净利同比≥50% 且 每股经营现金流/每股收益≥0.5（现金流对得上）
  G3 G2 且 净利同比≥100%
买点：公告日后第1个交易日收盘买；看 T+5 / T+20 收益，胜率，跑赢沪深300
输出 reports/业绩回测.txt
"""
import datetime, os, random, time, traceback
import akshare as ak
import pandas as pd

OUT = "reports/业绩回测.txt"
L = []
PERIODS = ["20260630", "20260930"]
random.seed(7)


def hs300():
    df = ak.stock_zh_index_daily(symbol="sh000300")
    df["d"] = pd.to_datetime(df["date"]).dt.date
    return df.set_index("d")["close"]


def px(code, start):
    end = datetime.date.today().strftime("%Y%m%d")
    df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start, end_date=end, adjust="qfq")
    df["d"] = pd.to_datetime(df["日期"]).dt.date
    return df.set_index("d")["收盘"]


def main():
    bj = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
    L.append("=" * 72)
    L.append(f"🧪【业绩高增长·公告后买入回测】北京 {bj}")
    L.append("   公告日后第1个交易日收盘买；前复权；不含手续费")
    L.append("=" * 72)
    idx = hs300()
    idays = list(idx.index)
    res = {g: {5: [], 20: [], "ex5": [], "ex20": []} for g in ("G0", "G1", "G2", "G3")}
    for per in PERIODS:
        try:
            yj = ak.stock_yjbb_em(date=per)
        except Exception:
            L.append(f"  {per} 业绩报表获取失败：{traceback.format_exc().splitlines()[-1][:120]}")
            continue
        yj = yj.rename(columns={"股票代码": "code", "净利润-同比增长": "g", "最新公告日期": "ann",
                                "每股经营现金流量": "cfps", "每股收益": "eps"})
        yj["g"] = pd.to_numeric(yj["g"], errors="coerce")
        yj["cfps"] = pd.to_numeric(yj["cfps"], errors="coerce")
        yj["eps"] = pd.to_numeric(yj["eps"], errors="coerce")
        yj["ann"] = pd.to_datetime(yj["ann"], errors="coerce").dt.date
        yj = yj[yj["code"].astype(str).str.match(r"^(60|00|30|68)") & yj["ann"].notna()]
        g1 = yj[(yj["g"] >= 50) & (yj["eps"] > 0)]
        g2 = g1[(g1["cfps"] / g1["eps"]) >= 0.5]
        g3 = g2[g2["g"] >= 100]
        g1s = g1.sample(min(len(g1), 150), random_state=1)
        g0s = yj.sample(min(len(yj), 150), random_state=2)
        L.append(f"  {per}：全部{len(yj)}只 ｜ 净利≥50% {len(g1)}只 ｜ +现金流 {len(g2)}只 ｜ +净利≥100% {len(g3)}只（G0/G1各抽150只，G2/G3全测，上限200）")
        todo = {}
        for g, df in (("G0", g0s), ("G1", g1s), ("G2", g2.head(200)), ("G3", g3.head(200))):
            for r in df.itertuples():
                todo.setdefault(r.code, (r.ann, set()))[1].add(g)
        for code, (ann, groups) in todo.items():
            try:
                p = px(code, (ann - datetime.timedelta(days=5)).strftime("%Y%m%d"))
                time.sleep(0.25)
            except Exception:
                time.sleep(1)
                continue
            days = [d for d in p.index if d > ann]
            if not days:
                continue
            b = days[0]
            i = list(p.index).index(b)
            for k in (5, 20):
                if i + k >= len(p):
                    continue
                ret = (p.iloc[i + k] / p.iloc[i] - 1) * 100
                ex = None
                if b in idx.index:
                    j = idays.index(b)
                    if j + k < len(idays):
                        ex = ret - (idx.iloc[j + k] / idx.iloc[j] - 1) * 100
                for g in groups:
                    res[g][k].append(ret)
                    if ex is not None:
                        res[g]["ex" + str(k)].append(ex)
    desc = {"G0": "对照：随机全部股票", "G1": "净利同比≥50%", "G2": "净利≥50%＋现金流对得上（≥0.5）",
            "G3": "净利≥100%＋现金流对得上"}

    def st(v):
        if not v:
            return "样本0"
        w = sum(1 for x in v if x > 0)
        s = sorted(v)
        return f"样本{len(v):>4} ｜ 平均{sum(v)/len(v):+.2f}% ｜ 中位{s[len(s)//2]:+.2f}% ｜ 胜率{w/len(v)*100:.0f}%"

    for g in ("G0", "G1", "G2", "G3"):
        L.append(f"\n◆ {g} {desc[g]}")
        for k in (5, 20):
            L.append(f"   T+{k}：{st(res[g][k])}")
            L.append(f"   T+{k} 跑赢沪深300：{st(res[g]['ex' + str(k)])}")
    L.append("\n  读法：G2/G3 比 G0 明显更好（平均高≥2个点、胜率≥55%）才算业绩是有效买入依据")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        L.append("🔴 失败：" + traceback.format_exc()[-800:])
    os.makedirs("reports", exist_ok=True)
    open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L))

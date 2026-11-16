# -*- coding: utf-8 -*-
"""
短融ETF（511360）机构停车资金监控 + 历史回测（2026-11-16 新建）
用户："你怎么没查到这个信息"（11/16 短融ETF海富通成交超1200亿，历史第二；9/22 1372亿历史第一）
含义：短融ETF是机构T+0流动性工具。天量＝大资金从股票撤出、停车观望，但没离场，随时可回流。
输出 reports/短融ETF.txt：
  ① 今天/近10日成交额 + 判定（>800亿=机构停车观望，不开新仓；从高位回落+大盘放量=资金回流信号）
  ② 历史回测：成交额≥阈值的日子之后 沪深300 T+1/T+3/T+5 涨跌、上涨概率
"""
import datetime, os, traceback
import akshare as ak
import pandas as pd

OUT = "reports/短融ETF.txt"
THRESH = [500, 800, 1000]          # 亿元
L = []


def etf_hist():
    end = datetime.date.today().strftime("%Y%m%d")
    df = ak.fund_etf_hist_em(symbol="511360", period="daily",
                             start_date="20240101", end_date=end, adjust="")
    df = df.rename(columns={"日期": "d", "成交额": "amt"})
    df["d"] = pd.to_datetime(df["d"]).dt.date
    df["amt"] = df["amt"].astype(float) / 1e8
    return df[["d", "amt"]]


def etf_today():
    try:
        sp = ak.fund_etf_spot_em()
        row = sp[sp["代码"] == "511360"]
        if len(row):
            return float(row.iloc[0]["成交额"]) / 1e8
    except Exception:
        pass
    return None


def hs300():
    df = ak.stock_zh_index_daily(symbol="sh000300")
    df["d"] = pd.to_datetime(df["date"]).dt.date
    return df[["d", "close"]].reset_index(drop=True)


def main():
    bj = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
    L.append("=" * 70)
    L.append(f"🅿️【短融ETF·机构停车资金】北京 {bj} ｜ 511360 海富通中证短融ETF")
    L.append("   T+0流动性工具：天量＝机构从股票撤出停车观望（没离场，随时回流）")
    L.append("=" * 70)
    h = etf_hist()
    t = etf_today()
    today = datetime.date.today()
    if t is not None and (h.empty or h.iloc[-1]["d"] != today):
        h = pd.concat([h, pd.DataFrame([{"d": today, "amt": t}])], ignore_index=True)
    last = h.tail(10)
    L.append("\n【一、近10个交易日成交额（亿）】")
    for _, r in last.iterrows():
        bar = "█" * int(min(r["amt"], 1500) / 50)
        L.append(f"  {r['d']}  {r['amt']:>7.0f}  {bar}")
    cur = float(h.iloc[-1]["amt"])
    avg20 = float(h.tail(21).head(20)["amt"].mean())
    rank = int((h["amt"] > cur).sum()) + 1
    L.append(f"\n  今天 {cur:.0f}亿 ｜ 前20日均 {avg20:.0f}亿（×{cur/avg20:.1f}）｜ 2024年以来第 {rank} 高")
    if cur >= 800:
        verdict = "🔴 机构大额停车观望 → 不开新仓、不加仓（买入铁律V7红线）"
    elif cur >= 500:
        verdict = "🟡 停车资金偏多 → 新仓从严"
    else:
        verdict = "🟢 常态"
    prev = float(h.iloc[-2]["amt"]) if len(h) > 1 else cur
    if prev >= 800 and cur < prev * 0.6:
        verdict += " ｜ ⚡昨天天量今天骤降≥40% → 停车资金可能在回流股市，盯大盘放量+板块资金流入"
    L.append(f"  ★判定：{verdict}")

    # 回测
    idx = hs300()
    m = idx.set_index("d")["close"]
    dates = list(m.index)
    L.append("\n【二、历史回测：天量之后沪深300怎么走】（2024年以来）")
    for th in THRESH:
        hits = h[h["amt"] >= th]["d"].tolist()
        rows = []
        for d in hits:
            if d not in m.index:
                continue
            i = dates.index(d)
            rr = []
            for k in (1, 3, 5):
                rr.append((m.iloc[i + k] / m.iloc[i] - 1) * 100 if i + k < len(dates) else None)
            rows.append((d, rr))
        L.append(f"  ◆ 成交额≥{th}亿：{len(rows)}天")
        for k, name in enumerate(("T+1", "T+3", "T+5")):
            v = [r[1][k] for r in rows if r[1][k] is not None]
            if v:
                up = sum(1 for x in v if x > 0) / len(v) * 100
                L.append(f"     {name}：平均{sum(v)/len(v):+.2f}% ｜ 上涨概率{up:.0f}% ｜ 样本{len(v)}")
        if th == 800:
            for d, rr in rows[-12:]:
                s = " ".join(f"{x:+.1f}%" if x is not None else "—" for x in rr)
                L.append(f"       {d} 成交{float(h[h['d']==d]['amt'].iloc[0]):.0f}亿 → T+1/3/5 {s}")
    L.append("\n  ⚠️ 样本少（<10天）时只作参考，不作为单独买卖依据")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # 扫描后东财push2常被限流：失败时不覆盖上一份好数据，只在文末追加失败说明
        err = traceback.format_exc().strip().splitlines()[-1][:200]
        old = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        bj = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)).strftime("%m-%d %H:%M")
        if old:
            old = old.split("\n⚠️ 本次刷新失败")[0]
            open(OUT, "w", encoding="utf-8").write(old + f"\n⚠️ 本次刷新失败（{bj}，保留上一份数据）：{err}")
            print("刷新失败，保留上一份"); raise SystemExit(0)
        L.append("🔴 失败：" + err)
    os.makedirs("reports", exist_ok=True)
    open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L))

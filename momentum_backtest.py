# -*- coding: utf-8 -*-
"""
个股层面打法回测（2026-11-18 新建）
用户："你有没有总结出一套比较有效的方法？…找到问题所在，赶紧改进或者把代码修改"
前两轮（板块资金/业绩）都无优势。我们实盘+练手的亏损几乎都来自"抄下跌趋势的底"，赚的来自"强势+催化"。
这里直接比较：抄底 vs 强者恒强（相对强度），以及大盘强弱环境的影响。

样本：A股主板/创业板/科创板随机400只（固定种子），近约15个月日线（前复权）
信号（每天收盘判定、收盘买入，看 T+5 / T+10）：
  M0 对照：任意一天
  M1 强势：站上【向上】的20日线 且 近20日涨幅比沪深300高≥5个点（相对强）
  M2 强势+回踩：M1 且 当日较5日高点回落≥3%（强势股回调买）
  M3 抄底：在【向下】的20日线下方 且 近20日涨幅比沪深300低≥10个点（我们过去的亏法）
  M4 抄底+放量阳线：M3 且 当日涨≥3%且量≥5日均量1.5倍（"止跌信号"）
每条再按大盘环境拆分：强市（沪深300>60日线）/ 弱市
输出 reports/个股打法回测.txt
"""
import datetime, os, random, time, traceback
import akshare as ak
import pandas as pd

OUT = "reports/个股打法回测.txt"
L = []
N = 400


def retry(f, n=5, wait=6):
    """11/18：首轮 ConnectionResetError 直接失败 → 关键接口重试"""
    for k in range(n):
        try:
            return f()
        except Exception:
            if k == n - 1:
                raise
            time.sleep(wait * (k + 1))


def main():
    bj = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
    L.append("=" * 72)
    L.append(f"🧪【个股打法回测：抄底 vs 强者恒强】北京 {bj}")
    L.append("=" * 72)
    idx = retry(lambda: ak.stock_zh_index_daily(symbol="sh000300"))
    idx["d"] = pd.to_datetime(idx["date"]).dt.date
    idx = idx.set_index("d")["close"]
    ima60 = idx.rolling(60).mean()
    ir20 = idx.pct_change(20) * 100
    codes = retry(lambda: ak.stock_info_a_code_name())["code"].astype(str)
    codes = [c for c in codes if c[:2] in ("60", "00", "30", "68")]
    random.seed(11)
    codes = random.sample(codes, N)
    start = (datetime.date.today() - datetime.timedelta(days=460)).strftime("%Y%m%d")
    end = datetime.date.today().strftime("%Y%m%d")
    R = {k: {"strong": {5: [], 10: []}, "weak": {5: [], 10: []}} for k in ("M0", "M1", "M2", "M3", "M4")}
    ok = 0
    for c in codes:
        try:
            df = retry(lambda: ak.stock_zh_a_hist(symbol=c, period="daily", start_date=start, end_date=end, adjust="qfq"), n=3, wait=2)
            time.sleep(0.25)
        except Exception:
            time.sleep(1)
            continue
        if len(df) < 120:
            continue
        ok += 1
        df["d"] = pd.to_datetime(df["日期"]).dt.date
        cl = df["收盘"].astype(float).reset_index(drop=True)
        vol = df["成交量"].astype(float).reset_index(drop=True)
        ds = list(df["d"])
        ma20 = cl.rolling(20).mean()
        r20 = cl.pct_change(20) * 100
        hi5 = cl.rolling(5).max()
        v5 = vol.rolling(5).mean().shift(1)
        chg = cl.pct_change() * 100
        for i in range(60, len(cl) - 1):
            d = ds[i]
            if d not in idx.index or pd.isna(ima60.get(d)):
                continue
            env = "strong" if idx[d] > ima60[d] else "weak"
            rel = r20[i] - ir20.get(d, 0)
            up20 = ma20[i] > ma20[i - 5]
            sig = {"M0": True,
                   "M1": cl[i] > ma20[i] and up20 and rel >= 5}
            sig["M2"] = sig["M1"] and cl[i] <= hi5[i] * 0.97
            sig["M3"] = cl[i] < ma20[i] and (not up20) and rel <= -10
            sig["M4"] = sig["M3"] and chg[i] >= 3 and pd.notna(v5[i]) and vol[i] >= 1.5 * v5[i]
            for k, s in sig.items():
                if not s:
                    continue
                for h in (5, 10):
                    if i + h < len(cl):
                        R[k][env][h].append((cl[i + h] / cl[i] - 1) * 100)
    L.append(f"  样本股票：成功{ok}/{N} ｜ 区间约15个月 ｜ 强市＝沪深300>60日线")
    desc = {"M0": "对照：任意一天买", "M1": "强者恒强：站上向上20日线＋20日相对强≥5点",
            "M2": "强势股回踩3%再买", "M3": "抄底：向下20日线下方＋20日相对弱≥10点（我们过去的亏法）",
            "M4": "抄底＋放量长阳止跌信号"}

    def st(v):
        if not v:
            return "样本0"
        w = sum(1 for x in v if x > 0)
        s = sorted(v)
        return f"样本{len(v):>6} ｜ 平均{sum(v)/len(v):+.2f}% ｜ 中位{s[len(s)//2]:+.2f}% ｜ 胜率{w/len(v)*100:.0f}%"

    for k in ("M0", "M1", "M2", "M3", "M4"):
        L.append(f"\n◆ {k} {desc[k]}")
        for env, nm in (("strong", "强市"), ("weak", "弱市")):
            for h in (5, 10):
                L.append(f"   {nm} T+{h}：{st(R[k][env][h])}")
    L.append("\n  读法：和M0同环境同周期比；平均高≥1个点且胜率≥53%算有优势")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        L.append("🔴 失败：" + traceback.format_exc()[-800:])
    os.makedirs("reports", exist_ok=True)
    open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L))

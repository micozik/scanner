# -*- coding: utf-8 -*-
"""
练手命中率回测（2026-11-19 新建）
用户："你的模拟只有18%成功，你不想办法解决？"
问题：练手按"涨≥3%才算中"计分，但我们选股没有一套被回测验证过"能涨≥8%"的规则。
这里直接用练手的口径回测：入场=信号日收盘；10个交易日内
  先摸到 +8%（目标）= 中；先跌破 −5%（止损）= 错；都没到 = 平（按第10天收盘算收益）
同时给 T+5 收盘≥+3% 的比例（练手T+5打分口径）。
只看弱市（沪深300<60日线，当前环境）。样本：随机400只 × 约15个月。
变体（都在 M3 基础上：向下20日线下方 + 20日相对沪深300弱≥10点）：
  V0  对照：弱市任意一天
  V1  M3
  V2  M4 = M3 + 今日涨≥3% + 量≥5日均量1.5倍
  V3  M4 + 收在当日高位（收盘≥最低+80%振幅）
  V4  M3 + 60日高点回撤≥30%（深度超跌）
  V5  M4 + 60日高点回撤≥30%
  V6  M4 + 前5日累计跌≥8%（急跌后反抽）
  V7  M3 + 今日缩量（量<5日均量0.7）+ 收阳（地量止跌）
  V8  M4 + 今日涨幅3–7%（排除涨停买不到/过热）
输出 reports/练手命中率回测.txt
"""
import datetime, os, random, time, traceback
import akshare as ak
import pandas as pd

OUT = "reports/练手命中率回测.txt"
L = []
N = 400
EM_BAN = {"on": False}


def retry(f, n=4, wait=5):
    for k in range(n):
        try:
            return f()
        except Exception:
            if k == n - 1:
                raise
            time.sleep(wait * (k + 1))


def hist(c, start, end):
    if not EM_BAN["on"]:
        try:
            d = retry(lambda: ak.stock_zh_a_hist(symbol=c, period="daily", start_date=start, end_date=end, adjust="qfq"), n=2, wait=2)
            return pd.DataFrame({"d": pd.to_datetime(d["日期"]).dt.date, "o": d["开盘"].astype(float), "h": d["最高"].astype(float),
                                 "l": d["最低"].astype(float), "c": d["收盘"].astype(float), "v": d["成交量"].astype(float)})
        except Exception:
            EM_BAN["on"] = True
    mk = "sh" if c.startswith("6") else "sz"
    d = retry(lambda: ak.stock_zh_a_daily(symbol=mk + c, start_date=start, end_date=end, adjust="qfq"), n=2, wait=3)
    return pd.DataFrame({"d": pd.to_datetime(d["date"]).dt.date, "o": d["open"].astype(float), "h": d["high"].astype(float),
                         "l": d["low"].astype(float), "c": d["close"].astype(float), "v": d["volume"].astype(float)})


def main():
    bj = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
    L.append("=" * 72)
    L.append(f"🧪【练手命中率回测】北京 {bj}")
    L.append("   口径：收盘买入，10个交易日内先到+8%=中，先破−5%=错，都没到=平；只看弱市")
    L.append("=" * 72)
    idx = retry(lambda: ak.stock_zh_index_daily(symbol="sh000300"))
    idx["d"] = pd.to_datetime(idx["date"]).dt.date
    idx = idx.set_index("d")["close"].astype(float)
    ima60 = idx.rolling(60).mean()
    ir20 = idx.pct_change(20) * 100
    codes = retry(lambda: ak.stock_info_a_code_name())["code"].astype(str)
    codes = [c for c in codes if c[:2] in ("60", "00", "30", "68")]
    random.seed(11)
    codes = random.sample(codes, N)
    start = (datetime.date.today() - datetime.timedelta(days=460)).strftime("%Y%m%d")
    end = datetime.date.today().strftime("%Y%m%d")
    keys = ["V0", "V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8"]
    R = {k: [] for k in keys}   # (结果 '中'/'错'/'平', 10日收益, T+5≥3%)
    ok = 0
    for c in codes:
        try:
            df = hist(c, start, end)
            time.sleep(0.25)
        except Exception:
            time.sleep(1)
            continue
        if len(df) < 120:
            continue
        ok += 1
        cl, hi, lo, vo = df["c"], df["h"], df["l"], df["v"]
        ds = list(df["d"])
        ma20 = cl.rolling(20).mean()
        r20 = cl.pct_change(20) * 100
        v5 = vo.rolling(5).mean().shift(1)
        chg = cl.pct_change() * 100
        h60 = hi.rolling(60).max()
        r5p = cl.shift(1).pct_change(5) * 100     # 信号日前5日累计
        for i in range(60, len(cl) - 10):
            d = ds[i]
            if d not in idx.index or pd.isna(ima60.get(d)) or idx[d] > ima60[d]:
                continue                       # 只看弱市
            rel = r20[i] - ir20.get(d, 0)
            m3 = cl[i] < ma20[i] and ma20[i] < ma20[i - 5] and rel <= -10
            m4 = m3 and chg[i] >= 3 and pd.notna(v5[i]) and vo[i] >= 1.5 * v5[i]
            rng = hi[i] - lo[i]
            hipos = rng > 0 and cl[i] >= lo[i] + 0.8 * rng
            deep = cl[i] <= h60[i] * 0.7
            sig = {"V0": True, "V1": m3, "V2": m4, "V3": m4 and hipos, "V4": m3 and deep, "V5": m4 and deep,
                   "V6": m4 and pd.notna(r5p[i]) and r5p[i] <= -8,
                   "V7": m3 and pd.notna(v5[i]) and vo[i] < 0.7 * v5[i] and cl[i] > df["o"][i],
                   "V8": m4 and chg[i] <= 7}
            if not any(sig[k] for k in keys[1:]) and random.random() > 0.15:
                continue                       # 对照组抽样15%，省时间
            p = cl[i]
            res = "平"
            for j in range(i + 1, i + 11):
                if lo[j] <= p * 0.95:
                    res = "错"; break
                if hi[j] >= p * 1.08:
                    res = "中"; break
            r10 = (cl[i + 10] / p - 1) * 100
            t5 = cl[i + 5] / p - 1 >= 0.03
            for k, s in sig.items():
                if s:
                    R[k].append((res, r10, t5))
    L.append(f"  样本股票：成功{ok}/{N}（{'新浪日线' if EM_BAN['on'] else '东财日线'}）")
    desc = {"V0": "对照：弱市任意一天（抽样）", "V1": "M3 超跌", "V2": "M4 超跌+放量长阳", "V3": "M4+收在当日高位",
            "V4": "M3+60日回撤≥30%", "V5": "M4+60日回撤≥30%", "V6": "M4+前5日急跌≥8%",
            "V7": "M3+地量收阳", "V8": "M4+涨幅3–7%（买得到）"}
    L.append("\n  变体                      样本   中(+8%先到)  错(−5%先到)  平   T+5≥3%   10日平均")
    for k in keys:
        v = R[k]
        if not v:
            L.append(f"  {k} {desc[k]:<18} 样本0"); continue
        n = len(v)
        z = sum(1 for x in v if x[0] == "中") / n * 100
        e = sum(1 for x in v if x[0] == "错") / n * 100
        f = 100 - z - e
        t5 = sum(1 for x in v if x[2]) / n * 100
        av = sum(x[1] for x in v) / n
        L.append(f"  {k} {desc[k]:<18} {n:>6}   {z:5.1f}%      {e:5.1f}%     {f:4.1f}%  {t5:5.1f}%   {av:+.2f}%")
    L.append("\n  读法：'中'比对照高、'中/错'≥1 且 T+5≥3% 明显高于对照的变体，才能当练手主打法")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        L.append("🔴 失败：" + traceback.format_exc()[-800:])
    os.makedirs("reports", exist_ok=True)
    open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L))

# -*- coding: utf-8 -*-
"""
因子搜索（2026-11-03）：回测显示单靠"趋势单/超跌单"价格规则胜率只有~50%、每笔+0.4%，
离合格线（胜率70%、每笔+4%）很远。用算力在 800只×2.5年 上搜索 2~3 个条件的组合，
前60%时间段"训练"选规则，后40%时间段"检验"——只信检验段也好的规则（防过拟合）。
出场规则同 backtest.py（止损/目标/持有上限）。
"""
import os
import json
import time
import itertools
import datetime
from concurrent.futures import ThreadPoolExecutor

import backtest as bt

L = []


def w(s=""):
    L.append(str(s))
    print(s)


def rows_for(code, hsr):
    k = bt.kline(bt.mk(code))
    if len(k) < 200:
        return []
    call = [x["c"] for x in k]
    out = []
    i = 125
    while i < len(k) - 1:
        f = bt.feats(k, i, call)
        d = k[i]["d"]
        h = hsr.get(d)
        if not f or h is None:
            i += 1
            continue
        stop, tgt, rr = bt.stop_target(f, f["from_hi"] <= -25)
        r = bt.simulate(k, i, stop, tgt)
        if r is None:
            i += 1
            continue
        rng = k[i]["h"] - k[i]["l"]
        c = {
            "强市": h["up"], "弱市": not h["up"],
            "大盘5日跌>2%": h["d5"] < -2, "大盘5日涨>2%": h["d5"] > 2,
            "趋势单": bt.sig_trend(f), "超跌单": bt.sig_over(f),
            "站上MA20": f["last"] > f["ma20"], "MA20向上": f["ma20"] > f["ma20p"],
            "站上MA60": f["last"] > f["ma60"], "MA60>MA120": f["ma60"] > f["ma120"],
            "20日跑赢大盘>5": (f["last"] / call[i - 20] - 1) * 100 - h["d20"] > 5,
            "20日跑输大盘>5": (f["last"] / call[i - 20] - 1) * 100 - h["d20"] < -5,
            "5日涨0~5%": 0 <= f["d5"] <= 5, "5日跌>5%": f["d5"] < -5, "5日涨>10%": f["d5"] > 10,
            "今日涨2~5%": 2 <= f["pct"] <= 5, "今日跌>3%": f["pct"] < -3, "今日收红": f["pct"] > 0,
            "缩量(5/60<0.8)": f["volr"] is not None and f["volr"] < 0.8,
            "放量(5/60>1.5)": f["volr"] is not None and f["volr"] > 1.5,
            "距60日高<5%": f["from_hi"] > -5, "距60日高-15~-30%": -30 <= f["from_hi"] <= -15,
            "贴布林下轨": f["last"] <= f["boll_lo"] * 1.02, "贴布林上轨": f["last"] >= f["boll_hi"] * 0.98,
            "回踩MA20(±2%)": abs(f["last"] / f["ma20"] - 1) <= 0.02,
            "赔率≥2": rr >= 2, "收在日内高位": rng > 0 and (k[i]["c"] - k[i]["l"]) / rng >= 0.8,
            "收在日内低位": rng > 0 and (k[i]["c"] - k[i]["l"]) / rng <= 0.2,
            "ATR<2.5%": f["atr"] / f["last"] < 0.025,
        }
        out.append((d, r[0], frozenset(n for n, v in c.items() if v)))
        i += 3   # 每3天取一个样本，减少高度重叠
    return out


def st(rs):
    if not rs:
        return None
    wins = [r for r in rs if r > 0]
    loss = [r for r in rs if r <= 0]
    return {"n": len(rs), "wr": len(wins) / len(rs) * 100, "avg": sum(rs) / len(rs),
            "plr": (sum(wins) / len(wins)) / abs(sum(loss) / len(loss)) if wins and loss else None}


def main():
    t0 = time.time()
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    w("=" * 72)
    w("🔬【因子搜索】北京 %s ｜ 训练=前60%%时间 ｜ 检验=后40%%时间 ｜ 持有上限%d天" % (now.strftime("%Y-%m-%d %H:%M"), bt.HOLD))
    w("=" * 72)
    hs = bt.kline("sh000300")
    hsr = {}
    for i in range(60, len(hs)):
        c = hs[i]["c"]
        hsr[hs[i]["d"]] = {"up": c > sum(x["c"] for x in hs[i - 59:i + 1]) / 60,
                           "d5": (c / hs[i - 5]["c"] - 1) * 100, "d20": (c / hs[i - 20]["c"] - 1) * 100}
    last = hs[-1]["d"]
    cur = hsr.get(last, {})
    w("当前大盘（%s）：沪深300 %s60日线 ｜ 5日%+.1f%% ｜ 20日%+.1f%% → %s" % (
        last, "在" if cur.get("up") else "跌破", cur.get("d5", 0), cur.get("d20", 0), "强市" if cur.get("up") else "弱市"))
    codes = bt.universe()
    data = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        for rs in ex.map(lambda c: rows_for(c, hsr), codes):
            data += rs
    ds = sorted(set(d for d, _, _ in data))
    cut = ds[int(len(ds) * 0.6)]
    tr = [(r, c) for d, r, c in data if d < cut]
    te = [(r, c) for d, r, c in data if d >= cut]
    w("样本：%d（训练%d / 检验%d，分界%s）" % (len(data), len(tr), len(te), cut))
    b1, b2 = st([r for r, _ in tr]), st([r for r, _ in te])
    w("基准（全部样本）：训练 胜率%.0f%% 均%+.2f%% ｜ 检验 胜率%.0f%% 均%+.2f%%" % (b1["wr"], b1["avg"], b2["wr"], b2["avg"]))
    import numpy as np
    names = sorted(set().union(*[c for _, _, c in data]))
    ni = {n: j for j, n in enumerate(names)}

    def mat(rows):
        M = np.zeros((len(rows), len(names)), dtype=bool)
        R = np.array([r for r, _ in rows], dtype=float)
        for i, (_, c) in enumerate(rows):
            for n in c:
                M[i, ni[n]] = True
        return M, R
    Mtr, Rtr = mat(tr)
    Mte, Rte = mat(te)

    def stm(R):
        if len(R) == 0:
            return None
        wv, lv = R[R > 0], R[R <= 0]
        return {"n": int(len(R)), "wr": float((R > 0).mean() * 100), "avg": float(R.mean()),
                "plr": float(wv.mean() / abs(lv.mean())) if len(wv) and len(lv) else None}
    cands = []
    for k_ in (1, 2, 3):
        for combo in itertools.combinations(range(len(names)), k_):
            m = Mtr[:, list(combo)].all(axis=1)
            n = int(m.sum())
            if n < 300:
                continue
            a = Rtr[m]
            if a.mean() < b1["avg"] + 0.8:
                continue
            cands.append((float(a.mean()), combo, stm(a)))
    cands.sort(key=lambda x: -x[0])
    w("")
    w("【训练段最好的组合 → 检验段表现】（训练≥300笔；检验段也≥100笔且仍跑赢基准0.5点才算可信）")
    w("  组合                                         训练:笔/胜率/均     检验:笔/胜率/均/盈亏比   可信")
    good = []
    for avg, combo, sa in cands[:60]:
        m = Mte[:, list(combo)].all(axis=1)
        sb = stm(Rte[m])
        ok = sb and sb["n"] >= 100 and sb["avg"] > b2["avg"] + 0.5
        nm = [names[j] for j in combo]
        if ok:
            good.append((nm, sa, sb))
        w("  %-44s %5d/%3.0f%%/%+5.2f%%   %s  %s" % (
            "+".join(nm), sa["n"], sa["wr"], sa["avg"],
            ("%5d/%3.0f%%/%+5.2f%%/%s" % (sb["n"], sb["wr"], sb["avg"], ("%.2f" % sb["plr"]) if sb["plr"] else "—")) if sb else "—",
            "✅" if ok else "❌"))
    w("")
    w("【可信规则（检验段仍有效）】%d 条" % len(good))
    for combo, sa, sb in sorted(good, key=lambda x: -x[2]["avg"])[:15]:
        w("  ✅ %s ｜ 检验：%d笔 胜率%.0f%% 每笔%+.2f%%" % ("+".join(combo), sb["n"], sb["wr"], sb["avg"]))
    w("")
    w("⚠️ 价格规则只是七关中的一关；最终买卖仍需过 世界/行情/板块/资金/反方 各关")
    w("耗时 %.0f 秒" % (time.time() - t0))
    os.makedirs("reports", exist_ok=True)
    with open("reports/因子搜索.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
历史回测（2026-11-03 新建，用户："把不具备的能力，利用你的强大算力，补全"）
把查股票里"能用价格回测"的规则，在 沪深300+中证500 成分股约2.5年日K上跑一遍，
不用等几个月样本，直接拿到胜率 / 每笔平均 / 盈亏比 / 连亏，并和"随便买"基准、沪深300比。

买卖规则（和查股票一致）：
  信号日 D 收盘满足条件 → D+1 开盘买（扣双边成本0.2%）
  止损 = max(现价−2ATR, MA20×0.97(若MA20<现价), 60日低×0.97)，且不高于 现价−1.2ATR；超跌单止损=60日低×0.97
  目标 = 第一道 ≥+3% 的压力位（20日高/MA60/MA120/60日高/布林上轨），没有则 现价+3ATR
  当天最低碰止损→止损价出（跳空低开则开盘价出）；最高碰目标→目标价出；都没碰→持有满 HOLD 天收盘出
  同一只股票持仓期间不重复开仓
所有数字是历史统计，不是承诺；样本外（未来）可能变差。
"""
import os
import json
import time
import datetime
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HOLD = int(os.environ.get("HOLD", "10"))
BARS = 640
COST = 0.2
L = []


def w(s=""):
    L.append(str(s))
    print(s)


def mk(code):
    return ("sh" if code.startswith(("6", "9")) and not code.startswith("92")
            else ("bj" if code[:2] in ("92", "83", "87", "43") else "sz")) + code


def kline(sym):
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=%s,day,,,%d,qfq" % (sym, BARS)
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"})
            d = json.loads(urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "ignore"))["data"][sym]
            rows = d.get("qfqday") or d.get("day") or []
            out = []
            for r in rows:
                out.append({"d": r[0], "o": float(r[1]), "c": float(r[2]), "h": float(r[3]),
                            "l": float(r[4]), "v": float(r[5])})
            return out
        except Exception:
            time.sleep(1 + i)
    return []


def universe():
    codes = []
    try:
        import akshare as ak
        for idx in ("000300", "000905"):
            df = None
            for fn in (lambda: ak.index_stock_cons_csindex(symbol=idx), lambda: ak.index_stock_cons(symbol=idx)):
                try:
                    df = fn()
                    if df is not None and len(df):
                        break
                except Exception:
                    df = None
            if df is not None:
                c = [x for x in df.columns if "代码" in str(x) and "指数" not in str(x)] or [df.columns[0]]
                codes += [str(x).zfill(6)[-6:] for x in df[c[0]]]
    except Exception as e:
        w("成分股获取失败 %s" % str(e)[:60])
    codes = sorted(set(c for c in codes if c.isdigit()))
    return codes


def feats(k, i, call=None):
    """第 i 根K线收盘时的指标（只用 i 及以前的数据，避免偷看未来）"""
    if i < 125:
        return None
    cs = (call or [x["c"] for x in k])[i - 124:i + 1]
    last = cs[-1]
    c60 = cs[-60:]
    ma20 = sum(cs[-20:]) / 20
    ma20p = sum(cs[-25:-5]) / 20
    sd = (sum((x - ma20) ** 2 for x in cs[-20:]) / 20) ** 0.5
    trs = []
    for j in range(i - 13, i + 1):
        trs.append(max(k[j]["h"] - k[j]["l"], abs(k[j]["h"] - k[j - 1]["c"]), abs(k[j]["l"] - k[j - 1]["c"])))
    atr = sum(trs) / len(trs)
    v5 = sum(x["v"] for x in k[i - 4:i + 1]) / 5
    v60 = sum(x["v"] for x in k[i - 59:i + 1]) / 60
    f = {"last": last, "ma20": ma20, "ma20p": ma20p, "ma60": sum(c60) / 60, "ma120": sum(cs[-120:]) / 120,
         "hi": max(c60), "lo": min(c60), "d5": (last / cs[-6] - 1) * 100, "pct": (last / cs[-2] - 1) * 100,
         "boll_lo": ma20 - 2 * sd, "boll_hi": ma20 + 2 * sd, "atr": atr,
         "hi20": max(x["h"] for x in k[i - 19:i + 1]), "volr": v5 / v60 if v60 else None}
    f["from_hi"] = (last / f["hi"] - 1) * 100
    f["from_lo"] = (last / f["lo"] - 1) * 100
    return f


def sig_trend(f):
    return f["last"] > f["ma20"] and f["ma20"] > f["ma20p"] and f["d5"] <= 15 and f["pct"] <= 4


def sig_over(f):
    b2 = f["from_lo"] <= 5 or f["last"] <= f["boll_lo"] * 1.02
    b3 = (f["volr"] is not None and f["volr"] <= 1.0) or f["pct"] > 0
    return f["from_hi"] <= -25 and b2 and b3


def stop_target(f, over=False):
    last, atr = f["last"], f["atr"]
    if over:
        stop = f["lo"] * 0.97
    else:
        stop = max(last - 2 * atr, f["ma20"] * 0.97 if f["ma20"] < last else 0, f["lo"] * 0.97)
        stop = min(stop, last - 1.2 * atr)
    rs = sorted(x for x in (f["hi20"], f["ma60"], f["ma120"], f["hi"], f["boll_hi"]) if x >= last * 1.03)
    tgt = rs[0] if rs else last + 3 * atr
    rr = (tgt - last) / (last - stop) if last > stop else 0
    return stop, tgt, rr


def simulate(k, i, stop, tgt):
    """D=i 收盘信号，D+1 开盘买"""
    if i + 1 >= len(k):
        return None
    e = k[i + 1]["o"]
    if e <= stop:
        return None
    for j in range(i + 1, min(i + 1 + HOLD, len(k))):
        b = k[j]
        if j > i + 1 and b["o"] <= stop:
            return (b["o"] / e - 1) * 100 - COST, j - i, "止损(跳空)", j
        if b["l"] <= stop:
            return (stop / e - 1) * 100 - COST, j - i, "止损", j
        if b["h"] >= tgt:
            return (max(tgt, b["o"]) / e - 1) * 100 - COST, j - i, "目标", j
    j = i + HOLD
    if j > len(k) - 1:
        return None   # 还没走完，不计
    return (k[j]["c"] / e - 1) * 100 - COST, j - i, "到期", j


STRATS = {
    "A趋势单": lambda f: sig_trend(f),
    "A趋势单+赔率≥2": lambda f: sig_trend(f) and stop_target(f)[2] >= 2,
    "A趋势单+赔率≥2+5日缩量": lambda f: sig_trend(f) and stop_target(f)[2] >= 2 and f["volr"] is not None and f["volr"] <= 1.0,
    "A趋势单+回踩MA10附近": lambda f: sig_trend(f) and f["last"] <= f["ma20"] * 1.03,
    "B超跌单": lambda f: sig_over(f),
    "B超跌单+赔率≥2": lambda f: sig_over(f) and stop_target(f, True)[2] >= 2,
    "基准:随便买(每20天抽一次)": None,
}


def run_one(code):
    k = kline(mk(code))
    if len(k) < 200:
        return code, {}
    res = {s: [] for s in STRATS}
    call = [x["c"] for x in k]
    FF = {i: feats(k, i, call) for i in range(125, len(k) - 1)}
    for s, fn in STRATS.items():
        busy = -1
        for i in range(125, len(k) - 1):
            if i <= busy:
                continue
            f = FF[i]
            if not f:
                continue
            if fn is None:
                if i % 20 != 0:
                    continue
                over = False
            else:
                if not fn(f):
                    continue
                over = s.startswith("B")
            stop, tgt, rr = stop_target(f, over)
            r = simulate(k, i, stop, tgt)
            if r:
                res[s].append({"d": k[i]["d"], "ret": r[0], "days": r[1], "why": r[2]})
                busy = r[3]
    return code, res


def stats(tr):
    if not tr:
        return None
    rs = [t["ret"] for t in sorted(tr, key=lambda x: x["d"])]
    wins = [r for r in rs if r > 0]
    loss = [r for r in rs if r <= 0]
    st = mx = 0
    for r in rs:
        st = st + 1 if r <= 0 else 0
        mx = max(mx, st)
    return {"n": len(rs), "wr": len(wins) / len(rs) * 100, "avg": sum(rs) / len(rs),
            "plr": (sum(wins) / len(wins)) / abs(sum(loss) / len(loss)) if wins and loss else None,
            "days": sum(t["days"] for t in tr) / len(tr),
            "tgt": sum(1 for t in tr if t["why"] == "目标") / len(tr) * 100,
            "stop": sum(1 for t in tr if t["why"].startswith("止损")) / len(tr) * 100}


def main():
    t0 = time.time()
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    w("=" * 70)
    w("🧪【历史回测】北京 %s ｜ 持有上限%d天 ｜ 成本%.1f%%" % (now.strftime("%Y-%m-%d %H:%M"), HOLD, COST))
    w("=" * 70)
    codes = universe()
    if not codes:
        w("🔴 拿不到成分股，回测中止")
        return
    w("股票池：沪深300+中证500 共%d只 ｜ 每只约%d根日K" % (len(codes), BARS))
    allr = {s: [] for s in STRATS}
    with ThreadPoolExecutor(max_workers=12) as ex:
        for code, res in ex.map(run_one, codes):
            for s, tr in res.items():
                for t in tr:
                    t["code"] = code
                allr[s] += tr
    hs = kline("sh000300")
    regime = {}
    for i in range(60, len(hs)):
        regime[hs[i]["d"]] = hs[i]["c"] > sum(x["c"] for x in hs[i - 59:i + 1]) / 60
    if hs:
        w("同期沪深300：%s → %s，%+.1f%%" % (hs[125]["d"], hs[-1]["d"], (hs[-1]["c"] / hs[125]["c"] - 1) * 100))
    w("")
    w("  策略                       笔数   胜率   每笔平均  盈亏比  平均持有  到目标  止损")
    for s in STRATS:
        x = stats(allr[s])
        if not x:
            w("  %-24s 无样本" % s)
            continue
        w("  %-24s %5d  %4.0f%%  %+6.2f%%   %s   %4.1f天  %4.0f%%  %4.0f%%" % (
            s, x["n"], x["wr"], x["avg"], ("%.2f" % x["plr"]) if x["plr"] else " — ", x["days"], x["tgt"], x["stop"]))
    w("")
    w("【分大盘环境】沪深300在60日线上=牛/震荡偏强；线下=弱市")
    for s in STRATS:
        up = [t for t in allr[s] if regime.get(t["d"]) is True]
        dn = [t for t in allr[s] if regime.get(t["d"]) is False]
        a, b = stats(up), stats(dn)
        if a or b:
            w("  %-24s 强市：%s ｜ 弱市：%s" % (s,
                ("%d笔 胜率%.0f%% 均%+.2f%%" % (a["n"], a["wr"], a["avg"])) if a else "—",
                ("%d笔 胜率%.0f%% 均%+.2f%%" % (b["n"], b["wr"], b["avg"])) if b else "—"))
    w("")
    w("【合格线】（七关文档第五节）胜率≥70% 且 每笔平均≥+4%（中线单）——达不到的规则不许单独作为买入依据")
    w("  ⚠️ 回测只能检验价格规则；政策/资金/故事三关无法回测，靠建议账本实盘对账")
    w("  耗时 %.0f 秒" % (time.time() - t0))
    os.makedirs("reports", exist_ok=True)
    with open("reports/回测结果.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    try:
        summ = {s: stats(allr[s]) for s in STRATS}
        json.dump({"made": now.strftime("%Y-%m-%d %H:%M"), "hold": HOLD, "stats": summ},
                  open("reports/回测结果.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception:
        pass


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
选股命中率（2026-11-03 新建）
用户："赚钱才是你唯一目的……你要记录你选中的股票，当你的样本够多，你才能计算你的命中率"

读 reports/picks/*.json（每次查股票的★综合结论★）+ reports/zt_hit.json（涨停猎手对账）
→ 每条样本按"当天首次结论"去重，用腾讯日K算之后 T+1/T+3/T+5/T+10 收益、
  先碰止损还是先碰目标 → 按结论（可买/观察/不买）分组统计 → reports/选股命中率.txt
判断标准：🟢可买 的 T+5 胜率和平均收益 必须明显好于 🔴不买，否则打分规则要改。
"""
import os
import json
import glob
import datetime
import urllib.request


def bj_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=8)


def mk(code):
    return ("sh" if code.startswith(("6", "9")) and not code.startswith("92")
            else ("bj" if code[:2] in ("92", "83", "87", "43") else "sz")) + code


_K = {}


def kline(code):
    if code in _K:
        return _K[code]
    m = mk(code)
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=%s,day,,,80,qfq" % m
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"})
        d = json.loads(urllib.request.urlopen(req, timeout=8).read().decode("utf-8", "ignore"))["data"][m]
        rows = d.get("qfqday") or d.get("day") or []
        k = [(r[0], float(r[2]), float(r[3]), float(r[4]), float(r[1])) for r in rows]   # 日期 收 高 低 开
    except Exception:
        k = []
    _K[code] = k
    return k


def main():
    L = []
    w = L.append
    now = bj_now()
    w("=" * 64)
    w("📒【选股命中率】北京 %s" % now.strftime("%Y-%m-%d %H:%M"))
    w("   样本=每次查股票的★综合结论★（同一天同一只取当天第一次结论）")
    w("=" * 64)
    seen = {}
    for fn in sorted(glob.glob("reports/picks/*.json")):
        try:
            for p in json.load(open(fn, encoding="utf-8")):
                key = (p["t"][:10], p["code"])
                if key not in seen and p.get("price"):
                    seen[key] = p
        except Exception:
            pass
    samples = list(seen.values())
    groups = {}
    detail = []
    for p in samples:
        k = kline(p["code"])
        d0 = p["t"][:10]
        idx = [i for i, r in enumerate(k) if r[0] > d0]   # 结论之后的交易日
        res = {"T+1": None, "T+3": None, "T+5": None, "T+10": None, "first": "未触发"}
        for n in (1, 3, 5, 10):
            if len(idx) >= n:
                res["T+%d" % n] = (k[idx[n - 1]][1] / p["price"] - 1) * 100
        st, tg = p.get("stop"), p.get("target")
        for i in idx:
            _, c, h, l_ = k[i][:4]
            if st and l_ <= st:
                res["first"] = "先碰止损"
                break
            if tg and h >= tg:
                res["first"] = "先到目标"
                break
        v = p.get("verdict", "?")
        groups.setdefault(v, []).append(res)
        detail.append((p, res))
    w("")
    w("样本 %d 条（%d 只股票，%d 个交易日）" % (len(samples), len(set(p["code"] for p in samples)),
                                        len(set(p["t"][:10] for p in samples))))
    w("")
    w("【按结论分组】")
    w("  结论   条数  T+1均   T+3均   T+5均   T+5胜率  T+10均  先到目标/先碰止损")
    for v in sorted(groups):
        rs = groups[v]

        def avg(key):
            xs = [r[key] for r in rs if r[key] is not None]
            return (sum(xs) / len(xs), len(xs)) if xs else (None, 0)
        a1, a3, a5, a10 = avg("T+1"), avg("T+3"), avg("T+5"), avg("T+10")
        x5 = [r["T+5"] for r in rs if r["T+5"] is not None]
        wr = (sum(1 for x in x5 if x > 0) / len(x5) * 100) if x5 else None
        ft = sum(1 for r in rs if r["first"] == "先到目标")
        fs = sum(1 for r in rs if r["first"] == "先碰止损")
        f = lambda t: ("%+6.2f%%" % t[0]) if t[0] is not None else "   —  "
        w("  %-4s %4d  %s %s %s  %s  %s   %d/%d" % (v, len(rs), f(a1), f(a3), f(a5),
                                                ("%5.0f%%" % wr) if wr is not None else "  —  ", f(a10), ft, fs))
    w("")
    w("  ⚠️ 每组T+5样本<20条时结论不可信")
    w("  ★🟢可买 合格标准：T+5胜率≥60% 且 T+5平均≥+2% 且 比🔴不买组高≥2个点 且 先到目标>先碰止损 —— 达不到就改打分规则")
    # ★11/03 用户："高于15%你觉得就成功？代表我有85%失败" → 涨停命中率只是辅助，
    #   真正的成绩=按规则买卖的模拟交易：胜率、平均每笔收益、盈亏比
    #   规则：D日收盘预测 → D+1 开盘高开在区间内才买（主板+2~+7%，20cm +3~+10%）
    #         → 当天最低碰到 昨收×0.97 止损；否则 D+2 开盘卖出（接力单不恋战）
    w("")
    w("【涨停接力·模拟交易】（买卖规则见代码注释；扣双边成本0.2%）")
    trades = []
    for fn in sorted(glob.glob("reports/zt_pred/*.json")):
        try:
            pdj = json.load(open(fn, encoding="utf-8"))
        except Exception:
            continue
        d0 = pdj.get("date", "")
        d0s = "%s-%s-%s" % (d0[:4], d0[4:6], d0[6:8])
        for x in pdj.get("top", [])[:8]:
            k = kline(x["code"])
            i0 = [i for i, r in enumerate(k) if r[0] == d0s]
            if not i0 or i0[0] + 1 >= len(k):
                continue
            i = i0[0]
            prev = k[i][1]
            o1, c1, h1, l1 = k[i + 1][4], k[i + 1][1], k[i + 1][2], k[i + 1][3]
            gap = (o1 / prev - 1) * 100
            big = x["code"].startswith(("30", "68"))
            lo, hi = (3, 10) if big else (2, 7)
            if not (lo <= gap <= hi):
                trades.append((d0, x, gap, None, "未买(竞价不符)"))
                continue
            stop = prev * 0.97
            if l1 <= stop:
                ret = (stop / o1 - 1) * 100 - 0.2
                why = "当天止损"
            elif i + 2 < len(k):
                ret = (k[i + 2][4] / o1 - 1) * 100 - 0.2
                why = "次日开盘卖"
            else:
                trades.append((d0, x, gap, None, "持有中(待次日)"))
                continue
            trades.append((d0, x, gap, ret, why))
    done = [t for t in trades if t[3] is not None]
    if done:
        rs = [t[3] for t in done]
        wins = [r for r in rs if r > 0]
        loss = [r for r in rs if r <= 0]
        wr = len(wins) / len(rs) * 100
        avg = sum(rs) / len(rs)
        plr = (sum(wins) / len(wins)) / abs(sum(loss) / len(loss)) if wins and loss else None
        w("  成交%d笔（另有%d只竞价不符没买）｜ 胜率%.0f%% ｜ 每笔平均%+.2f%% ｜ 盈亏比%s" % (
            len(done), sum(1 for t in trades if t[4].startswith("未买")), wr, avg, ("%.2f" % plr) if plr else "—"))
        w("  ★可用标准：成交≥30笔 且 胜率≥55% 且 每笔平均≥+1% 且 盈亏比≥1.5 —— 达不到不许重仓")
        for d0, x, gap, ret, why in done[-10:]:
            w("    %s %s(%s) 高开%+.1f%% → %+.2f%% %s" % (d0, x["name"], x["code"], gap, ret, why))
    else:
        w("  还没有成交样本（预测后需要2个交易日才能结算）")
    try:
        zh = json.load(open("reports/zt_hit.json", encoding="utf-8"))
        n = sum(v["n"] for v in zh.values())
        h = sum(v["hit"] for v in zh.values())
        ap = [v["avg_pct"] for v in zh.values() if v.get("avg_pct") is not None]
        w("")
        w("【涨停猎手·辅助】%d天 预测%d只 次日涨停%d只 涨停命中率%s（只是辅助，不是成绩）｜ 次日平均%s" % (
            len(zh), n, h, ("%.0f%%" % (h / n * 100)) if n else "—", ("%+.2f%%" % (sum(ap) / len(ap))) if ap else "—"))
    except Exception:
        w("")
        w("【涨停猎手】还没有对账数据")
    w("")
    w("【最近20条明细】")
    for p, r in sorted(detail, key=lambda x: x[0]["t"])[-20:]:
        w("  %s %s(%s) %s 结论价%.2f ｜ T+1 %s T+5 %s ｜ %s" % (
            p["t"], p.get("name"), p["code"], p.get("verdict"), p["price"],
            ("%+.1f%%" % r["T+1"]) if r["T+1"] is not None else "—",
            ("%+.1f%%" % r["T+5"]) if r["T+5"] is not None else "—", r["first"]))
    os.makedirs("reports", exist_ok=True)
    with open("reports/选股命中率.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()

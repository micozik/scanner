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
        k = [(r[0], float(r[2]), float(r[3]), float(r[4])) for r in rows]   # 日期 收 高 低
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
            _, c, h, l_ = k[i]
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
    w("  ⚠️ 每组T+5样本<20条时结论不可信；🟢可买 若不明显好于 🔴不买 → 打分规则要改")
    try:
        zh = json.load(open("reports/zt_hit.json", encoding="utf-8"))
        n = sum(v["n"] for v in zh.values())
        h = sum(v["hit"] for v in zh.values())
        ap = [v["avg_pct"] for v in zh.values() if v.get("avg_pct") is not None]
        w("")
        w("【涨停猎手】%d天 预测%d只 次日涨停%d只 命中率%s ｜ 次日平均%s" % (
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

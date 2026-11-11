# -*- coding: utf-8 -*-
"""
决策记分（2026-11-11 新建，用户："你要继续进化…已经过好多个月了，你依旧失败"）

为什么：选股命中率只统计"查股票"的结论；但真正决定账户盈亏的是我给用户的每一个动作
（买/卖/不买/撤单/持有）。这里把每个动作记下来，T+1/T+3/T+5 自动打分，每周看我到底对了几成。

输入：backup/决策记分.csv（每行一个动作）
  时间,代码,名称,动作,价格,理由
  动作取值：买 / 卖 / 不买 / 撤单 / 持有
打分口径：
  买、持有：之后涨=对，跌=错
  卖、不买、撤单：之后跌=对，涨=错（卖了它又涨=卖错）
  |涨跌| < 1% 记"平"
输出：reports/决策记分.txt
"""
import csv, json, os, time, datetime, urllib.request

SRC = "backup/决策记分.csv"
OUT = "reports/决策记分.txt"


def kline(code):
    mk = "sh" if code.startswith(("6", "9")) else ("bj" if code.startswith(("8", "4", "92")) else "sz")
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={mk}{code},day,,,60,qfq"
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"})
            d = json.loads(urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "ignore"))["data"][mk + code]
            rows = d.get("qfqday") or d.get("day") or []
            return [(r[0], float(r[2])) for r in rows]
        except Exception:
            time.sleep(1 + i)
    return []


def main():
    if not os.path.exists(SRC):
        print("无决策记分.csv"); return
    rows = list(csv.DictReader(open(SRC, encoding="utf-8")))
    cache, L = {}, []
    stat = {}
    L.append("=" * 70)
    L.append("🎯【决策记分】北京 %s ｜ 共 %d 个动作" % ((datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M"), len(rows)))
    L.append("口径：买/持有→之后涨=对；卖/不买/撤单→之后跌=对；|涨跌|<1%=平")
    L.append("=" * 70)
    for r in rows:
        code = r["代码"].strip()
        if code not in cache:
            cache[code] = kline(code)
        k = cache[code]
        day = r["时间"][:10]
        px = float(r["价格"])
        after = [c for d, c in k if d > day]
        res = []
        for h in (1, 3, 5):
            if len(after) >= h:
                chg = (after[h - 1] / px - 1) * 100
                good = chg > 1 if r["动作"] in ("买", "持有") else chg < -1
                flat = abs(chg) < 1
                tag = "平" if flat else ("对" if good else "错")
                res.append(f"T+{h} {chg:+.1f}% {tag}")
                if h in (1, 5):
                    st = stat.setdefault((r["动作"] if r["动作"] in ("买", "持有") else "卖类", h), [0, 0, 0])
                    st[0 if tag == "对" else (1 if tag == "错" else 2)] += 1
            else:
                res.append(f"T+{h} —")
        L.append(f"{r['时间']} {r['名称']}({code}) {r['动作']}@{px} ｜ " + " ｜ ".join(res) + f" ｜ {r.get('理由','')[:30]}")
    L.append("\n—— 汇总（对/错/平）——")
    for (a, h), (g, b, f) in sorted(stat.items()):
        n = g + b
        L.append(f"  {a} T+{h}：对{g} 错{b} 平{f} ｜ 判对率 {g/n*100:.0f}%" if n else f"  {a} T+{h}：样本不足")
    os.makedirs("reports", exist_ok=True)
    open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()

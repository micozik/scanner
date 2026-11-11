# -*- coding: utf-8 -*-
"""
板块月榜（2026-11-11 新建，用户："板块统计排名，我觉得起码1个月的板块数据排名"）

数据：reports/top_sectors.json（同花顺90个行业，每天收盘涨幅+排名，扫描器盘后写入）
     reports/sector_flow_hist.json（同花顺行业每日主力净流入，亿元）
做法：去掉重复日（节假日/盘前跑写入的同一份数据），取最近 N=22 个交易日（≈1个月）
输出：reports/板块月榜.txt
  - 月度强弱总榜（按1个月累计涨幅）：今天｜5日｜10日｜1个月｜进前10天数｜上涨天数｜平均排名｜排名趋势｜1个月资金
  - 月度最弱榜
  - 稳定性榜（1个月里进前10天数最多的＝持续主线）
  - 加速榜（近5日平均排名比前面明显靠前的＝正在变强）
"""
import json, os, datetime

N = 22
IND = "reports/top_sectors.json"
FLOW = "reports/sector_flow_hist.json"
OUT = "reports/板块月榜.txt"


def load_days():
    d = json.load(open(IND, encoding="utf-8"))["days"]
    out, prev_sig = [], None
    for k in sorted(d):
        day = d[k]
        try:
            if datetime.date.fromisoformat(k).weekday() >= 5:
                continue
        except Exception:
            pass
        sig = tuple(sorted((n, v.get("pct")) for n, v in day.items()))
        if sig == prev_sig:          # 和上一天一模一样＝非交易日/重复写入
            continue
        prev_sig = sig
        out.append((k, day))
    return out


def main():
    days = load_days()[-N:]
    flows = {}
    if os.path.exists(FLOW):
        flows = json.load(open(FLOW, encoding="utf-8"))
    names = set()
    for _, day in days:
        names |= set(day)
    nd = len(days)
    rows = []
    for nm in names:
        pcts = [day.get(nm, {}).get("pct") for _, day in days]
        rks = [day.get(nm, {}).get("rank") for _, day in days]
        if sum(p is not None for p in pcts) < nd * 0.7:
            continue

        def cum(seq):
            v = 1.0
            for p in seq:
                if p is not None:
                    v *= 1 + p / 100
            return (v - 1) * 100

        tot = len(days[-1][1]) or 90
        rk_valid = [r for r in rks if r is not None]
        last5 = [r for r in rks[-5:] if r is not None]
        early = [r for r in rks[:-5] if r is not None]
        fl = [flows.get(k, {}).get(nm) for k, _ in days]
        fl_sum = sum(x for x in fl if x is not None)
        fl_n = sum(x is not None for x in fl)
        rows.append(dict(
            nm=nm,
            today=pcts[-1], rk_today=rks[-1],
            d5=cum(pcts[-5:]), d10=cum(pcts[-10:]), m1=cum(pcts),
            top10=sum(1 for r in rk_valid if r <= 10),
            up=sum(1 for p in pcts if p is not None and p > 0),
            avg=sum(rk_valid) / len(rk_valid) if rk_valid else tot,
            a5=sum(last5) / len(last5) if last5 else tot,
            a_early=sum(early) / len(early) if early else tot,
            flow=fl_sum, fl_n=fl_n,
        ))

    def trend(r):
        dlt = r["a_early"] - r["a5"]
        if dlt >= 15:
            return f"⬆️加速({r['a_early']:.0f}→{r['a5']:.0f})"
        if dlt <= -15:
            return f"⬇️走弱({r['a_early']:.0f}→{r['a5']:.0f})"
        return f"➡️({r['a_early']:.0f}→{r['a5']:.0f})"

    def line(i, r):
        fl = f"{r['flow']:+.0f}亿({r['fl_n']}天)" if r["fl_n"] else "—"
        td = f"{r['today']:+.1f}%(第{r['rk_today']})" if r["today"] is not None else "—"
        return (f"  {i:>2}. {r['nm']:<8}｜今天{td}｜5日{r['d5']:+.1f}%｜10日{r['d10']:+.1f}%｜"
                f"1个月{r['m1']:+.1f}%｜进前10 {r['top10']}天｜涨{r['up']}/{nd}天｜均排第{r['avg']:.0f}｜{trend(r)}｜资金{fl}")

    L = []
    bj = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
    L.append("=" * 78)
    L.append(f"📊【板块月榜】北京 {bj} ｜ 同花顺{len(rows)}个行业 ｜ 最近{nd}个交易日 {days[0][0]} → {days[-1][0]}")
    L.append("   累计涨幅＝每天收盘涨幅连乘；排名趋势＝前面平均排名→近5日平均排名；资金＝同花顺主力净流入合计（有记录的天数）")
    L.append("=" * 78)
    rows.sort(key=lambda r: -r["m1"])
    L.append("\n【一、1个月强势榜 Top20】（按1个月累计涨幅）")
    for i, r in enumerate(rows[:20], 1):
        L.append(line(i, r))
    L.append("\n【二、1个月最弱榜 Bottom10】")
    for i, r in enumerate(rows[::-1][:10], 1):
        L.append(line(i, r))
    st = sorted(rows, key=lambda r: (-r["top10"], r["avg"]))
    L.append("\n【三、稳定性榜：1个月里进前10天数最多（＝持续主线，不是一日游）】")
    for i, r in enumerate(st[:12], 1):
        L.append(line(i, r))
    ac = sorted(rows, key=lambda r: -(r["a_early"] - r["a5"]))
    L.append("\n【四、加速榜：近5日排名比前面明显靠前（＝正在变强，可能是新主线）】")
    for i, r in enumerate([r for r in ac if r["a_early"] - r["a5"] >= 15][:12], 1):
        L.append(line(i, r))
    dc = [r for r in ac[::-1] if r["a_early"] - r["a5"] <= -15]
    L.append("\n【五、退潮榜：近5日排名比前面明显靠后（＝资金在撤）】")
    for i, r in enumerate(dc[:10], 1):
        L.append(line(i, r))
    fl = sorted([r for r in rows if r["fl_n"]], key=lambda r: -r["flow"])
    L.append("\n【六、1个月资金榜】净流入前10 ／ 净流出前10")
    for i, r in enumerate(fl[:10], 1):
        L.append(line(i, r))
    L.append("  ……")
    for i, r in enumerate(fl[::-1][:10], 1):
        L.append(line(i, r))
    os.makedirs("reports", exist_ok=True)
    open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()

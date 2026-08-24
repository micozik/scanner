# -*- coding: utf-8 -*-
"""V32.0 补丁 · 【跳升榜回测】—— 找真正能抓涨停的规律

2026-08-24 用户：
  『你要努力地想办法去找到这个A股市场的规律，
    给我抓一些能够大涨的股，甚至于每天给我抓涨停板。』
  『但不是为了抓涨停而拼命找那些已经涨停的股票让我买进去，
    我也买不进去啊。你要找到规律。』

★AI今天的错：推"算电协同链"的协鑫能科 —— 一字板封单8.37亿，
  用户根本买不到。这不是抓机会，是事后描述。

★真正要验证的假设：
  【板块跳升≥300位 且 当天涨幅<2%】= 资金刚进来、价格还没动
  → 次日/3日后，这个板块会不会出现涨停？
  → 如果成立，今天买、明天就在涨停板里面（而不是追）

本补丁用 reports/top_sectors.json 和 top_concepts.json 的历史，
回测这个假设，用数据说话。有效就每天用，无效就废掉。
"""
import io
import os

P = "scanner_cloud.py"
if not os.path.exists(P):
    print("no scanner_cloud.py")
    raise SystemExit(0)
s = io.open(P, encoding="utf-8").read()
n = 0

FUNC = '''

def backtest_jump():
    """★★★V32.0【跳升榜回测】验证：跳升大+涨幅小 = 明天的涨停吗★★★

    用户2026-08-24：『你要找到规律，抓能涨停的股，
      而不是找已经涨停的让我买 —— 我买不进去。』

    假设：板块跳升≥N位 且 当天涨幅<2% = 资金刚进、价格没动
         → 次日该板块涨幅应显著高于全市场平均
    数据源：reports/top_sectors.json + top_concepts.json（26天历史）
    """
    w("\\n" + "=" * 60)
    w("🔬🔬【跳升榜回测】跳升大+涨幅小 → 明天真的会涨吗 🔬🔬")
    w("=" * 60)
    w("  ★用户2026-08-24：『抓能涨停的股，不是找已经涨停的让我买』")
    w("  ★假设：跳升≥300位 + 当天涨幅<2% = 资金刚进、价格没动")
    w("    → 次日该板块表现应显著优于其他板块")

    hist = {}
    for f in ("reports/top_sectors.json", "reports/top_concepts.json"):
        try:
            if os.path.exists(f):
                with open(f, "r", encoding="utf-8") as fp:
                    d = json.load(fp)
                for dt, arr in d.items():
                    hist.setdefault(dt, []).extend(
                        arr if isinstance(arr, list) else [])
        except Exception:
            continue
    days = sorted(hist.keys())
    if len(days) < 4:
        w(f"  ⚠️ 历史仅{len(days)}天，需≥4天才能回测")
        w("=" * 60)
        return

    w(f"  ✅ 历史数据：{len(days)}天（{days[0]} ~ {days[-1]}）")

    # 每天建立 板块名 -> (排名, 涨幅)
    day_map = {}
    for dt in days:
        m = {}
        for i, it in enumerate(hist[dt]):
            try:
                if isinstance(it, dict):
                    nm = str(it.get("name") or it.get("板块") or "")
                    pc = it.get("pct")
                    if pc is None:
                        pc = it.get("涨跌幅")
                elif isinstance(it, (list, tuple)) and len(it) >= 2:
                    nm, pc = str(it[0]), it[1]
                else:
                    continue
                if not nm:
                    continue
                m[nm] = (i + 1, float(pc) if pc is not None else None)
            except Exception:
                continue
        if m:
            day_map[dt] = m

    dl = sorted(day_map.keys())
    if len(dl) < 3:
        w(f"  ⚠️ 可用天数{len(dl)}，不足")
        w("=" * 60)
        return

    # 分组统计
    groups = {
        "跳升≥300位 且 涨<2%": [0, 0.0],
        "跳升≥300位 且 涨≥2%": [0, 0.0],
        "跳升100-300位 涨<2%": [0, 0.0],
        "跳升30-100位  涨<2%": [0, 0.0],
        "★对照·全部板块": [0, 0.0],
    }
    for i in range(1, len(dl) - 1):
        prev, today, nxt = dl[i - 1], dl[i], dl[i + 1]
        mp, mt, mn = day_map[prev], day_map[today], day_map[nxt]
        for nm, (rk_t, pc_t) in mt.items():
            if nm not in mn:
                continue
            nxt_pc = mn[nm][1]
            if nxt_pc is None:
                continue
            g = groups["★对照·全部板块"]
            g[0] += 1
            g[1] += nxt_pc
            if nm not in mp or pc_t is None:
                continue
            jump = mp[nm][0] - rk_t
            if jump >= 300:
                k = "跳升≥300位 且 涨<2%" if pc_t < 2 else "跳升≥300位 且 涨≥2%"
            elif jump >= 100 and pc_t < 2:
                k = "跳升100-300位 涨<2%"
            elif jump >= 30 and pc_t < 2:
                k = "跳升30-100位  涨<2%"
            else:
                continue
            groups[k][0] += 1
            groups[k][1] += nxt_pc

    base = groups["★对照·全部板块"]
    base_avg = base[1] / base[0] if base[0] else 0
    w("")
    w("  ── 次日板块平均涨幅（分组对比）──")
    best = None
    for k, (cnt, sm) in groups.items():
        if cnt < 5:
            w(f"    {k:22s}：样本{cnt}，不足5个，跳过")
            continue
        avg = sm / cnt
        excess = avg - base_avg
        mark = ""
        if k != "★对照·全部板块":
            if excess > 0.5:
                mark = "  🟢★显著跑赢★"
                if best is None or excess > best[1]:
                    best = (k, excess, cnt)
            elif excess > 0:
                mark = "  ⚪略跑赢"
            else:
                mark = "  🔴跑输"
        w(f"    {k:22s}：{cnt:>4}个样本 次日均{avg:+.2f}% "
          f"超额{excess:+.2f}%{mark}")

    w("")
    if best:
        w(f"  ★★结论：【{best[0]}】次日超额 {best[1]:+.2f}%（{best[2]}样本）")
        w("     → ★这条规律成立，可以拿来选板块★")
        w("     → 用法：从该板块里挑【今天涨幅最小 + 60日低位】的个股")
    else:
        w("  🔴🔴 没有任何一组显著跑赢全市场平均")
        w("     → ★跳升榜这个信号不成立，不许再拿它当买入依据★")
        w("     → 需要换一个假设重新验证")
    w("")
    w("  ⚠️ 这是【板块级】回测。板块次日涨 ≠ 你买的那只涨。")
    w("     仍需过①-B：这只票的驱动和板块涨的原因是同一个吗？")
    w("=" * 60)

'''

if "def backtest_jump()" not in s:
    anchor = "def backtest_picker("
    if anchor in s:
        s = s.replace(anchor, FUNC.strip() + "\n\n\ndef backtest_picker(", 1)
        n += 1
        print("OK 1: backtest_jump added")
    else:
        anchor2 = "def scan_rule_scorecard("
        if anchor2 in s:
            s = s.replace(anchor2, FUNC.strip() + "\n\n\ndef scan_rule_scorecard(", 1)
            n += 1
            print("OK 1b: backtest_jump added (alt anchor)")
        else:
            print("SKIP 1: no anchor")
else:
    print("SKIP 1: already there")

CALL = '        safe_run("选股器回测", backtest_picker)'
if CALL in s and "跳升榜回测" not in s.split("safe_run")[0]:
    if 'safe_run("跳升榜回测"' not in s:
        s = s.replace(CALL, '        safe_run("跳升榜回测", backtest_jump)\n' + CALL, 1)
        n += 1
        print("OK 2: call added")
else:
    print("SKIP 2")

if "V31.0 |" in s:
    s = s.replace("A股作战扫描器V31.0 |", "A股作战扫描器V32.0 |")
    n += 1

if n:
    io.open(P, "w", encoding="utf-8").write(s)
    print("DONE: %d changes" % n)
else:
    print("DONE: nothing")

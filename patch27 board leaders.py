# -*- coding: utf-8 -*-
"""
patch27_board_leaders.py —— 新增模块【强板块·领涨挖掘】

★为什么要它（2026-09-22 用户原话）★
  『你敢说你昨天在找ETF创新药的时候，在他板块里面没有任何一支医药股
    今天是涨停的吗？……你并没有让我去买，反而让我去买个ETF』
  9/22 医药里 义翘神州/诺唯赞 20cm涨停，南华生物/哈药/新华制药 涨停，
  全在AI 9/21 已判为"最强"的板块里。
  ★缺口：系统能告诉AI"哪个板块强"，却没有模块告诉AI"强板块里谁最强"。
    旧【个股选股器】筛的是"60日下跌+缩量+没涨"的冷门反转，方向相反，已停用。
    于是AI每次停在板块层 → 用ETF填空 → 几天波动一百多块。

★做法（全部只用在GitHub上能拿到的数据，不碰被封的个股接口）★
  ① 选板块：今日板块榜（行业+概念），按 涨幅×2 + 排名跳升 + 资金 打分，
     过滤掉"同花顺指数/融资融券/次新/破净"这类非产业概念，取前5个
  ② 取成分股：同花顺成分股接口（30天缓存）
  ③ 合并全市场快照：今日涨幅、成交额、是否20cm、是否已封板
  ④ 拉K线（每板块前8只）：近10日涨停次数、5日/20日量比、10日涨幅
  ⑤ 弹性打分：今日强度 + 20cm + 近期涨停(有辨识度) + 放量 − 已涨透
     ★已封板的标"今日买不到"，但保留（明日看溢价）
  ⑥ 输出：每个强板块前5只 + 全场"可买"弹性前5

依赖：get_spot / pick_col / _board_cons / _hist_close / _prewarm_klines /
      SECTOR_JUMP_MAP / _sector_flow_of / TODAY_BOARD_行业/概念（patch17c/25）
"""
import io
import os
import sys

MARK = "patch27_board_leaders"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"]
             if os.path.exists(c)), None)
if path is None:
    print("!! patch27 中止：找不到 scanner_cloud.py")
    sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch27 已打过，跳过（幂等）")
    sys.exit(0)

FUNC = r'''
# ===== @@MARK@@ =====
_SB27_SKIP = ["指数", "同花顺", "新质50", "次新", "融资融券", "沪股通", "深股通",
              "MSCI", "标普", "富时", "转融券", "证金", "社保", "QFII", "基金重仓",
              "机构重仓", "破净", "高股息", "注册制", "昨日", "涨停", "连板", "首板",
              "AH股", "中特估", "国企改革", "央企", "地方国企", "参股", "预增",
              "预盈", "扭亏", "送转", "股权转让", "举牌", "回购", "债转股",
              "B股", "H股", "北交所", "ST板块", "年报", "中报"]


def scan_strong_board_picks():
    """patch27【强板块·领涨挖掘】最强板块里，谁最强、谁最有弹性"""
    import time as _t27
    _t0 = _t27.time()
    _BUDGET = 90
    w("\n" + "=" * 60)
    w("🏆🏆【强板块·领涨挖掘】最强板块里，谁最强、谁最有弹性 🏆🏆")
    w("=" * 60)
    w("  ★9/22用户：『昨天创新药板块里没有一支今天涨停的吗？你却让我买ETF』")
    w("    旧流程停在板块层→ETF填空。本模块补上【板块→个股】这一步。")

    sp = get_spot()
    if sp is None:
        w("  🔴 快照缺失，本节无法计算")
        return
    try:
        sp = sp.loc[:, ~sp.columns.duplicated()]
    except Exception:
        pass
    cc = pick_col(sp, ["代码", "code"])
    cn = pick_col(sp, ["名称", "name"])
    cp = pick_col(sp, ["最新价", "trade"])
    cg = pick_col(sp, ["涨跌幅", "changepercent"])
    ca = pick_col(sp, ["成交额", "amount"])
    if not all([cc, cn, cp, cg, ca]):
        w("  🔴 快照缺关键列")
        return
    snap = {}
    for _, r in sp.iterrows():
        try:
            snap[str(r[cc])[-6:]] = (str(r[cn]).strip(), float(r[cp]),
                                     float(r[cg]), float(r[ca]))
        except Exception:
            continue

    # ① 选板块
    boards = []
    for kind in ("行业", "概念"):
        store = globals().get("TODAY_BOARD_" + kind) or {}
        for nm, v in store.items():
            try:
                pct = float(v.get("pct"))
            except Exception:
                continue
            if pct < 0.5 or any(k in str(nm) for k in _SB27_SKIP):
                continue
            jp = SECTOR_JUMP_MAP.get(nm, 0) or 0
            fl = _sector_flow_of(nm) if kind == "行业" else None
            sc = pct * 2 + min(max(jp, 0), 300) / 60.0 + ((fl or 0) / 10.0)
            boards.append((sc, kind, nm, pct, jp, fl))
    if not boards:
        w("  ⚠️ 今日板块快照为空（patch17c/25未生效？）→ 本节无法计算")
        return
    boards.sort(key=lambda x: -x[0])
    pick_b, n_ind, n_con = [], 0, 0
    for b in boards:
        if b[1] == "行业" and n_ind < 3:
            pick_b.append(b); n_ind += 1
        elif b[1] == "概念" and n_con < 3:
            pick_b.append(b); n_con += 1
        if len(pick_b) >= 5:
            break
    w("\n  ── ①今日最强板块（涨幅×2+跳升+资金）──")
    for sc, kind, nm, pct, jp, fl in pick_b:
        w(f"    [{kind}]{nm} {pct:+.2f}% 跳升{jp:+d}位"
          + (f" 资金{fl:+.1f}亿" if fl is not None else "") + f" → {sc:.1f}分")

    # ②③ 成分股 + 快照
    per_board = []
    all_codes = []
    for sc, kind, nm, pct, jp, fl in pick_b:
        if _t27.time() - _t0 > _BUDGET:
            w("  ⏱️ 预算用尽，后面的板块跳过")
            break
        cons = _board_cons(nm, kind) or []
        rows = []
        for c6, _n in cons:
            if c6 not in snap:
                continue
            name, price, chg, amt = snap[c6]
            if "ST" in name or "退" in name or name.startswith("N") or price <= 0:
                continue
            is20 = c6.startswith(("300", "301", "688", "689"))
            lim = 19.8 if is20 else 9.8
            rows.append({"c": c6, "n": name, "p": price, "g": chg, "a": amt,
                         "is20": is20, "sealed": chg >= lim})
        rows.sort(key=lambda x: -x["g"])
        top = [r for r in rows if r["a"] >= 1e8][:8]
        per_board.append((nm, kind, pct, top, len(cons)))
        all_codes += [r["c"] for r in top]

    # ④ K线
    try:
        _prewarm_klines(list(dict.fromkeys(all_codes)))
    except Exception:
        pass

    def _kfeat(code):
        try:
            k, clc = _hist_close(code)
            if k is None or not clc:
                return None
            cl = pd.to_numeric(k[clc], errors="coerce").dropna()
            if len(cl) < 21:
                return None
            chg = cl.pct_change() * 100
            is20 = code.startswith(("300", "301", "688", "689"))
            lim = 19.5 if is20 else 9.5
            lu10 = int((chg.tail(10) >= lim).sum())
            r10 = float(cl.iloc[-1] / cl.iloc[-11] - 1)
            hi60 = float(cl.tail(60).max())
            d60 = float(cl.iloc[-1] / hi60 - 1)
            vr = None
            vc = pick_col(k, ["成交量", "volume"])
            if vc:
                vv = pd.to_numeric(k[vc], errors="coerce").dropna()
                if len(vv) >= 20 and float(vv.tail(20).mean()) > 0:
                    vr = float(vv.tail(5).mean() / vv.tail(20).mean())
            return {"lu10": lu10, "r10": r10, "d60": d60, "vr": vr}
        except Exception:
            return None

    # ⑤ 打分 + ⑥ 输出
    buyable = []
    w("\n  ── ②每个强板块里的弹性前5 ──")
    for nm, kind, pct, top, ncons in per_board:
        if not top:
            w(f"\n  ◆[{kind}]{nm}：成分股{ncons}只，但与快照无交集/成交不足 → 跳过")
            continue
        scored = []
        for r in top:
            f = _kfeat(r["c"]) if _t27.time() - _t0 < _BUDGET + 30 else None
            s2 = min(r["g"], 10) / 2.0
            if r["is20"]:
                s2 += 1.5
            if f:
                s2 += min(f["lu10"], 3) * 1.5
                if f["vr"] is not None:
                    s2 += 1.5 if f["vr"] > 1.5 else (0.5 if f["vr"] > 1.0 else 0)
                if f["r10"] > 0.5:
                    s2 -= 3
                elif f["r10"] > 0.3:
                    s2 -= 1
            if 3e8 <= r["a"] <= 8e9:
                s2 += 1
            scored.append((s2, r, f))
        scored.sort(key=lambda x: -x[0])
        w(f"\n  ◆[{kind}]{nm} {pct:+.2f}%（成分股{ncons}只）")
        for i, (s2, r, f) in enumerate(scored[:5], 1):
            tag = "🔒已封板·今日买不到(明日看溢价)" if r["sealed"] else "✅可买"
            fs = (f"｜近10日涨停{f['lu10']}次｜量比{f['vr']:.2f}｜10日{f['r10']*100:+.1f}%"
                  f"｜距60日高{f['d60']*100:+.1f}%") if f and f["vr"] is not None else \
                 (f"｜近10日涨停{f['lu10']}次｜10日{f['r10']*100:+.1f}%" if f else "｜K线【无数据】")
            w(f"    {i}. {r['n']}({r['c']}) 今{r['g']:+.2f}%"
              f"{'｜20cm' if r['is20'] else ''}{fs}｜成交{r['a']/1e8:.1f}亿"
              f" → 弹性{s2:.1f} {tag}")
            if not r["sealed"]:
                buyable.append((s2, r, nm))
    buyable.sort(key=lambda x: -x[0])
    w("\n  ── ③全场【可买】弹性前5（AI从这里选，不许退回ETF）──")
    if not buyable:
        w("    无（强板块里能买的全封板了 → 明日看溢价，不追）")
    for i, (s2, r, nm) in enumerate(buyable[:5], 1):
        w(f"    {i}. {r['n']}({r['c']}) [{nm}] 今{r['g']:+.2f}% 弹性{s2:.1f}")
    w("\n  ⚠️ AI必须：从③里选一只，答出①-B（靠什么赚钱、和板块今天涨的原因是否同一个）")
    w("     答不出 → 当场说缺什么数据，写代码补/请用户查股票，★不许退回ETF★")
    w(f"  （耗时{_t27.time()-_t0:.0f}秒）")
    w("=" * 60)
# ===== @@MARK@@ 结束 =====

'''.replace("@@MARK@@", MARK)

A = "def scan_daily_pick():"
if s.count(A) != 1:
    print("!! patch27 中止：锚点 def scan_daily_pick 未命中或不唯一")
    sys.exit(0)
s = s.replace(A, FUNC + A, 1)
print("OK 1: 已注入 scan_strong_board_picks()")

B = '        safe_run("★每日选股(稳定版)★", scan_daily_pick)'
if s.count(B) == 1:
    s = s.replace(B, B + '\n        safe_run("★强板块·领涨挖掘★", scan_strong_board_picks)', 1)
    print("OK 2: 已接入主流程（紧跟每日选股之后）")
else:
    print("!! 2: 调用锚点未命中 —— 函数已注入但不会被调用")

io.open(path, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n# " + MARK + "\n")
print("patch27 完成 → " + path)

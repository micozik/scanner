# -*- coding: utf-8 -*-
"""
patch28_leaders_v2.py —— 修【强板块·领涨挖掘】首跑暴露的4个问题（2026-09-22 r679实测）

  ① 5个强板块里4个"成分股0只"：同花顺成分股接口在海外服务器大多失败。
     → 行业板块改用系统已有的【行业对照表 industry_map.json】反查成分股，不再调接口。
  ② 全部"K线【无数据】"：本模块排在报告后段，K线预算(420秒)已被前面模块用光。
     → 预算用尽时直接走 _hist_close_raw（带新浪symbol），本模块最多20只，不抢别人。
  ③ 只按今日涨幅排序 = 追高（排第一的光云科技已+16%）。
     → 改成面向"明天能买"：今日强度5%封顶，20cm折半计；折算后>7%扣分；封板单列"明日看溢价"。
  ④ 板块打分偏涨幅，资金+17亿的半导体没入选。
     → 资金前两名且>5亿的行业强制入选。
  依赖 patch27 已打（替换它注入的函数体，保留原标记）。
"""
import io, os, sys
MARK = "patch28_leaders_v2"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch28 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch28 已打过，跳过（幂等）"); sys.exit(0)
A = "# ===== patch27_board_leaders ====="
B = "# ===== patch27_board_leaders 结束 ====="
if A not in s or B not in s:
    print("!! patch28 中止：没找到 patch27 的函数（先打 patch27）"); sys.exit(0)
i = s.index(A); j = s.index(B) + len(B)
NEW = r'''# ===== @@MARK@@ =====
_SB27_SKIP = ["指数", "同花顺", "新质50", "次新", "融资融券", "沪股通", "深股通",
              "MSCI", "标普", "富时", "转融券", "证金", "社保", "QFII", "基金重仓",
              "机构重仓", "破净", "高股息", "注册制", "昨日", "涨停", "连板", "首板",
              "AH股", "中特估", "国企改革", "央企", "地方国企", "参股", "预增",
              "预盈", "扭亏", "送转", "股权转让", "举牌", "回购", "债转股",
              "B股", "H股", "北交所", "ST板块", "年报", "中报"]


def scan_strong_board_picks():
    """patch27+28【强板块·领涨挖掘 V2】"""  # patch28_leaders_v2
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
    try:
        _ind_by_flow = sorted([b for b in boards if b[1] == "行业" and b[5] is not None],
                              key=lambda x: -x[5])
        for _bf in _ind_by_flow[:2]:                     # 资金前两名的行业都要看
            if _bf[5] > 5 and _bf[2] not in [b[2] for b in pick_b]:
                pick_b.append(_bf)
        pick_b = pick_b[:6]
    except Exception:
        pass
    w("\n  ── ①今日最强板块（涨幅×2+跳升+资金；资金前两名的行业强制入选）──")
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
        _src28 = "接口"
        if not cons and kind == "行业":
            try:
                _im28, _ = _load_ind_cache()
                cons = [(c, "") for c, ind in (_im28 or {}).items()
                        if str(ind).strip() == str(nm).strip()]
                _src28 = "行业对照表"
            except Exception:
                cons = []
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
        per_board.append((nm, kind, pct, top, len(cons), _src28))
        all_codes += [r["c"] for r in top]

    # ④ K线
    try:
        _prewarm_klines(list(dict.fromkeys(all_codes)))
    except Exception:
        pass

    _kraw = [0]

    def _kfeat(code):
        try:
            k, clc = _hist_close(code)
            if (k is None or not clc) and _kraw[0] < 20:
                _kraw[0] += 1
                _sym = ("sh" if code.startswith(("6", "9")) else
                        "bj" if code.startswith(("8", "4", "92")) else "sz") + code
                k, clc = _hist_close_raw(code, _sym)
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
    for nm, kind, pct, top, ncons, srcn in per_board:
        if not top:
            if ncons == 0:
                w(f"\n  ◆[{kind}]{nm}：成分股接口失败且对照表无匹配 → 跳过")
            else:
                w(f"\n  ◆[{kind}]{nm}：成分股{ncons}只，但成交不足1亿 → 跳过")
            continue
        scored = []
        for r in top:
            f = _kfeat(r["c"]) if _t27.time() - _t0 < _BUDGET + 30 else None
            _ge = r["g"] / 2.0 if r["is20"] else r["g"]   # 20cm折算成10cm口径
            s2 = min(max(_ge, 0), 5) / 1.5                  # 今天强度，5%封顶
            if _ge > 7:
                s2 -= 1.5                                   # 今天涨太多=明天追高
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
        w(f"\n  ◆[{kind}]{nm} {pct:+.2f}%（成分股{ncons}只，来源:{srcn}）")
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
    _seen27 = {}
    for s2, r, nm in buyable:
        if r["c"] not in _seen27 or s2 > _seen27[r["c"]][0]:
            _seen27[r["c"]] = (s2, r, nm)
    buyable = sorted(_seen27.values(), key=lambda x: -x[0])
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
'''.replace("@@MARK@@", "patch27_board_leaders").strip("\n")
s = s[:i] + NEW + s[j:]
io.open(path, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n# " + MARK + "\n")
print("OK 1: 领涨挖掘已升级为V2（行业对照表兜底/K线直取/面向明日打分/资金第一行业强制入选）→ " + path)

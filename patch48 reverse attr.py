# -*- coding: utf-8 -*-
"""
patch48_reverse_attr.py —— 【漏网线索·反向归因】
2026-10-08 用户：『你每天收集的信息里面有很多都被你过滤了，
                这些过滤掉的信息里面到底包含有多少机会？你知不知道？』
实测当天漏掉的：鼠疫→华北制药/润都股份/达安基因/蔚蓝生物开盘涨停；
  流感阳性率19.8%→流感概念高开；生物质能→卓越新能20cm；
  9/28 七部门新型电池规划→电池连涨三天、今天资金第一。
根因（两个）：
  ① patch31 硬线索把含『涨停/拉升/高开/ETF』的标题当噪音丢掉——
     可这些恰恰是『市场正在为哪条新闻掏钱』的直接证据；
  ② 只会『新闻→板块』正向推，从不反过来问『今天涨的票，新闻池里有没有它』。
做法（全自动、零输入）：
  A. 今天涨≥7%的每只票，去新闻池+公告池里找点名它的标题；
     有 = 这条新闻我们收到了却被过滤；没有 = 题材/资金驱动，需查板块。
     末尾统计『大涨N只，其中M只新闻池里早有』= 当天被过滤的机会数。
  B. 【盘面在炒什么】把『XX概念/板块 + 涨停/拉升/走强/高开/连板』类标题单列，
     这是 patch31 丢掉的那一类。
  插在【今日硬线索】正下方。
"""
import io, os, sys
MARK = "patch48_reverse_attr"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch48 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch48 已打过"); sys.exit(0)

D = '''    os.makedirs("reports", exist_ok=True)
    text = "\\n".join(REPORT)'''
if s.count(D) != 1:
    print("!! patch48 中止：报告写出锚点命中 %d 次" % s.count(D)); sys.exit(0)

NEW = r'''    # ===== @@MARK@@：反向归因 =====
    try:
        import re as _re48

        def _t48(it):
            if isinstance(it, dict):
                return str(it.get("title") or it.get("t") or it.get("content") or "")
            if isinstance(it, (tuple, list)):
                return " ".join(str(x) for x in it)
            return str(it)

        _pool48 = [_t48(x).strip() for x in
                   (list(globals().get("TODAY_NEWS", []) or []) +
                    list(globals().get("TODAY_ANNOUNCE_RAW", []) or []))]
        _pool48 = [x for x in _pool48 if x]
        _L48 = ["", "=" * 60,
                "🔎🔎【漏网线索·反向归因】今天涨的票，新闻池里早有没有它？🔎🔎",
                "=" * 60,
                f"  新闻+公告池共 {len(_pool48)} 条"]
        _sp48 = globals().get("SPOT_DF")
        if _sp48 is None:
            try:
                _sp48 = get_spot()
            except Exception:
                _sp48 = None
        _movers48 = []
        if _sp48 is not None and len(_sp48):
            _cc = pick_col(_sp48, ["代码", "code", "symbol"])
            _cn = pick_col(_sp48, ["名称", "name"])
            _cg = pick_col(_sp48, ["涨跌幅", "changepercent"])
            for _, _r in _sp48.iterrows():
                try:
                    _nm = str(_r[_cn]).strip()
                    _pc = float(pd.to_numeric(_r[_cg], errors="coerce"))
                    if _pc != _pc or _pc < 7 or "ST" in _nm or _nm[:1] in ("N", "C"):
                        continue
                    _movers48.append((_pc, _nm, str(_r[_cc])[-6:]))
                except Exception:
                    continue
        _movers48.sort(reverse=True)
        if not _movers48:
            _L48.append("  ⚠️ 全市场快照拿不到或无≥7%个股 → A段跳过")
        else:
            _hit48 = 0
            _L48.append(f"  ── A. 今天涨≥7%共 {len(_movers48)} 只（列前40）──")
            for _pc, _nm, _cd in _movers48[:40]:
                _keys = [_nm]
                if len(_nm) >= 4:
                    _keys.append(_nm[:2] + _nm[2:4])   # 全称前4字
                _m = [t for t in _pool48 if any(k in t for k in _keys)]
                if _m:
                    _hit48 += 1
                    _L48.append(f"  📰 {_nm}({_cd}) {_pc:+.1f}% ← 新闻池里有{len(_m)}条：")
                    for t in _m[:2]:
                        _L48.append("       · " + _re48.sub(r"\s+", " ", t)[:80])
                else:
                    _L48.append(f"  ❓ {_nm}({_cd}) {_pc:+.1f}% ← 新闻池无点名（题材/资金驱动，查它属于哪个板块）")
            _n = min(len(_movers48), 40)
            _L48.append(f"  ★统计：大涨{_n}只里，{_hit48}只的消息我们早就收到了"
                        f" → 这{_hit48}条就是今天被过滤掉的机会")
        # B. 盘面在炒什么（patch31 丢掉的那类标题）
        _UP48 = ("涨停", "拉升", "走强", "活跃", "爆发", "大涨", "高开", "连板",
                 "异动", "走高", "涨超", "领涨", "冲击涨停", "触及涨停")
        _GRP48 = ("概念", "板块", "股", "赛道", "产业链")
        _seen48, _B48 = set(), []
        for t in _pool48:
            if not any(u in t for u in _UP48) or not any(g in t for g in _GRP48):
                continue
            if "跌" in t[:12]:
                continue
            _fp = "".join(_re48.findall(r"[一-龥]", t))[:10]
            if not _fp or _fp in _seen48:
                continue
            _seen48.add(_fp)
            _B48.append(_re48.sub(r"\s+", " ", t)[:80])
        _L48.append("")
        _L48.append(f"  ── B. 盘面在炒什么（{len(_B48)}条，硬线索模块会把这类当噪音丢掉）──")
        for t in _B48[:40]:
            _L48.append("   · " + t)
        _L48.append("  ★AI必做：A段每个📰都要回答『这条新闻我当时为什么没推？下次怎么抓？』")
        _L48.append("=" * 60)
        _pos48 = next((i for i, l in enumerate(REPORT) if "数据可信度体检" in str(l)), 8)
        _pos48 = max(0, _pos48 - 1)
        REPORT[_pos48:_pos48] = _L48
    except Exception as _e48:
        REPORT.insert(8, f"  [patch48] 反向归因失败：{type(_e48).__name__}: {str(_e48)[:60]}")
    # ===== @@MARK@@ 结束 =====
'''.replace("@@MARK@@", MARK)
s = s.replace(D, NEW + D, 1)
io.open(path, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n# " + MARK + "\n")
print("OK 1: 【漏网线索·反向归因】将插在硬线索下方 → " + path)

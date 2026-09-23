# -*- coding: utf-8 -*-
"""
patch34_probe.py —— 把 akshare 里【实际存在】的板块/成分股函数全部打印出来
2026-09-23 三次尝试全失败，结论如下：
  · 同花顺 stock_board_concept_cons_ths / industry_cons_ths → 本版akshare【不存在】
  · 东财 cons/name → CallTimeout / ConnectionError（海外IP封锁）
  · 新浪 → 概念只有175个、行业只有49个，没有玻璃基板/MLCC/培育钻石这些新概念
★不再猜第四个源。先把这版 akshare 里名字带 board/cons/concept/industry/sector
  的函数【全部列出来】，下一轮直接用看得见的函数，不再盲试。
只打印一次，不影响任何逻辑，耗时<1秒。
"""
import io, os, sys
MARK = "patch34_probe"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch34 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch34 已打过"); sys.exit(0)

A = '''    os.makedirs("reports", exist_ok=True)
    text = "\\n".join(REPORT)'''
if A not in s:
    print("!! patch34 中止：报告写出锚点未命中"); sys.exit(0)

NEW = '''    # ''' + MARK + '''：把可用的板块类函数打印出来，供下一轮选源
    try:
        _all34 = [x for x in dir(ak) if not x.startswith("_")]
        _pick34 = lambda k: sorted([x for x in _all34 if k in x.lower()])
        w("\\n" + "=" * 60)
        w("🔧【akshare 可用函数探测】patch34 —— 成分股到底该用哪个函数")
        w("=" * 60)
        w(f"  akshare 版本：{getattr(ak, '__version__', '未知')} ｜ 函数总数 {len(_all34)}")
        for _k34 in ("cons", "concept", "industry", "sector", "board"):
            _v34 = _pick34(_k34)
            w(f"  含『{_k34}』的函数 {len(_v34)}个：")
            for _i34 in range(0, min(len(_v34), 24), 3):
                w("      " + " ｜ ".join(_v34[_i34:_i34 + 3]))
            if len(_v34) > 24:
                w(f"      …另有{len(_v34)-24}个")
        w("=" * 60)
    except Exception as _e34:
        w(f"  [patch34] 探测失败：{type(_e34).__name__}")
''' + A
s = s.replace(A, NEW, 1)
io.open(path, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n# " + MARK + "\n")
print("OK 1: 已加 akshare 函数探测（报告末尾）→ " + path)

# -*- coding: utf-8 -*-
"""
patch35_order_budget.py —— 修"必然失败的概念把预算烧光，能查的行业反而被跳过"
2026-09-23 事故：依顿电子(603328)涨停，元件板块资金+34.56亿全场第一、连4天、
  它就是领涨股；PCB概念交叉得分第2★有催化但还没涨★；硬线索有"覆铜板涨价10%"。
  而【强板块·领涨挖掘】的输出是：
     玻璃基板→接口失败 / PET铜箔→接口失败 / 培育钻石→接口失败
     ⏱️ 预算用尽，后面的板块跳过   ← 元件、半导体全没轮到
  ★行业板块能用行业对照表查出成分股（元件昨天查到42只），
    却因为排在三个查不到的概念后面而被跳过。

三处修：
  ① ★行业板块排在概念前面★（行业能用对照表兜底，概念现在三个源全挂）
  ② 失败的板块记入【负缓存】，同一天/次日不再重复试（省下大量超时）
  ③ 模块预算 90秒 → 150秒
"""
import io, os, sys
MARK = "patch35_order_budget"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch35 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch35 已打过"); sys.exit(0)
ok = 0

# ① 行业优先：挑板块时先放行业，再放概念
A1 = '''    pick_b, n_ind, n_con = [], 0, 0
    for b in boards:
        if b[1] == "行业" and n_ind < 3:
            pick_b.append(b); n_ind += 1
        elif b[1] == "概念" and n_con < 3:
            pick_b.append(b); n_con += 1
        if len(pick_b) >= 5:
            break'''
if A1 in s:
    s = s.replace(A1, '''    # ''' + MARK + '''：★行业排前面★（行业能用对照表兜底，概念三个源全挂）
    pick_b, n_ind, n_con = [], 0, 0
    for b in boards:                      # 先扫行业
        if b[1] == "行业" and n_ind < 3:
            pick_b.append(b); n_ind += 1
    for b in boards:                      # 再补概念
        if b[1] == "概念" and n_con < 3:
            pick_b.append(b); n_con += 1
        if len(pick_b) >= 6:
            break''', 1); ok += 1
    print("OK 1: 领涨挖掘改为【行业优先】")
else:
    print("!! 1: 选板块锚点未命中")

# ② 负缓存：查不到的板块，当天不再重复试
A2 = '''    _cc, _cts = _cache_get(CONS_CACHE_FILE, _ck, 30)
    if _cc:
        return [tuple(x) for x in _cc]'''
if A2 in s:
    s = s.replace(A2, A2 + '''
    # ''' + MARK + '''：负缓存——今天已确认查不到的板块，不再重复烧预算
    _neg35 = globals().setdefault("CONS_FAIL_TODAY35", set())
    if _ck in _neg35:
        return []''', 1); ok += 1
    print("OK 2: 加负缓存（读）")

A3 = '''    try:
        w(f"    [patch32诊断] {kind}『{board_name}』成分股全失败：{' ｜ '.join(_why32[:6])}")
    except Exception:
        pass
    return []'''
if A3 in s:
    s = s.replace(A3, '''    try:
        globals().setdefault("CONS_FAIL_TODAY35", set()).add(_ck)   # ''' + MARK + '''
        w(f"    [patch32诊断] {kind}『{board_name}』成分股全失败：{' ｜ '.join(_why32[:6])}")
    except Exception:
        pass
    return []''', 1); ok += 1
    print("OK 3: 加负缓存（写）")
else:
    print("!! 3: patch33后的诊断锚点未命中")

# ③ 预算 90 → 150 秒
A4 = '''    _BUDGET = 90'''
if A4 in s:
    s = s.replace(A4, '''    _BUDGET = 150   # ''' + MARK + '''：90秒不够，行业挖掘常被卡在最后''', 1); ok += 1
    print("OK 4: 模块预算 90→150秒")

io.open(path, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n# " + MARK + "\n")
print("patch35 完成 %d/4 → %s" % (ok, path))

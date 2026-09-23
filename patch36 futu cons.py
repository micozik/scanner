# -*- coding: utf-8 -*-
"""
patch36_futu_cons.py —— 概念成分股改用【富途】
2026-09-23 patch34探测结论（akshare 1.18.97，1143个函数）：
  · 同花顺：只有 name_ths/index_ths/info_ths/summary_ths，★确实没有 cons_ths★
  · 东财：stock_board_concept_cons_em 存在但海外IP被封（CallTimeout/ConnectionError）
  · 新浪：概念只有175个，没有玻璃基板/MLCC/培育钻石
  ★★探测发现新函数：stock_concept_cons_futu ★★
  而富途源今天在新闻模块是通的（富途12条）→ 值得一试。
做法：在新浪兜底之后，再加富途兜底；同时富途概念名单函数若存在也一并试。
"""
import io, os, sys
MARK = "patch36_futu_cons"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch36 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch36 已打过"); sys.exit(0)

A = '''    try:
        globals().setdefault("CONS_FAIL_TODAY35", set()).add(_ck)   # patch35_order_budget'''
if A not in s:
    A = '''    try:
        w(f"    [patch32诊断] {kind}『{board_name}』成分股全失败：{' ｜ '.join(_why32[:6])}")'''
    if A not in s:
        print("!! patch36 中止：锚点未命中（先打 patch32/33）"); sys.exit(0)

NEW = '''    # ''' + MARK + '''：富途兜底（patch34探测到 stock_concept_cons_futu 存在）
    try:
        _ft36 = getattr(ak, "stock_concept_cons_futu", None)
        if _ft36 is None:
            _why32.append("富途:stock_concept_cons_futu不存在")
        else:
            for _nm36 in dict.fromkeys([board_name, _nz32(board_name),
                                        _nz32(board_name) + "概念"]):
                try:
                    _df36 = with_retry(lambda x=_nm36: _ft36(symbol=str(x)),
                                       tries=1, wait=1, timeout=25)
                    _out36 = _parse32(_df36) if _df36 is not None and len(_df36) else []
                    if _out36:
                        _cache_put(CONS_CACHE_FILE, _ck, _out36)
                        w(f"    [patch36] {board_name} 成分股经【富途】取得{len(_out36)}只")
                        return _out36
                except Exception as e:
                    _why32.append(f"富途({_nm36}):{type(e).__name__}")
    except Exception as e:
        _why32.append(f"富途兜底异常:{type(e).__name__}")

''' + A
s = s.replace(A, NEW, 1)
io.open(path, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n# " + MARK + "\n")
print("OK 1: 概念成分股已加富途兜底 → " + path)

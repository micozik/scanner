# -*- coding: utf-8 -*-
"""
patch33_cons_sina.py —— 成分股再加一条【新浪】兜底
2026-09-23 r691 patch32诊断结论：
  · 同花顺 stock_board_concept_cons_ths / _industry_cons_ths 在本版akshare【不存在】
  · 东财 cons/name 全部 CallTimeout / ConnectionError（海外IP被封）
  → 两条路都不通，玻璃基板(跳351位全场第1)、MLCC、培育钻石全部挖不到个股。
★而新浪是通的（全市场快照5567只就是新浪给的）→ 用新浪板块接口兜底：
   stock_sector_spot(indicator="概念"/"新浪行业") 拿板块名单和板块代码
   stock_sector_detail(sector=板块代码) 拿成分股
  函数不存在也会打印出来，下一轮就知道换哪个。
"""
import io, os, sys
MARK = "patch33_cons_sina"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch33 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch33 已打过"); sys.exit(0)

A = '''    try:
        w(f"    [patch32诊断] {kind}『{board_name}』成分股全失败：{' ｜ '.join(_why32[:5])}")
    except Exception:
        pass
    return []'''
if A not in s:
    print("!! patch33 中止：patch32 锚点未命中（先打 patch32）"); sys.exit(0)

NEW = '''    # ''' + MARK + '''：新浪兜底（同花顺函数不存在、东财被封时唯一可用）
    try:
        _sp33 = getattr(ak, "stock_sector_spot", None)
        _dt33 = getattr(ak, "stock_sector_detail", None)
        if _sp33 is None or _dt33 is None:
            _why32.append("新浪:stock_sector_spot/detail不存在")
        else:
            for _ind33 in (["概念", "新浪行业"] if kind != "行业"
                           else ["新浪行业", "概念"]):
                try:
                    _lst33 = with_retry(lambda i=_ind33: _sp33(indicator=i),
                                        tries=1, wait=1, timeout=25)
                    if _lst33 is None or len(_lst33) == 0:
                        _why32.append(f"新浪{_ind33}:名单空")
                        continue
                    _ln33 = pick_col(_lst33, ["板块", "label", "name", "板块名称"])
                    _lc33 = pick_col(_lst33, ["label", "板块代码", "code"])
                    if not _ln33 or not _lc33:
                        _why32.append(f"新浪{_ind33}:列名{list(_lst33.columns)[:4]}")
                        continue
                    _t33 = _nz32(board_name)
                    _row33 = None
                    for _, r in _lst33.iterrows():
                        if _nz32(r[_ln33]) == _t33:
                            _row33 = r
                            break
                    if _row33 is None:
                        for _, r in _lst33.iterrows():
                            _v = _nz32(r[_ln33])
                            if _v and (_v in _t33 or _t33 in _v):
                                _row33 = r
                                break
                    if _row33 is None:
                        _why32.append(f"新浪{_ind33}:{len(_lst33)}个板块里没有它")
                        continue
                    _df33 = with_retry(lambda k=_row33[_lc33]: _dt33(sector=str(k)),
                                       tries=1, wait=1, timeout=25)
                    _out33 = _parse32(_df33) if _df33 is not None and len(_df33) else []
                    if _out33:
                        _cache_put(CONS_CACHE_FILE, _ck, _out33)
                        w(f"    [patch33] {board_name} 成分股经【新浪{_ind33}】取得{len(_out33)}只")
                        return _out33
                    _why32.append(f"新浪{_ind33}:成分股空/字段对不上")
                except Exception as e:
                    _why32.append(f"新浪{_ind33}:{type(e).__name__}")
    except Exception as e:
        _why32.append(f"新浪兜底异常:{type(e).__name__}")

    try:
        w(f"    [patch32诊断] {kind}『{board_name}』成分股全失败：{' ｜ '.join(_why32[:6])}")
    except Exception:
        pass
    return []'''

s = s.replace(A, NEW, 1)
io.open(path, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n# " + MARK + "\n")
print("OK 1: 已加新浪成分股兜底 → " + path)

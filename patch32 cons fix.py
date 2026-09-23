# -*- coding: utf-8 -*-
"""
patch32_cons_fix.py —— 修【概念板块成分股一直取不到】
2026-09-23 r690：玻璃基板(跳351位全场第1)、PET铜箔、BC电池
  三个最强概念全部"成分股接口失败" → 领涨挖掘只能给元件/非金属材料，
  最该挖的三个板块一个都没挖到。

根因两条：
  ① _board_cons 里 `except Exception: continue` —— 错误被吞，
     跑了一个月都不知道到底是函数不存在、超时、还是名字对不上。
  ② 只试了【按名字】取成分股。同花顺概念接口通常要【概念代码】，
     名字对不上就空手而归。

修法：
  ① 每个源失败都打印原因（函数不存在/超时/返回空/异常类型），一板块只打一次
  ② 加两条兜底：
     · 同花顺：先拉概念名单 stock_board_concept_name_ths → 名字找代码 → 用代码取成分股
     · 东财：先拉概念名单 stock_board_concept_name_em → 模糊匹配 → 再取成分股
  ③ 名字归一化（去"概念/板块/Ⅱ/Ⅲ/空格"）后再比对
"""
import io, os, sys
MARK = "patch32_cons_fix"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch32 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch32 已打过"); sys.exit(0)

A = '''    for tag, fname in fns:
        fn = getattr(ak, fname, None)
        if fn is None:
            continue
        try:
            df = with_retry(lambda: fn(symbol=board_name), tries=1, wait=1, timeout=20)
            if df is None or len(df) == 0:
                continue
            cc = pick_col(df, ["代码", "股票代码", "code"])
            cn = pick_col(df, ["名称", "股票简称", "name"])
            if not cc:
                continue
            out = []
            for _, r in df.iterrows():
                c = str(r[cc])[-6:]
                n = str(r[cn]).strip() if cn else ""
                if c.isdigit():
                    out.append((c, n))
            if out:
                _cache_put(CONS_CACHE_FILE, _ck, out)
                return out
        except Exception:
            continue
    return []'''

if A not in s:
    print("!! patch32 中止：_board_cons 锚点未命中"); sys.exit(0)

NEW = '''    # ''' + MARK + '''：失败原因必须可见 + 两条兜底路径
    _why32 = []

    def _nz32(x):
        return (str(x).replace("概念", "").replace("板块", "")
                .replace("Ⅱ", "").replace("Ⅲ", "").replace(" ", "").strip())

    def _parse32(df):
        cc = pick_col(df, ["代码", "股票代码", "code"])
        cn = pick_col(df, ["名称", "股票简称", "name"])
        if not cc:
            return []
        out = []
        for _, r in df.iterrows():
            c = str(r[cc])[-6:]
            n = str(r[cn]).strip() if cn else ""
            if c.isdigit():
                out.append((c, n))
        return out

    # 路径1：按名字直取（原逻辑）
    for tag, fname in fns:
        fn = getattr(ak, fname, None)
        if fn is None:
            _why32.append(f"{tag}:函数{fname}不存在")
            continue
        try:
            df = with_retry(lambda: fn(symbol=board_name), tries=1, wait=1, timeout=20)
            if df is None or len(df) == 0:
                _why32.append(f"{tag}:按名字返回空")
                continue
            out = _parse32(df)
            if out:
                _cache_put(CONS_CACHE_FILE, _ck, out)
                return out
            _why32.append(f"{tag}:字段对不上")
        except Exception as e:
            _why32.append(f"{tag}:{type(e).__name__}")

    # 路径2：先拉板块名单拿【代码】，再用代码取成分股
    _listfns = ([("同花顺", "stock_board_industry_name_ths", "stock_board_industry_cons_ths"),
                 ("东财", "stock_board_industry_name_em", "stock_board_industry_cons_em")]
                if kind == "行业" else
                [("同花顺", "stock_board_concept_name_ths", "stock_board_concept_cons_ths"),
                 ("东财", "stock_board_concept_name_em", "stock_board_concept_cons_em")])
    _n0 = _nz32(board_name)
    for tag, lname, cname in _listfns:
        lf, cf = getattr(ak, lname, None), getattr(ak, cname, None)
        if lf is None or cf is None:
            _why32.append(f"{tag}:名单函数缺失")
            continue
        try:
            lst = with_retry(lambda: lf(), tries=1, wait=1, timeout=20)
            if lst is None or len(lst) == 0:
                _why32.append(f"{tag}:名单为空")
                continue
            _nc = pick_col(lst, ["name", "板块名称", "概念名称", "行业名称", "分类名称"])
            _cd = pick_col(lst, ["code", "板块代码", "代码", "序号"])
            if not _nc:
                _why32.append(f"{tag}:名单无名称列({list(lst.columns)[:4]})")
                continue
            _hit = None
            for _, r in lst.iterrows():
                if _nz32(r[_nc]) == _n0:
                    _hit = r
                    break
            if _hit is None:
                for _, r in lst.iterrows():
                    _v = _nz32(r[_nc])
                    if _v and (_v in _n0 or _n0 in _v):
                        _hit = r
                        break
            if _hit is None:
                _why32.append(f"{tag}:名单{len(lst)}个里没有『{board_name}』")
                continue
            for _key in ([_hit[_cd]] if _cd else []) + [_hit[_nc]]:
                try:
                    df = with_retry(lambda k=_key: cf(symbol=str(k)),
                                    tries=1, wait=1, timeout=20)
                    out = _parse32(df) if df is not None and len(df) else []
                    if out:
                        _cache_put(CONS_CACHE_FILE, _ck, out)
                        w(f"    [patch32] {board_name} 成分股经兜底取得{len(out)}只"
                          f"（{tag}·{'代码' if _key is not _hit[_nc] else '名单名'}）")
                        return out
                except Exception as e:
                    _why32.append(f"{tag}:取成分股{type(e).__name__}")
        except Exception as e:
            _why32.append(f"{tag}:名单{type(e).__name__}")

    try:
        w(f"    [patch32诊断] {kind}『{board_name}』成分股全失败：{' ｜ '.join(_why32[:5])}")
    except Exception:
        pass
    return []'''

s = s.replace(A, NEW, 1)
io.open(path, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n# " + MARK + "\n")
print("OK 1: 成分股加了两条兜底路径 + 失败原因打印 → " + path)

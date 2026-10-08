# -*- coding: utf-8 -*-
"""
patch_usa50_json.py —— 美股扫描器：把每只美股的涨跌另存一份机器可读的 reports/us_quote.json
给 A股扫描器的【美股联动核对】(patch51) 读。只改 scanner_usa.py。
"""
import io, os, sys
MARK = "patch_usa50_json"
path = next((c for c in ["scanner_usa.py", "scanner_usa__1_.py"] if os.path.exists(c)), None)
if not path:
    print("跳过 patch_usa50：找不到 scanner_usa.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch_usa50 已打过"); sys.exit(0)
A = '''    os.makedirs("reports", exist_ok=True)
    text = "\\n".join(REPORT)
    date = bj.strftime("%Y%m%d")'''
if s.count(A) != 1:
    print("!! patch_usa50 中止：报告写出锚点命中 %d 次" % s.count(A)); sys.exit(0)
NEW = A + '''
    # ''' + MARK + '''：机器可读行情，供A股【美股联动核对】
    try:
        _q50 = {k: [round(v[0], 2), v[1], v[2]] for k, v in US_QUOTE.items()}
        _n50 = {tk: cn for cn, tk in US_TICKERS}
        with open("reports/us_quote.json", "w", encoding="utf-8") as _f50:
            json.dump({"made": bj.strftime("%Y-%m-%d %H:%M"), "quote": _q50,
                       "name": _n50}, _f50, ensure_ascii=False)
        print(f"[patch_usa50] us_quote.json 写入 {len(_q50)} 只")
    except Exception as _e50:
        print(f"!! [patch_usa50] us_quote.json 写入失败：{type(_e50).__name__}: {_e50}")'''
s = s.replace(A, NEW, 1)
io.open(path, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n# " + MARK + "\n")
print("OK 1: 美股行情将另存 reports/us_quote.json → " + path)

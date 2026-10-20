# -*- coding: utf-8 -*-
"""
patch_lhb50_runnum.py —— 龙虎榜报告加一份带运行号的副本 reports/lhb<运行号>.txt
原因：龙虎榜_日期.txt 同一天文件名不变，AI 的抓取器按网址缓存，
     10/20 18:58 重跑后 AI 读到的仍是 01:10 那份旧报告。
"""
import io, os, sys
MARK = "patch_lhb50_runnum"
path = next((c for c in ["scanner_lhb.py", "scanner_lhb__1_.py"] if os.path.exists(c)), None)
if not path:
    print("跳过 patch_lhb50：找不到 scanner_lhb.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch_lhb50 已打过"); sys.exit(0)
A = '''    for p in [f"reports/龙虎榜_最新.txt", f"reports/龙虎榜_{d}.txt"]:
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)'''
if s.count(A) != 1:
    print("!! patch_lhb50 中止：写文件锚点命中 %d 次" % s.count(A)); sys.exit(0)
B = '''    _rn50 = os.environ.get("GITHUB_RUN_NUMBER") or bj.strftime("%m%d%H%M")   # ''' + MARK + '''
    for p in [f"reports/龙虎榜_最新.txt", f"reports/龙虎榜_{d}.txt", f"reports/lhb{_rn50}.txt"]:
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    print(f"★发给AI：https://micozik.github.io/scanner/reports/lhb{_rn50}.txt")'''
s = s.replace(A, B, 1)
io.open(path, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n# " + MARK + "\n")
print("OK 1: 龙虎榜将另存 reports/lhb<运行号>.txt → " + path)

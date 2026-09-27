# -*- coding: utf-8 -*-
"""
patch44_winrate_early.py —— 修 patch43 的顺序错误
r727实测：报告里仍是『热力图（历史57.4%）』，也没有任何 [patch43] 行
根因（我的错）：
  · patch43 把 _refresh_winrate43() 插在第8653行，
    而报告显示的胜率表在第8627行就已经打印完了 → 先打印、后刷新
  · 文件不存在时 continue 静默跳过，又是『吞错误』
修法：
  ① 函数定义完立刻在【模块加载时】执行一次 → 之后所有地方读到的都是实时值
  ② 文件不存在/无_acc 也写进日志，不再静默
"""
import io, os, sys
MARK = "patch44_winrate_early"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch44 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch44 已打过"); sys.exit(0)
if "def _refresh_winrate43():" not in s:
    print("!! patch44 中止：没找到 patch43 的函数（先打 patch43）"); sys.exit(0)
ok = 0

# ② 静默跳过 → 记日志
A = '''            if not _fp or not os.path.exists(_fp):
                continue'''
if A in s:
    s = s.replace(A, '''            if not _fp or not os.path.exists(_fp):
                _log.append(f"{_nm}:回测文件不存在({_fp})")   # ''' + MARK + '''
                continue''', 1); ok += 1

# ① 模块加载时立刻执行
B = '''    globals()["_WR_LOG43"] = _log
    return _log


'''
if B in s:
    s = s.replace(B, B + '''# ''' + MARK + '''：模块加载时就刷新，保证所有打印都用实时胜率
try:
    _refresh_winrate43()
except Exception as _e44:
    globals()["_WR_LOG43"] = [f"刷新失败:{type(_e44).__name__}"]


''', 1); ok += 1
    print("OK 1: 胜率刷新改为程序启动时执行")
else:
    print("!! 1: 函数结尾锚点未命中")

io.open(path, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n# " + MARK + "\n")
print("patch44 完成 %d/2 → %s" % (ok, path))

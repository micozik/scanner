# -*- coding: utf-8 -*-
"""
patch18_runnum.py —— 只做一件事：
每次跑完，除了 reports/latest.txt，再多写一份
    reports/r<运行号>.txt
例如第625次运行 → reports/r625.txt

★为什么要这个★
AI这边的抓取工具按URL做缓存，而且会把 ?v=xxx 参数整个剥掉。
所以 latest.txt 这种固定URL，第一次抓是新鲜的，
之后同一个URL会一直返回第一次那份缓存，永远看不到新报告。
2026-09-16 实测：扫描#625成功、Pages也部署了，
AI连抓三次全是11:49那份旧的 —— 卡在AI的缓存上，不是仓库问题。

修法：文件名带运行号，每次跑URL都不同 → 缓存不可能命中。
  运行号从 GITHUB_RUN_NUMBER 读（Actions自动注入，无需改yml）。
  本地跑没有这个变量时，退回用时间戳。

★用法★
  跑完在 Actions 首页看到「A股自动扫描 #625」，
  把 625 换进下面这条发给AI：
    https://micozik.github.io/scanner/reports/r625.txt
"""
import io
import os
import sys

MARK = "patch18_runnum"
CANDIDATES = ["scanner_cloud.py", "scanner_cloud__1_.py"]

path = None
for c in CANDIDATES:
    if os.path.exists(c):
        path = c
        break
if path is None:
    print("!! patch18 中止：找不到 scanner_cloud.py")
    sys.exit(0)

with io.open(path, "r", encoding="utf-8") as f:
    s = f.read()

if MARK in s:
    print("OK 0: patch18 已打过，跳过（幂等）")
    sys.exit(0)

# 找写 latest.txt 的那一行，在它后面追加一份带运行号的副本
A = 'for p in [f"reports/latest.txt"'
if A not in s:
    # 兼容另一种写法
    A2 = '"reports/latest.txt"'
    if A2 not in s:
        print("!! patch18 中止：找不到写 latest.txt 的位置")
        sys.exit(0)

# 在文件末尾加一个独立函数 + 在主流程结束时调用它太复杂，
# 改用最稳的办法：包装内置 open 不可行 →
# 直接在写完 latest.txt 之后补一次复制。
ANCHOR = None
for cand in [
    'for p in [f"reports/latest.txt", f"reports/{d}.txt"]:',
    'for p in ["reports/latest.txt"]:',
]:
    if cand in s:
        ANCHOR = cand
        break

if ANCHOR is None:
    # 兜底：在脚本最末尾追加一段，程序退出前复制一次
    s = s.rstrip("\n") + '''


# ''' + MARK + '''：额外写一份带运行号的副本，URL每次唯一
try:
    import shutil as _sh18
    import os as _os18
    _rn18 = _os18.environ.get("GITHUB_RUN_NUMBER")
    if not _rn18:
        import datetime as _dt18
        _rn18 = _dt18.datetime.now().strftime("%m%d%H%M")
    _src18 = "reports/latest.txt"
    if _os18.path.exists(_src18):
        _dst18 = "reports/r%s.txt" % _rn18
        _sh18.copyfile(_src18, _dst18)
        print("OK patch18: 已另存 %s" % _dst18)
        print("★把这条发给AI：https://micozik.github.io/scanner/reports/r%s.txt"
              % _rn18)
except Exception as _e18:
    print("patch18 复制失败：%s" % type(_e18).__name__)
'''
    print("OK 1: 已在脚本末尾追加运行号副本逻辑（兜底方式）")
else:
    s = s.replace(ANCHOR, ANCHOR, 1)
    s = s.rstrip("\n") + '''


# ''' + MARK + '''：额外写一份带运行号的副本，URL每次唯一
try:
    import shutil as _sh18
    import os as _os18
    _rn18 = _os18.environ.get("GITHUB_RUN_NUMBER")
    if not _rn18:
        import datetime as _dt18
        _rn18 = _dt18.datetime.now().strftime("%m%d%H%M")
    _src18 = "reports/latest.txt"
    if _os18.path.exists(_src18):
        _dst18 = "reports/r%s.txt" % _rn18
        _sh18.copyfile(_src18, _dst18)
        print("OK patch18: 已另存 %s" % _dst18)
        print("★把这条发给AI：https://micozik.github.io/scanner/reports/r%s.txt"
              % _rn18)
except Exception as _e18:
    print("patch18 复制失败：%s" % type(_e18).__name__)
'''
    print("OK 1: 已追加运行号副本逻辑（锚点命中：%s）" % ANCHOR[:40])

with io.open(path, "w", encoding="utf-8") as f:
    f.write(s)
print("patch18 完成 → %s" % path)

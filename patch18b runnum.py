# -*- coding: utf-8 -*-
"""
patch18b_runnum.py —— 只做一件事：
每次跑完，除 reports/latest.txt 外，再写一份 reports/r<运行号>.txt

★patch18 失败原因（我自己的错）★
  scanner_cloud.py 最后一行是 sys.exit(0)，
  我把复制代码追加在文件末尾 = 追加到了 sys.exit 之后 = 永远执行不到。
  → 本版改为插在 sys.exit(0) 【之前】。

★为什么需要这个★
  AI的抓取工具按URL做缓存，且会把 ?v=xxx 参数整个剥掉。
  latest.txt 这种固定URL，第一次抓是新鲜的，之后永远返回那份缓存。
  2026-09-16实测：扫描#625成功、Pages也部署了，
  AI连抓三次全是11:49那份 —— 卡在AI缓存上，不是仓库问题。
  文件名带运行号 → 每次URL不同 → 缓存不可能命中。

★用法★
  跑完在 Actions 首页看「A股自动扫描 #626」，把626换进：
    https://micozik.github.io/scanner/reports/r626.txt
  （Actions日志末尾也会直接打印这条链接，复制那条更快）
"""
import io
import os
import sys

MARK = "patch18b_runnum"
CANDIDATES = ["scanner_cloud.py", "scanner_cloud__1_.py"]

path = None
for c in CANDIDATES:
    if os.path.exists(c):
        path = c
        break
if path is None:
    print("!! patch18b 中止：找不到 scanner_cloud.py")
    sys.exit(0)

with io.open(path, "r", encoding="utf-8") as f:
    s = f.read()

if MARK in s:
    print("OK 0: patch18b 已打过，跳过（幂等）")
    sys.exit(0)

# 清掉 patch18 留在 sys.exit 之后的死代码（如果打过）
if "patch18_runnum" in s:
    _i = s.find("\n\n# patch18_runnum")
    if _i > 0:
        s = s[:_i] + "\n"
        print("OK 0b: 已清除 patch18 遗留的死代码（在sys.exit之后，从未执行）")

A = """    # ★永远 exit 0：报告写出来了就算成功，不要因为某个模块挂了就整体失败
    sys.exit(0)"""

if A not in s:
    print("!! patch18b 中止：找不到 sys.exit(0) 锚点")
    sys.exit(0)

NEW = '''    # ''' + MARK + '''：另存一份带运行号的副本，URL每次唯一
    try:
        import shutil as _sh18
        _rn18 = os.environ.get("GITHUB_RUN_NUMBER")
        if not _rn18:
            _rn18 = now_beijing().strftime("%m%d%H%M")
        if os.path.exists("reports/latest.txt"):
            _dst18 = "reports/r%s.txt" % _rn18
            _sh18.copyfile("reports/latest.txt", _dst18)
            print("OK patch18b: 已另存 %s" % _dst18)
            print("=" * 60)
            print("★把下面这条发给AI（每次运行号都不同，缓存打不中）：")
            print("https://micozik.github.io/scanner/reports/r%s.txt" % _rn18)
            print("=" * 60)
        else:
            print("!! patch18b: reports/latest.txt 不存在，没得复制")
    except Exception as _e18:
        print("!! patch18b 复制失败：%s: %s"
              % (type(_e18).__name__, str(_e18)[:60]))

    # ★永远 exit 0：报告写出来了就算成功，不要因为某个模块挂了就整体失败
    sys.exit(0)'''

s = s.replace(A, NEW, 1)
print("OK 1: 复制逻辑已插在 sys.exit(0) 之前")

with io.open(path, "w", encoding="utf-8") as f:
    f.write(s)
print("patch18b 完成 → %s" % path)

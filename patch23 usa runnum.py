# -*- coding: utf-8 -*-
"""
patch23_usa_runnum.py —— 只做一件事：
美股报告也写一份带【运行号】的副本，让AI能抓到。

★2026-09-18 事故★
  美股夜盘扫描 #107 今早07:01跑完、Success、4m24s，报告确实生成了。
  但AI用尽所有URL形式去抓 reports/美股_最新.txt：
      Pages / jsdelivr@main / jsdelivr@SHA / raw / blob
  ★全部命中AI侧的缓存，返回的是 2026-07-15 的 V1.0 版本★
  （blob两次抓取的 meta-request-id 完全相同，证明是纯缓存）
  最后只能改用公开财经源搜索美股收盘数据。

  根因：AI的抓取工具按URL缓存，且会剥掉 ?v= 参数。
  固定文件名的URL一旦被缓存，就永远抓不到新内容。

  ★A股那边已经用 patch18b 解决了：文件名带 GITHUB_RUN_NUMBER，
    每次运行URL都不同 → 缓存不可能命中。美股照搬同一个办法。★

★用法★
  跑完在 Actions 看「美股夜盘扫描 #108」，把108换进：
    https://micozik.github.io/scanner/reports/us108.txt
  （日志末尾会直接打印这条链接，复制那条更快）

⚠️ 前提：scan_usa.yml 里必须有【应用补丁】这一步，
   即 `for f in patch*.py; do python "$f"; done`。
   若没有，本补丁不会被执行 —— 见下方提示。
"""
import io
import os
import sys

MARK = "patch23_usa_runnum"
CANDIDATES = ["scanner_usa.py", "scanner_usa__1_.py"]

path = None
for c in CANDIDATES:
    if os.path.exists(c):
        path = c
        break
if path is None:
    print("跳过 patch23：找不到 scanner_usa.py（A股扫描不需要它）")
    sys.exit(0)

with io.open(path, "r", encoding="utf-8") as f:
    s = f.read()

if MARK in s:
    print("OK 0: patch23 已打过，跳过（幂等）")
    sys.exit(0)

A = '''    for p in [f"reports/美股_最新.txt", f"reports/美股_{date}.txt"]:
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    print("\\n✅ 美股扫描V4.1完成 reports/美股_最新.txt")'''

if A not in s:
    print("!! patch23 中止：找不到写文件的锚点")
    sys.exit(0)

NEW = '''    # ''' + MARK + '''：加一份带运行号的副本，URL每次唯一
    _rn23 = os.environ.get("GITHUB_RUN_NUMBER") or bj.strftime("%m%d%H%M")
    _outs23 = [f"reports/美股_最新.txt", f"reports/美股_{date}.txt",
               f"reports/us{_rn23}.txt"]
    for p in _outs23:
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    print("\\n✅ 美股扫描V4.1完成 reports/美股_最新.txt")
    print("=" * 60)
    print("★报告时间戳（核对是不是今天的）：")
    print(REPORT[1] if len(REPORT) > 1 else "(空)")
    print("")
    print("★把下面这条发给AI（每次运行号都不同，缓存打不中）：")
    print(f"https://micozik.github.io/scanner/reports/us{_rn23}.txt")
    print("=" * 60)'''

s = s.replace(A, NEW, 1)
print("OK 1: 已加 reports/us<运行号>.txt + 日志打印链接")

s = s.rstrip("\n") + "\n\n# " + MARK + "：美股报告运行号副本\n"
with io.open(path, "w", encoding="utf-8") as f:
    f.write(s)
print("patch23 完成 → %s" % path)
print("")
print("⚠️ 记得确认 scan_usa.yml 里有【应用补丁】这一步：")
print("   - name: 应用补丁")
print("     run: |")
print("       for f in patch*.py; do")
print('         if [ -f "$f" ]; then echo "--- $f ---"; python "$f"; fi')
print("       done")
print("   没有这一步，本补丁永远不会被执行。")

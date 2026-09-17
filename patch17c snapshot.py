# -*- coding: utf-8 -*-
"""
patch17c_snapshot.py —— 只做一件事：
把今天抓到的板块榜存进内存，供【启动日雷达】在盘中算跳升。

★为什么要第三版★
  patch17b 的步骤1 锚点用的是函数【定义】：
      def _save(store, hist, path, label):
          if not store or not can_save:
  仓库里有 30+ 个补丁，按 shell 字母序执行时
  patch.py / patch usdate.py / patch usa chain.py / patch3~11
  全排在 patch17b 【前面】（空格和小数字优先）。
  其中任何一个动过 _save 那一段，锚点就匹配不上，
  patch17b 步骤1 静默中止 → globals 里永远没有快照
  → 报告里出现「⚠️ 内存里也没有今天的快照」
  → 跳升榜连续3天报空，而同一份报告的【每日选股】
    却能列出「转基因跳386位」—— 数据在，只是没传到雷达手里。

★本版改用【调用点】做锚点（第2829/2830行）：
      _save(saved_ind, hist_ind, HIST_FILE, "行业")
      _save(saved_con, hist_con, CONCEPT_FILE, "概念")
  调用点是原始代码的主流程，老补丁改函数体也不会碰它。

★并且把诊断直接 w() 进报告★
  以后不用再进 Actions 翻日志 —— 报告里会直接写
  「[patch17c] 板块快照已存内存：行业90个 / 概念387个」
  没有这一行，就说明锚点又没命中。
"""
import io
import os
import sys

MARK = "patch17c_snapshot"
CANDIDATES = ["scanner_cloud.py", "scanner_cloud__1_.py"]

path = None
for c in CANDIDATES:
    if os.path.exists(c):
        path = c
        break
if path is None:
    print("!! patch17c 中止：找不到 scanner_cloud.py")
    sys.exit(0)

with io.open(path, "r", encoding="utf-8") as f:
    s = f.read()

if MARK in s:
    print("OK 0: patch17c 已打过，跳过（幂等）")
    sys.exit(0)

A = '''    _save(saved_ind, hist_ind, HIST_FILE, "行业")
    _save(saved_con, hist_con, CONCEPT_FILE, "概念")'''

if A not in s:
    print("!! patch17c 中止：连调用点锚点都没命中，")
    print("   说明 _save 调用被老补丁改写过，需要人工看代码")
    sys.exit(0)

NEW = '''    # ''' + MARK + '''：把本次板块榜存进内存，供启动日雷达盘中用
    try:
        globals()["TODAY_BOARD_行业"] = saved_ind
        globals()["TODAY_BOARD_概念"] = saved_con
        w(f"  [patch17c] 板块快照已存内存："
          f"行业{len(saved_ind)}个 / 概念{len(saved_con)}个")
        if not saved_ind and not saved_con:
            w("  [patch17c] ⚠️ 两个都是空的 —— 板块榜本次抓取失败")
    except Exception as _e17c:
        w(f"  [patch17c] 存内存失败：{type(_e17c).__name__}")

    _save(saved_ind, hist_ind, HIST_FILE, "行业")
    _save(saved_con, hist_con, CONCEPT_FILE, "概念")'''

s = s.replace(A, NEW, 1)
print("OK 1: 已在 _save 调用点前插入内存快照（锚点：主流程调用点）")

s = s.rstrip("\n") + "\n\n# " + MARK + "：板块快照存内存\n"
with io.open(path, "w", encoding="utf-8") as f:
    f.write(s)
print("patch17c 完成 → %s" % path)

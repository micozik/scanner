# -*- coding: utf-8 -*-
"""
patch16b_budget.py —— 只做一件事：
把脚本内部的【全局预算】从 1020秒(17分) 提到 2700秒(45分)。

2026-09-15 实测：扫描跑了 18分02秒，超过内部预算17分钟后，
  下面7个模块被全部跳过：
    【异动无解释】【定增破发雷达】【今日隐形主线】
    【板块轮动器】【预启动雷达】【每日选股(稳定版)】【跳升榜回测】
  其中【每日选股】和【板块轮动器】直接影响选股，
  被砍掉等于每天少两只候选。

根因：GitHub 的 timeout-minutes 已提到90分钟，
  但脚本内部这道闸门还卡在17分钟，是两套独立的限制。
  （代码原注释写「# 13分钟」也是错的，1020秒=17分钟）

⚠️ 环境变量优先：若 scan.yml 里显式写了 HARD_LIMIT，
   本补丁无效，必须同时改 yml，或删掉那一行让默认值生效。
"""
import io
import os
import sys

MARK = "patch16b_budget_2700"
CANDIDATES = ["scanner_cloud.py", "scanner_cloud__1_.py"]

path = None
for c in CANDIDATES:
    if os.path.exists(c):
        path = c
        break
if path is None:
    print("跳过 patch16b：找不到 scanner_cloud.py")
    sys.exit(0)

with io.open(path, "r", encoding="utf-8") as f:
    s = f.read()

if MARK in s:
    print("OK 0: patch16b 已打过，跳过（幂等）")
    sys.exit(0)

# 只换数字，不在表达式里插注释（那会插进括号内导致语法错）
OLD = '"HARD_LIMIT", "1020"'
NEW = '"HARD_LIMIT", "2700"'

n = s.count(OLD)
if n == 0:
    print("!! 锚点 HARD_LIMIT 未命中，patch16b 中止")
    sys.exit(0)

s = s.replace(OLD, NEW)
print("OK 1: 已把 %d 处全局预算 1020秒 → 2700秒" % n)

# 幂等标记单独放在文件末尾的注释行，不碰任何表达式
s = s.rstrip("\n") + "\n\n# " + MARK + "：全局预算已由 1020s 提到 2700s\n"
print("OK 2: 已写入幂等标记")

with io.open(path, "w", encoding="utf-8") as f:
    f.write(s)

print("patch16b 完成 → %s" % path)

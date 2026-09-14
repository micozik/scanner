# -*- coding: utf-8 -*-
"""
patch15_jump_fresh.py —— 只做一件事：
启动日雷达不许拿【不是今天】的历史库算跳升。

根因（scanner_cloud.py 第4241行）：
  pr, cu = _rank(hist[days[-2]]), _rank(hist[days[-1]])
  取库里最后两天做比较，★从不检查 days[-1] 是不是今天★。

2026-09-14 实例：
  【三、板块全景榜】报空「概念全源失败」→ 概念库今天没写入
  → days[-1] 还是 09-11，days[-2] 是 09-10
  → 雷达拿两天前比三天前，算出云游戏跳367位、DRG/DIP跳357位
  → 数据没变，所以盘中12:40和盘后18:19两份报告的前15条一字不差
  → 更糟的是：这些300多位的陈旧概念跳升，把今天真实的
     行业跳升（医疗服务69位/生物制品70位/电池53位）全部挤出前15
  → 铁律Q要求「按跳升榜当天出手」，而榜上没有一条今天的数据

修法：比较前先核对 days[-1] 是否等于今天。
  不是今天 → 整个库跳过，并明写「X库最后数据是哪天、为什么没今天的」
  ★宁可报空，不许拿陈旧数据冒充今日信号（铁律Y③）
"""
import io
import os
import sys

MARK = "★patch15：跳升榜新鲜度闸门★"
CANDIDATES = ["scanner_cloud.py", "scanner_cloud__1_.py"]

path = None
for c in CANDIDATES:
    if os.path.exists(c):
        path = c
        break
if path is None:
    print("跳过 patch15：找不到 scanner_cloud.py")
    sys.exit(0)

with io.open(path, "r", encoding="utf-8") as f:
    s = f.read()

if MARK in s:
    print("OK 0: patch15 已打过，跳过（幂等）")
    sys.exit(0)

A = "            pr, cu = _rank(hist[days[-2]]), _rank(hist[days[-1]])"
if s.count(A) != 1:
    print("!! 锚点命中 %d 次（需恰好1次），patch15 中止" % s.count(A))
    sys.exit(0)

NEW = '''            # ''' + MARK + '''
            # 库的最后一天必须是今天，否则算出来的是陈年跳升
            _today = now_beijing().strftime("%Y-%m-%d")
            _last = str(days[-1])[:10]
            if _last != _today:
                w(f"  [报空] {kind}库最后数据是 {_last}，不是今天({_today})")
                w(f"     → 今天该源抓取失败，★不拿旧数据冒充今日跳升★（铁律Y③）")
                w(f"     → 去【三、板块全景榜】看它报的是哪个错")
                continue
            pr, cu = _rank(hist[days[-2]]), _rank(hist[days[-1]])'''

s = s.replace(A, NEW, 1)
print("OK 1: 已加新鲜度闸门")

with io.open(path, "w", encoding="utf-8") as f:
    f.write(s)

print("patch15 完成 → %s" % path)

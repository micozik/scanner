# -*- coding: utf-8 -*-
"""
patch_probe.py  ——  放在仓库【根目录】，和 scanner_cloud.py 同一层

★这个文件【不修改任何代码】★
   它只做一件事：把四处有问题的代码，原样打印到 Actions 日志里，
   让我看清真实写法后，再给你一次改对的修复文件。

★为什么要这一步★
   scanner_cloud.py 有 7800 行 / 376KB，我读不完整。
   凭记忆猜锚点去改 = patch10 那种【静默失败】：
   补丁装了、日志没报错、但一行都没生效。
   宁可多走这一步，也不要修三次。

★安全性★
   · 全程只读，不写任何文件
   · 找不到就打印"未找到"，不报错、不中断流水线
   · 重复跑无副作用

★用完请删除★（它每次运行都会刷屏日志）
"""

import io
import os

TARGET = "scanner_cloud.py"

# 要定位的四处：关键词 → 这处是干什么的
PROBES = [
    ("已过及格线",        "【BUG二】铁律S的10%门槛判断，香农8.89%被判成已过10%"),
    ("当前最优",          "【BUG一】公告源挑选逻辑，按条数挑→挑中了无代码的源"),
    ("无代码(定位不到个股)", "【BUG一】标记无代码源的地方"),
    ("龙虎榜·东财失败",    "【BUG三】主扫描器的龙虎榜取数，三源全挂"),
    ("CHAIN_MAP",         "【BUG四】驱动链映射表，冷低早6只查不到"),
]

BEFORE = 12   # 命中行的前几行
AFTER = 28    # 命中行的后几行


def run():
    if not os.path.exists(TARGET):
        print("🔴 patch_probe: 找不到 %s" % TARGET)
        return

    lines = io.open(TARGET, encoding="utf-8").read().split("\n")
    print("=" * 70)
    print("🔬 patch_probe 开始 | %s 共 %d 行" % (TARGET, len(lines)))
    print("=" * 70)

    for kw, why in PROBES:
        hits = [i for i, ln in enumerate(lines) if kw in ln]

        print("")
        print("─" * 70)
        print("🔎 关键词：%s" % kw)
        print("   用途：%s" % why)
        print("   命中 %d 处" % len(hits))
        print("─" * 70)

        if not hits:
            print("   （未找到，换关键词再探）")
            continue

        # 最多打印前2处，避免日志爆炸
        for h in hits[:2]:
            lo = max(0, h - BEFORE)
            hi = min(len(lines), h + AFTER)
            print("")
            print("   ===== 第 %d 行附近 =====" % (h + 1))
            for i in range(lo, hi):
                mark = ">>>" if i == h else "   "
                print("   %s %5d | %s" % (mark, i + 1, lines[i]))

        if len(hits) > 2:
            print("")
            print("   （还有 %d 处未打印，行号：%s）"
                  % (len(hits) - 2, [x + 1 for x in hits[2:]]))

    print("")
    print("=" * 70)
    print("🔬 patch_probe 结束 —— 请把上面内容截图给我")
    print("=" * 70)


run()

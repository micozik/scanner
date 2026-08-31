# -*- coding: utf-8 -*-
"""
patch_announce.py  ——  放在仓库【根目录】，和 scanner_cloud.py 同一层

★只做一件事★
   修 scanner_cloud.py 第 6428 行的公告源评分公式。

★问题是什么★
   原式：_score = len(r) * (3 if _hascode else 1)
   实际： 东财资讯快讯 200条 无代码 → 200分  ✅被选中
          股市日历      30条 有代码 →  90分  ❌被淘汰
   → 系统拿到200条【没有股票代码】的公告，
     结果：事件雷达定位不到个股、持仓公告核对失效。
   → 8/28 通光线缆公告『净利由盈转亏』因此没被系统看见。

★怎么修★
   新式：_score = len(r) + (1000000 if _hascode else 0)
   带代码的源加一百万分 —— 任何带代码的源都必然赢过任何无代码的源，
   而同为带代码时，仍然按条数多的优先（保留原意图）。

★安全性★
   · 幂等：装过就跳过
   · 锚点是一整行完整代码，不匹配就原样退出、不改文件
   · 只改这一行，其余 7804 行一个字不动
"""

import io
import os

TARGET = "scanner_cloud.py"

OLD = "_score = len(r) * (3 if _hascode else 1)"
NEW = "_score = len(r) + (1000000 if _hascode else 0)"


def run():
    if not os.path.exists(TARGET):
        print("🔴 patch_announce: 找不到 %s → 未修改" % TARGET)
        return

    src = io.open(TARGET, encoding="utf-8").read()

    if NEW in src:
        print("✅ patch_announce: 已安装过，跳过（幂等，正常现象）")
        return

    n = src.count(OLD)
    if n == 0:
        print("🔴 patch_announce: 锚点未找到 → 未修改")
        print("   找的是这一行：%s" % OLD)
        return
    if n > 1:
        print("🔴 patch_announce: 锚点出现 %d 次，不唯一 → 未修改（防止改错地方）" % n)
        return

    io.open(TARGET, "w", encoding="utf-8").write(src.replace(OLD, NEW))
    print("✅ patch_announce: 已修复公告源评分 —— 带股票代码的源现在绝对优先")


run()

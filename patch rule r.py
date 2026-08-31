# -*- coding: utf-8 -*-
"""
patch_rule_r.py  ——  放在仓库【根目录】，和 scanner_cloud.py 同一层

★只做一件事★
   让 scanner_cloud.py 第 4137-4142 行的止盈提示，
   和它自己在第 4155-4168 行打印的【铁律R】保持一致。

★问题是什么★
   代码第4138行：  pnl >= 10  →  "💎【达标】+10% → 减半锁利，剩余移动止盈"
   而第4156行打印："🔴 已删除『+10%减半』『+20%再减半』—— 这两条是错的"
   ★同一个函数，代码和规则说的是相反的话。★

   用户2026-08-17原话：
     『谁说10%马上跑？我从没说过10%就要跑。
       如果你看好这个板块，为什么在10%的时候跑？★赚钱就尽量多赚★』

   香农芯创 2026-08-31 收盘 +8.89%，只差1.2%就触发这条错误建议。

   另：第4142行的分支条件是 pnl >= 7，却打印"已过及格线(+10%)"，
   把 8.89% 说成过了10%。文字与事实不符。

★不改什么★
   · peak>=20 / peak>=10 的两条（铁律S本体）原样保留
   · drop>=5 那条原样保留（它由另一个补丁在管，本补丁不碰）
   · 其余 7800 行一个字不动

★安全性★
   · 幂等：装过就跳过
   · 锚点是纯中文字符串，不含空格、不依赖缩进
   · 每处都先数出现次数，不等于1就整个放弃、不改文件
"""

import io
import os

TARGET = "scanner_cloud.py"

EDITS = [
    # (旧串, 新串, 说明)
    (
        "减半锁利，剩余移动止盈",
        "过及格线，趋势还在就继续拿（铁律R：不许因为到10%就减）",
        "删掉『+10%减半锁利』——铁律R已推翻这条",
    ),
    (
        "已过及格线(+10%)",
        "已达+7%，尚未到及格线(+10%)",
        "修正把8.89%说成已过10%的错误标注",
    ),
]


def run():
    if not os.path.exists(TARGET):
        print("🔴 patch_rule_r: 找不到 %s → 未修改" % TARGET)
        return

    src = io.open(TARGET, encoding="utf-8").read()

    # 幂等检查
    if EDITS[0][1] in src and EDITS[1][1] in src:
        print("✅ patch_rule_r: 已安装过，跳过（幂等，正常现象）")
        return

    # 先全部校验，任何一处不唯一就整个放弃
    plan = []
    for old, new, why in EDITS:
        if new in src:
            print("   · 已改过，跳过：%s" % why)
            continue
        n = src.count(old)
        if n != 1:
            print("🔴 patch_rule_r: 锚点『%s』出现 %d 次（需要正好1次）→ 整个补丁放弃，未修改任何内容" % (old, n))
            return
        plan.append((old, new, why))

    if not plan:
        print("✅ patch_rule_r: 无需改动")
        return

    for old, new, why in plan:
        src = src.replace(old, new)
        print("   ✅ %s" % why)

    io.open(TARGET, "w", encoding="utf-8").write(src)
    print("✅ patch_rule_r: 完成，铁律R与代码已一致")


run()

# -*- coding: utf-8 -*-
"""
patch_usa_chain.py  ——  放在仓库【根目录】，和 scanner_usa.py 同一层

★这个补丁只做一件事★
    给 scanner_usa.py 里的 CHAIN_TO_US 表补三条缺失的驱动链。

★为什么需要★
    CHAIN_TO_US 原来只有：AI算力链 / 半导体材料链 / 存储涨价链 /
    MLCC涨价链 / 锂电钠电链 / 贵金属链 / 医药链 / AI散热链 /
    AI供电链 / AI+制药CXO链 / 农业 / 用户自定。
    ★没有 CPO光模块链，也没有机器人链★
    → 仕佳光子(CPO)和拓普集团(机器人)跑出来永远是
      "今夜美股无对应标的"，接近三成仓位在美股映射里是盲区。

★安全性★
    · 幂等：已经装过就直接跳过，重复跑不会插两遍
    · 每一步都 print 状态，日志里一眼看得出有没有生效
    · 锚点只认 "CHAIN_TO_US = {" 这一行，不依赖任何具体行号
    · 任何一步没匹配上，就原样退出、不改文件，并印红字
"""

import io
import os

TARGET = "scanner_usa.py"
MARK = "CPO光芯片链"          # 幂等标记：这个词已经在文件里 = 装过了

NEW_LINES = '''    "CPO光芯片链": [("COHR", 1.0), ("GLW", 0.8), ("AVGO", 0.6),
                    ("NVDA", 0.5), ("TSM", 0.4)],
    "机器人执行器链": [("TSLA", 1.0), ("NVDA", 0.4)],
    "电网光缆链": [("GLW", 0.6), ("COHR", 0.4)],
'''


def run():
    if not os.path.exists(TARGET):
        print("🔴 patch_usa_chain: 找不到 %s → 未做任何修改" % TARGET)
        return

    src = io.open(TARGET, encoding="utf-8").read()

    if MARK in src:
        print("✅ patch_usa_chain: 已安装过，跳过（幂等，正常现象）")
        return

    anchor = "CHAIN_TO_US = {"
    i = src.find(anchor)
    if i < 0:
        print("🔴 patch_usa_chain: 锚点 'CHAIN_TO_US = {' 未找到 → 未做任何修改")
        return

    j = src.find("\n", i)
    if j < 0:
        print("🔴 patch_usa_chain: 锚点所在行异常 → 未做任何修改")
        return

    out = src[:j + 1] + NEW_LINES + src[j + 1:]

    io.open(TARGET, "w", encoding="utf-8").write(out)
    print("✅ patch_usa_chain: 已插入 CPO光芯片链 / 机器人执行器链 / 电网光缆链")


run()

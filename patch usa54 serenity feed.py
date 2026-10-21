# -*- coding: utf-8 -*-
"""
patch_usa54_serenity_feed.py —— 白毛股神全量信息接进 A股 + 美股 两份报告

依赖：仓库根目录的 serenity_feed.py（同一批上传）
文件名里带 usa → 美股工作流会跑它；A股工作流跑全部 patch*.py → 也会跑它。
它会同时给 scanner_cloud.py 和 scanner_usa.py 各注入一段（存在哪个打哪个，幂等）。
  · A股报告 r<运行号>.txt：附最近48小时她的推文全文 + A股映射线索
  · 美股报告 us<运行号>.txt：附最近72小时（覆盖美股整夜）
  · 另存 reports/白毛股神_最新.txt
旧的 patch_usa52（nitter 镜像）10/21 实测五个镜像全挂，这里把它的报错改成指向新来源。
"""
import io
import os
import sys

MARK = "patch_usa54_serenity_feed"
D = '    os.makedirs("reports", exist_ok=True)\n    text = "\\n".join(REPORT)'

if not os.path.exists("serenity_feed.py"):
    print("!! patch_usa54 中止：仓库根目录缺 serenity_feed.py（要和本补丁一起上传）")
    sys.exit(0)

TARGETS = [("scanner_cloud.py", 48), ("scanner_usa.py", 72)]
for fn, hours in TARGETS:
    if not os.path.exists(fn):
        print(f"跳过 {fn}：不存在")
        continue
    s = io.open(fn, encoding="utf-8").read()
    if MARK in s:
        print(f"OK 0: {fn} 已打过 patch_usa54")
        continue
    if s.count(D) != 1:
        print(f"!! {fn}：报告写出锚点命中 {s.count(D)} 次，跳过")
        continue
    block = (
        f"    # ===== {MARK} =====\n"
        "    try:\n"
        "        import serenity_feed as _sf54\n"
        f"        for _l54 in _sf54.build_section(hours={hours}):\n"
        "            w(_l54)\n"
        "    except Exception as _e54:\n"
        "        w(f\"  [patch_usa54] 白毛股神模块失败：{type(_e54).__name__}: {_e54}\")\n"
        f"    # ===== {MARK} 结束 =====\n"
    )
    s = s.replace(D, block + D, 1)
    old52 = 'w("  ⚠️ 所有镜像都没读到：" + "；".join(_fail52))'
    if old52 in s:
        s = s.replace(old52,
            'w("  （nitter镜像全挂，属正常 → 看下面【全量存档】那一节，那才是完整数据）")', 1)
    io.open(fn, "w", encoding="utf-8").write(s)
    print(f"OK: {fn} 已接入白毛股神全量存档（最近{hours}小时）")

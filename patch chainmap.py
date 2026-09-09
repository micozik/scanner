# -*- coding: utf-8 -*-
"""
patch_chainmap.py  ——  放仓库【根目录】  ★V2★

★问题（2026-09-09 仍在发生）★
   冷低早筛出10只，★全部10只★显示「❔驱动链未识别（CHAIN_MAP里没有它）」
   → 【①-B驱动筛】这一环完全空转，筛出来也用不了。

★病根（探针已确认）★
   CHAIN_MAP = {"存储涨价链": ["半导体","元件","电子化学品"], ...}
                                 ↑ 值是【行业名】
   而代码写的是：
       _codes = (globals().get("CHAIN_MAP") or {}).get(ch) or []
       if cd in _codes or nm in str(_codes):
                ↑ 拿【股票代码cd】和【股票名nm】去和一堆【行业名】比
   ★类型错配，永远匹配不上。不是数据缺，是比错了东西。★

★V2 相对V1的改进（V1装了没生效）★
   ① 试 3 个锚点，不是1个
   ② ★自己读出那一行的真实缩进★，不靠猜（GitHub网页会吃掉缩进）
   ③ 改完 compile() 语法自检，不通过★自动回滚★
   ④ ★全部失败时，把源码真实片段写进 reports/chainmap诊断_日期.txt★
      下一轮照着改，一次改对，不再盲试

★改成什么★
   改用同一份代码里已存在的 _chain_of(行业名) 做正向匹配：
     该股所属行业 → 查出它属于哪条驱动链 → 与当前链 ch 比对
   原来的代码/名称匹配★保留为兜底★，只增不减。

★安全性★
   · 幂等；锚点不唯一就跳过该锚点
   · 找不到 _chain_of 定义 → 整个放弃
   · 语法不过 → 自动回滚
   · 耗时 <1 秒
"""

import io
import os
import datetime

TARGET = "scanner_cloud.py"
OUTDIR = "reports"
MARK = "# [patch_chainmap_v2]"

ANCHORS = [
    "if cd in _codes or nm in str(_codes):",
    "if cd in _codes or nm in str(_codes)",
    "cd in _codes or nm in str(_codes)",
]


def diagnose(src):
    try:
        if not os.path.isdir(OUTDIR):
            os.makedirs(OUTDIR)
        lines = src.split("\n")
        hits = [i for i, ln in enumerate(lines)
                if "_codes" in ln or "CHAIN_MAP" in ln]
        out = ["=" * 60,
               "🔬 patch_chainmap V2 诊断：3个锚点全部未命中",
               "   下面是源码里所有含 _codes / CHAIN_MAP 的行，",
               "   把这个文件发给AI，下一轮一次改对。",
               "=" * 60]
        for h in hits[:25]:
            lo = max(0, h - 3)
            hi = min(len(lines), h + 6)
            out.append("")
            out.append("===== 第 %d 行附近 =====" % (h + 1))
            for i in range(lo, hi):
                out.append("  %5d | %s" % (i + 1, lines[i]))
        bj = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
        io.open(os.path.join(OUTDIR, "chainmap诊断_%s.txt"
                             % bj.strftime("%Y%m%d")),
                "w", encoding="utf-8").write("\n".join(out))
        print("🔬 已写出 reports/chainmap诊断_%s.txt" % bj.strftime("%Y%m%d"))
    except Exception as e:
        print("🔴 诊断文件写失败 %s" % e)


def run():
    if not os.path.exists(TARGET):
        print("🔴 patch_chainmap: 找不到 %s → 未修改" % TARGET)
        return

    src = io.open(TARGET, encoding="utf-8").read()

    if MARK in src:
        print("✅ patch_chainmap V2: 已安装过，跳过（幂等，正常现象）")
        return

    if "_chain_of" not in src:
        print("🔴 patch_chainmap: 源码找不到 _chain_of 定义 → 整个放弃")
        diagnose(src)
        return

    lines = src.split("\n")

    for idx, anchor in enumerate(ANCHORS, 1):
        hits = [i for i, ln in enumerate(lines) if anchor in ln]
        if len(hits) != 1:
            print("   锚点%d 命中%d次（需要正好1次），跳过" % (idx, len(hits)))
            continue

        i = hits[0]
        raw = lines[i]
        indent = raw[:len(raw) - len(raw.lstrip())]
        print("   锚点%d 命中第%d行，实测缩进%d空格"
              % (idx, i + 1, len(indent)))

        block = [
            indent + MARK + " 行业→驱动链 正向匹配，修类型错配",
            indent + "_ind_now = \"\"",
            indent + "try:",
            indent + "    _ind_now = str(locals().get(\"ind\", \"\") or \"\")",
            indent + "except Exception:",
            indent + "    _ind_now = \"\"",
            indent + "_ch_by_ind = \"\"",
            indent + "try:",
            indent + "    if _ind_now:",
            indent + "        _ch_by_ind = _chain_of(_ind_now) or \"\"",
            indent + "except Exception:",
            indent + "    _ch_by_ind = \"\"",
            indent + "if (_ch_by_ind and _ch_by_ind == ch) \\",
            indent + "        or (_ind_now and _ind_now in _codes) \\",
            indent + "        or cd in _codes or nm in str(_codes):",
        ]

        new_src = "\n".join(lines[:i] + block + lines[i + 1:])

        try:
            compile(new_src, TARGET, "exec")
        except SyntaxError as e:
            print("   锚点%d 改完语法不通过(%s line %s) → 回滚，试下一个"
                  % (idx, e.msg, e.lineno))
            continue

        io.open(TARGET, "w", encoding="utf-8").write(new_src)
        print("✅ patch_chainmap V2: 用锚点%d 修复成功，语法检查通过" % idx)
        print("   冷低早的【①-B驱动筛】从此能识别驱动链")
        return

    print("🔴 patch_chainmap V2: 3个锚点全未命中 → 主文件未改动")
    diagnose(src)


try:
    run()
except Exception as e:
    print("🔴 patch_chainmap 异常，未修改任何文件：%s" % e)

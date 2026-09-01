# -*- coding: utf-8 -*-
"""
patch_chainmap.py  ——  放仓库【根目录】

★问题（2026-09-01 实测）★
   冷低早筛出10只，9只显示「行业[未知]」「CHAIN_MAP里没有它」，
   全部被标成"驱动待确认，不许重仓" → 筛出来也用不了，模块空转。

★根因（探针已确认）★
   CHAIN_MAP = {"存储涨价链": ["半导体","元件","电子化学品"], ...}
                                  ↑ 值是【行业名】
   而代码里写的是：
       _codes = (globals().get("CHAIN_MAP") or {}).get(ch) or []
       if cd in _codes or nm in str(_codes):
                ↑ 拿【股票代码】和【股票名】去和一堆【行业名】比对
   ★永远匹配不上。这是类型错配，不是数据缺失。★

★这个补丁怎么做到"一次修完"★
   它不依赖我事先知道缩进 —— 它自己读源码：
     ① 定位 "if cd in _codes or nm in str(_codes):" 这一行
     ② ★读出这一行真实的前导空格★
     ③ 用同样的缩进生成替换代码
   所以不需要先跑探针再改，一次跑完。

★改成什么★
   改用同一份代码里已经存在的 _chain_of(行业名) 做反向匹配：
     该股所属行业 → 查出它属于哪条驱动链 → 与当前链 ch 比对
   同时保留原来的名称匹配作为兜底，只增不减。

★安全性★
   · 幂等：装过就跳过
   · 锚点不唯一 / 找不到 / 找不到 _chain_of 定义 → 整个放弃，一个字不改
   · 改完做 compile() 语法自检，★编译不过就自动回滚★
   · 耗时 <1 秒
"""

import io
import os

TARGET = "scanner_cloud.py"
ANCHOR = "if cd in _codes or nm in str(_codes):"
MARK = "# [patch_chainmap]"


def run():
    if not os.path.exists(TARGET):
        print("🔴 patch_chainmap: 找不到 %s → 未修改" % TARGET)
        return

    src = io.open(TARGET, encoding="utf-8").read()

    if MARK in src:
        print("✅ patch_chainmap: 已安装过，跳过（幂等，正常现象）")
        return

    if "_chain_of" not in src:
        print("🔴 patch_chainmap: 源码中找不到 _chain_of 定义 → 整个放弃，未修改")
        return

    lines = src.split("\n")
    hits = [i for i, ln in enumerate(lines) if ANCHOR in ln]

    if len(hits) != 1:
        print("🔴 patch_chainmap: 锚点出现 %d 次（需要正好1次）→ 整个放弃，未修改"
              % len(hits))
        print("   锚点：%s" % ANCHOR)
        return

    i = hits[0]
    raw = lines[i]

    # ★关键：读出这一行真实的前导空白，不靠猜★
    indent = raw[:len(raw) - len(raw.lstrip())]
    print("   已定位第 %d 行，实际缩进 %d 个空格" % (i + 1, len(indent)))

    new_block = [
        indent + MARK + " 行业→驱动链 反向匹配，替代原来的代码/名称比对",
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

    out = lines[:i] + new_block + lines[i + 1:]
    new_src = "\n".join(out)

    # ★语法自检：编译不过就不写，等于自动回滚★
    try:
        compile(new_src, TARGET, "exec")
    except SyntaxError as e:
        print("🔴 patch_chainmap: 改完语法检查不通过 → ★已自动回滚，原文件未动★")
        print("   %s (line %s)" % (e.msg, e.lineno))
        return

    io.open(TARGET, "w", encoding="utf-8").write(new_src)
    print("✅ patch_chainmap: 已修复 —— 冷低早改用【行业→驱动链】反向匹配")
    print("   语法检查通过，原逻辑保留为兜底（只增不减）")


try:
    run()
except Exception as e:
    print("🔴 patch_chainmap 异常，已跳过，未修改任何文件：%s" % e)

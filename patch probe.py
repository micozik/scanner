# -*- coding: utf-8 -*-
"""
patch_probe2.py  ——  放在仓库【根目录】，和 scanner_cloud.py 同一层
★请把上一版 patch_probe.py 删掉，只留这一个★

★与上一版的区别★
   上一版只把结果打进 Actions 日志 —— 那个日志要登录才能看，我抓不到。
   这一版【把结果写成文件】：reports/probe_最新.txt + reports/probe_日期.txt
   scan.yml 的提交步骤会自动把 reports/ 推上去，我就能直接抓。

★这个文件仍然【不修改任何代码】，全程只读★

★用完请删除★
"""

import io
import os
import datetime

TARGET = "scanner_cloud.py"
OUTDIR = "reports"

PROBES = [
    ("已过及格线",          "【BUG二】铁律S的10%门槛，香农8.89%被判成已过10%"),
    ("当前最优",            "【BUG一】公告源挑选逻辑，按条数挑→挑中无代码的源"),
    ("无代码(定位不到个股)",  "【BUG一】标记无代码源的地方"),
    ("龙虎榜·东财失败",      "【BUG三】主扫描器龙虎榜取数，三源全挂"),
    ("CHAIN_MAP",           "【BUG四】驱动链映射表，冷低早6只查不到"),
]

BEFORE = 12
AFTER = 30


def run():
    buf = []

    def w(s=""):
        buf.append(s)
        print(s)

    if not os.path.exists(TARGET):
        w("🔴 patch_probe2: 找不到 %s" % TARGET)
    else:
        lines = io.open(TARGET, encoding="utf-8").read().split("\n")
        bj = datetime.datetime.utcnow() + datetime.timedelta(hours=8)

        w("=" * 70)
        w("🔬 代码探针 patch_probe2 | 北京 %s" % bj.strftime("%Y-%m-%d %H:%M"))
        w("   目标：%s 共 %d 行" % (TARGET, len(lines)))
        w("=" * 70)

        for kw, why in PROBES:
            hits = [i for i, ln in enumerate(lines) if kw in ln]
            w("")
            w("-" * 70)
            w("🔎 关键词：%s" % kw)
            w("   用途：%s" % why)
            w("   命中 %d 处" % len(hits))
            w("-" * 70)

            if not hits:
                w("   （未找到）")
                continue

            for h in hits[:2]:
                lo = max(0, h - BEFORE)
                hi = min(len(lines), h + AFTER)
                w("")
                w("   ===== 第 %d 行附近 =====" % (h + 1))
                for i in range(lo, hi):
                    mark = ">>>" if i == h else "   "
                    w("   %s %5d | %s" % (mark, i + 1, lines[i]))

            if len(hits) > 2:
                w("")
                w("   （还有 %d 处，行号：%s）"
                  % (len(hits) - 2, [x + 1 for x in hits[2:]]))

        w("")
        w("=" * 70)
        w("🔬 探针结束")
        w("=" * 70)

    # ── 写文件（关键：让报告能被抓到）──
    try:
        if not os.path.isdir(OUTDIR):
            os.makedirs(OUTDIR)
        bj = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
        text = "\n".join(buf)
        p1 = os.path.join(OUTDIR, "probe_最新.txt")
        p2 = os.path.join(OUTDIR, "probe_%s.txt" % bj.strftime("%Y%m%d"))
        io.open(p1, "w", encoding="utf-8").write(text)
        io.open(p2, "w", encoding="utf-8").write(text)
        print("✅ patch_probe2: 已写出 %s 和 %s" % (p1, p2))
    except Exception as e:
        print("🔴 patch_probe2: 写文件失败 %s" % e)


run()

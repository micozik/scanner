# -*- coding: utf-8 -*-
"""
patch_probe3.py  ——  放仓库【根目录】
★请删掉 patch_probe.py 和 patch_probe2.py，只留这一个★

上一轮探针有三个关键词没打中，这一轮换词再探。
仍然【只读，不改任何代码】，结果写进 reports/probe3_日期.txt
"""

import io
import os
import datetime

TARGET = "scanner_cloud.py"
OUTDIR = "reports"

PROBES = [
    ("回撤提示",      "【BUG二·真正的那段】报告里佰维显示的『回撤提示·先走五问』出自哪"),
    ("【达标】",       "【BUG二】代码里还留着『+10%减半锁利』，而铁律R说这条已删除"),
    ("CHAIN_MAP =",   "【BUG四】CHAIN_MAP 到底有没有被定义？如果没有，全部票都会显示『未识别』"),
    ("龙虎榜",         "【BUG三】主扫描器的龙虎榜取数在哪（上一轮关键词打偏了）"),
]

BEFORE = 10
AFTER = 26


def run():
    buf = []

    def w(s=""):
        buf.append(s)
        print(s)

    if not os.path.exists(TARGET):
        w("🔴 patch_probe3: 找不到 %s" % TARGET)
    else:
        lines = io.open(TARGET, encoding="utf-8").read().split("\n")
        bj = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
        w("=" * 70)
        w("🔬 代码探针3 | 北京 %s | %s 共 %d 行"
          % (bj.strftime("%Y-%m-%d %H:%M"), TARGET, len(lines)))
        w("=" * 70)

        for kw, why in PROBES:
            hits = [i for i, ln in enumerate(lines) if kw in ln]
            w("")
            w("-" * 70)
            w("🔎 关键词：%s   （命中 %d 处）" % (kw, len(hits)))
            w("   用途：%s" % why)
            w("-" * 70)

            if not hits:
                w("   （未找到）")
                continue

            # 龙虎榜命中会很多，只打印前3处；其余只给行号
            cap = 3 if kw == "龙虎榜" else 2
            for h in hits[:cap]:
                lo = max(0, h - BEFORE)
                hi = min(len(lines), h + AFTER)
                w("")
                w("   ===== 第 %d 行附近 =====" % (h + 1))
                for i in range(lo, hi):
                    mark = ">>>" if i == h else "   "
                    w("   %s %5d | %s" % (mark, i + 1, lines[i]))

            if len(hits) > cap:
                w("")
                w("   （还有 %d 处，行号：%s）"
                  % (len(hits) - cap, [x + 1 for x in hits[cap:]]))

        w("")
        w("=" * 70)
        w("🔬 探针3 结束")
        w("=" * 70)

    try:
        if not os.path.isdir(OUTDIR):
            os.makedirs(OUTDIR)
        bj = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
        text = "\n".join(buf)
        io.open(os.path.join(OUTDIR, "probe3_%s.txt" % bj.strftime("%Y%m%d")),
                "w", encoding="utf-8").write(text)
        print("✅ patch_probe3: 已写出 reports/probe3_%s.txt" % bj.strftime("%Y%m%d"))
    except Exception as e:
        print("🔴 patch_probe3: 写文件失败 %s" % e)


run()

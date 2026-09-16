# -*- coding: utf-8 -*-
"""
patch17b_radar_intraday.py —— 只做一件事：
让【启动日雷达】在盘中也能算出今天的跳升。

★与 patch17 的区别：不再依赖 patch15 插入的代码做锚点。
  锚点改用原始代码里就存在的 `days = sorted(hist.keys())`，
  且插入位置在 patch15 的日期闸门【之前】——
  所以无论 patch15 打没打、先打后打，都能生效。

根因（scanner_cloud.py 第2764/2816行）：
    can_save = (bj.weekday() < 5) and (bj.hour >= 15)
  板块历史库【只在15点后写盘】。盘中跑时今天的数据没入库，
  雷达读到的最后一天永远是昨天 → 永远报空。
  ★铁律Q要求「跳升≥30位当天必须出手」，而这个模块
    在盘中——唯一还能出手的时段——从来没工作过★

  2026-09-16 实测：盘中抓到90个行业，半导体+4.99%资金+185.93亿、
  通信设备跳18→3名资金+171.99亿，跳升榜一条没报。

修法：不动写盘规则（盘中快照不该当收盘价存进40天库）。
  把本次抓到的板块榜【临时注入内存】，算完跳升即丢。
"""
import io
import os
import sys

MARK = "patch17b_radar_intraday"
CANDIDATES = ["scanner_cloud.py", "scanner_cloud__1_.py"]

path = None
for c in CANDIDATES:
    if os.path.exists(c):
        path = c
        break
if path is None:
    print("!! patch17b 中止：找不到 scanner_cloud.py")
    sys.exit(0)

with io.open(path, "r", encoding="utf-8") as f:
    s = f.read()

if MARK in s:
    print("OK 0: patch17b 已打过，跳过（幂等）")
    sys.exit(0)

ok = 0

# ── 步骤1：盘中也把当天板块快照留一份在内存 ──
A1 = """    def _save(store, hist, path, label):
        if not store or not can_save:
            return"""
if A1 in s:
    s = s.replace(A1, """    def _save(store, hist, path, label):
        # patch17b：盘中不写盘，但把快照留在内存给启动日雷达用
        if store:
            globals()["TODAY_BOARD_" + label] = store
        if not store or not can_save:
            return""", 1)
    ok += 1
    print("OK 1: 板块快照已暂存内存(TODAY_BOARD_行业/概念)")
else:
    print("!! 1: 锚点 _save 未命中 → patch17b 中止（没打成，不留半成品）")
    sys.exit(0)

# ── 步骤2：雷达取到 days 之后立刻补今天，位置在任何日期闸门之前 ──
A2 = """            days = sorted(hist.keys())

            def _rank(obj):"""
if A2 in s:
    s = s.replace(A2, """            days = sorted(hist.keys())
            # patch17b：库里没有今天(盘中未到写盘时点)，用本次快照临时补
            _t17 = now_beijing().strftime("%Y-%m-%d")
            if str(days[-1])[:10] != _t17:
                _m17 = globals().get("TODAY_BOARD_" + kind)
                if _m17:
                    hist = dict(hist)
                    hist[_t17] = _m17
                    days = sorted(hist.keys())
                    w(f"  ✅ {kind}：库里无今天，已用本次抓到的"
                      f"{len(_m17)}个板块临时补入，跳升按今天算")
                else:
                    w(f"  ⚠️ {kind}：内存里也没有今天的快照"
                      f"（板块榜本次是不是报空了？）")

            def _rank(obj):""", 1)
    ok += 1
    print("OK 2: 雷达已在取days后立刻接入内存快照")
else:
    print("!! 2: 锚点 days=sorted 未命中 → patch17b 中止")
    sys.exit(0)

s = s.rstrip("\n") + "\n\n# " + MARK + "：启动日雷达盘中可用\n"
with io.open(path, "w", encoding="utf-8") as f:
    f.write(s)
print("patch17b 完成，%d/2 步生效 → %s" % (ok, path))

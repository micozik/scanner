# -*- coding: utf-8 -*-
"""
patch17_radar_intraday.py —— 只做一件事：
让【启动日雷达】在盘中也能算出今天的跳升。

根因（scanner_cloud.py 第2764/2816行）：
    can_save = (bj.weekday() < 5) and (bj.hour >= 15)
  板块历史库【只在15点后写盘】。盘中跑时今天的数据没入库，
  启动日雷达读到的最后一天永远是昨天。
  patch15 正确地把它拦成[报空]，但真正的损失是：
  ★铁律Q说「跳升≥30位当天必须出手」，而这个模块
    在盘中——也就是唯一还能出手的时段——从来没工作过★

  2026-09-16 实测：盘中榜抓到90个行业成功，半导体+3.05%连3天、
  通信设备跳18→6名资金+125.9亿，但跳升榜一条没报，
  必答清单[1]列出来的全是农业/橡胶/电商这些低位补涨的杂毛。

修法：不动写盘规则（盘中快照不该当收盘价存进40天库）。
  改成把本次抓到的板块榜【临时注入内存】，算完跳升即丢。
  ★盘中= 用内存快照；盘后= 用正式入库的数据，两者不混。
"""
import io
import os
import sys

MARK = "patch17_radar_intraday"
CANDIDATES = ["scanner_cloud.py", "scanner_cloud__1_.py"]

path = None
for c in CANDIDATES:
    if os.path.exists(c):
        path = c
        break
if path is None:
    print("跳过 patch17：找不到 scanner_cloud.py")
    sys.exit(0)

with io.open(path, "r", encoding="utf-8") as f:
    s = f.read()

if MARK in s:
    print("OK 0: patch17 已打过，跳过（幂等）")
    sys.exit(0)

# ── 步骤1：盘中也把当天板块快照留一份在内存 ──
A1 = """    def _save(store, hist, path, label):
        if not store or not can_save:
            return"""
if A1 not in s:
    print("!! 1: 锚点 _save 未命中，patch17 中止")
    sys.exit(0)

N1 = """    def _save(store, hist, path, label):
        # patch17：盘中不写盘，但把快照留在内存给启动日雷达用
        if store:
            globals()["TODAY_BOARD_" + label] = store
        if not store or not can_save:
            return"""
s = s.replace(A1, N1, 1)
print("OK 1: 板块快照已暂存内存（TODAY_BOARD_行业 / TODAY_BOARD_概念）")

# ── 步骤2：雷达读不到今天时，先用内存快照补，补不上才报空 ──
A2 = """            _today = now_beijing().strftime("%Y-%m-%d")
            _last = str(days[-1])[:10]
            if _last != _today:"""
if A2 not in s:
    print("!! 2: 锚点未命中（patch15 是否已打？），patch17 中止")
    sys.exit(0)

N2 = """            _today = now_beijing().strftime("%Y-%m-%d")
            _last = str(days[-1])[:10]
            # patch17：盘中库里没有今天，用本次抓到的快照临时补
            if _last != _today:
                _mem = globals().get("TODAY_BOARD_" + kind)
                if _mem:
                    hist = dict(hist)
                    hist[_today] = _mem
                    days = sorted(hist.keys())
                    _last = _today
                    w(f"  ✅ {kind}：库里无今天(盘中未到写盘时点)，"
                      f"已用本次抓到的{len(_mem)}个板块临时补入，跳升按今天算")
            if _last != _today:"""
s = s.replace(A2, N2, 1)
print("OK 2: 雷达已接入内存快照兜底")

s = s.rstrip("\n") + "\n\n# " + MARK + "：启动日雷达盘中可用\n"
print("OK 3: 已写入幂等标记")

with io.open(path, "w", encoding="utf-8") as f:
    f.write(s)
print("patch17 完成 → %s" % path)

# -*- coding: utf-8 -*-
"""
patch_leader.py  ——  放仓库【根目录】

★为什么要这个★
   2026-08-28 亨通光电(领涨2个板块) vs 通光线缆(领涨0个) → 我选了0个的
              结果：亨通两天+8.8%，通光+3.0%后净利转亏暴雷
   2026-09-01 神农种业/绿亨科技(各领涨3个) vs 万向德农(领涨0个) → 我又选了0个的
   ★同一个错犯了两次，根因是从没统计过"谁领涨了几个板块"★

   数据一直都在（每个板块都有"领涨股"字段），只是从来没人把它们汇总。
   同一只股票在多个板块的领涨位重复出现 = 这条产业链的真龙头。

★做什么★
   扫全市场【行业板块 + 概念板块】，统计每只股票出现在"领涨"位的次数，
   按次数排序，写到 reports/龙头榜_最新.txt + 龙头榜_日期.txt
   ★这是全市场扫描，不受 我的清单.txt 限制，会带回清单外的新名字★

★安全性★
   · ★完全不修改 scanner_cloud.py★
   · 只写 reports/龙头榜_*.txt
   · 只调 2 个板块级接口（板块接口在GitHub Actions上是通的，个股接口才挂）
   · 60秒硬预算 + 全程异常捕获，最坏情况本表空白，不影响主扫描
   · 实测耗时应在 5-15 秒
"""

import io
import os
import time
import datetime
import traceback

OUTDIR = "reports"
TIME_BUDGET = 60.0
MIN_BOARD_PCT = 0.0        # 只统计上涨板块的领涨股

_T0 = time.time()


def col(df, *names):
    for n in names:
        if n in df.columns:
            return n
    return None


def grab(ak, kind):
    """返回 [(板块名, 板块涨幅, 领涨股), ...]"""
    fns = []
    if kind == "行业":
        fns = [lambda: ak.stock_board_industry_name_em()]
    else:
        fns = [lambda: ak.stock_board_concept_name_em()]

    for fn in fns:
        try:
            df = fn()
            if df is None or len(df) == 0:
                continue
            c_name = col(df, "板块名称", "name")
            c_pct = col(df, "涨跌幅", "pct_chg")
            c_lead = col(df, "领涨股票", "领涨股")
            if not (c_name and c_pct and c_lead):
                continue
            out = []
            for _, r in df.iterrows():
                try:
                    out.append((str(r[c_name]), float(r[c_pct]),
                                str(r[c_lead]).strip()))
                except Exception:
                    continue
            return out
        except Exception:
            continue
    return []


def run():
    buf = []

    def w(s=""):
        buf.append(s)

    bj = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    w("=" * 66)
    w("👑【龙头榜】谁领涨了几个板块 | 北京 %s" % bj.strftime("%Y-%m-%d %H:%M"))
    w("   领涨≥3个板块 = 这条链的真龙头，产业趋势启动期【优先买它】")
    w("   领涨0个但你看上了 = 必须先说出'资金为什么错了'，说不出就买龙头")
    w("=" * 66)

    try:
        import akshare as ak
    except Exception as e:
        w("🔴 akshare 导入失败：%s → 本表无数据" % e)
        ak = None

    rows = []
    if ak is not None:
        for kind in ("行业", "概念"):
            if time.time() - _T0 > TIME_BUDGET:
                w("⏱️ 超出时间预算，跳过【%s】板块" % kind)
                continue
            got = grab(ak, kind)
            w("   %s板块：取到 %d 个" % (kind, len(got)))
            for name, pct, lead in got:
                rows.append((kind, name, pct, lead))

    if not rows:
        w("🔴 板块接口全部失败 → 本表无数据（不编数）")
    else:
        tally = {}
        for kind, name, pct, lead in rows:
            if pct <= MIN_BOARD_PCT or not lead or lead in ("nan", "-", ""):
                continue
            d = tally.setdefault(lead, {"n": 0, "boards": []})
            d["n"] += 1
            d["boards"].append("%s%+.1f%%" % (name, pct))

        ranked = sorted(tally.items(), key=lambda kv: -kv[1]["n"])

        w("")
        w("   上涨板块共 %d 个，涉及领涨股 %d 只"
          % (len([r for r in rows if r[2] > 0]), len(ranked)))
        w("")
        w("-" * 66)
        w("👑 真龙头（领涨 ≥3 个板块）")
        w("-" * 66)
        top = [x for x in ranked if x[1]["n"] >= 3]
        if not top:
            w("   （今日无个股领涨3个以上板块 → 没有明确主线龙头）")
        for name, d in top[:12]:
            w("  ★ %s —— 领涨 %d 个板块" % (name, d["n"]))
            w("     %s" % " ｜ ".join(d["boards"][:8]))

        w("")
        w("-" * 66)
        w("🥈 次龙头（领涨 2 个板块）")
        w("-" * 66)
        sec = [x for x in ranked if x[1]["n"] == 2]
        if not sec:
            w("   （无）")
        for name, d in sec[:15]:
            w("  · %s —— %s" % (name, " ｜ ".join(d["boards"][:4])))

        w("")
        w("-" * 66)
        w("📈 今日涨幅前20板块及其领涨股")
        w("-" * 66)
        for kind, name, pct, lead in sorted(
                rows, key=lambda r: -r[2])[:20]:
            star = ""
            if lead in tally:
                star = " 👑x%d" % tally[lead]["n"]
            w("  %s %-14s %+6.2f%%  领涨:%s%s" % (kind, name, pct, lead, star))

    w("")
    w("=" * 66)
    w("⚠️ 用法（写死，AI每次决断必须引用）：")
    w("   ① 同一条链里，默认买【领涨板块数最多】的那只")
    w("   ② 要买领涨0个的，必须先答出'资金为什么错了'，答不出就买龙头")
    w("   ③ ★配合位置表用★：龙头 + 距60日高点<-3% = 最佳；")
    w("      龙头 + 距高点0% + 放量3倍 = 高潮区，等回调")
    w("   ④ 无人领涨3个以上板块 → 今日无主线，宁可报空")
    w("   耗时 %.1f 秒" % (time.time() - _T0))
    w("=" * 66)

    text = "\n".join(buf)
    print(text)
    try:
        if not os.path.isdir(OUTDIR):
            os.makedirs(OUTDIR)
        io.open(os.path.join(OUTDIR, "龙头榜_最新.txt"),
                "w", encoding="utf-8").write(text)
        io.open(os.path.join(OUTDIR, "龙头榜_%s.txt" % bj.strftime("%Y%m%d")),
                "w", encoding="utf-8").write(text)
        print("✅ patch_leader: 已写出，耗时 %.1f 秒" % (time.time() - _T0))
    except Exception as e:
        print("🔴 patch_leader: 写文件失败 %s" % e)


try:
    run()
except Exception:
    print("🔴 patch_leader 整体异常，已跳过，不影响主扫描：")
    traceback.print_exc()

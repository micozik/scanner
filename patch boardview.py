# -*- coding: utf-8 -*-
"""
patch_boardview.py  ——  放仓库【根目录】
★请删掉 patch_leader.py 和 patch_boardcons.py，用这一个替代★

★上一版为什么失败（2026-09-01 16:11 实测）★
   板块列表-行业 → Connection aborted / RemoteDisconnected
   板块列表-概念 → 502 Bad Gateway  https://push2.eastmoney.com/api/qt/clist/
   ★不是代码写错，是东财 push2 接口把IP掐了。★
   而主扫描器能拿到477个板块，是因为它【多源自动切换】，
   我上一版只用东财一个源，东财一挂就全废。

★这一版的改法★
   ① ★新浪源优先★（stock_sector_spot）—— 和东财是完全不同的服务器
      而且新浪这个接口自带"领涨股"字段，一次调用同时喂两张表
   ② 东财作为兜底，且带 3 次重试 + 递增退避（502 多为瞬时）
   ③ 一个文件同时产出两张表，减少重复请求：
        reports/龙头榜_最新.txt      谁领涨了几个板块
        reports/板块成分_最新.txt    最强板块里谁还没涨
   ④ ★任何一步失败，都把真实报错原文写进报告★，不写"失败了"三个字了事

★安全性★
   · ★完全不修改 scanner_cloud.py★
   · 只写 reports/龙头榜_*.txt 和 reports/板块成分_*.txt
   · 100秒硬预算 + 全程异常捕获，最坏情况两张表空白，主扫描不受影响
"""

import io
import os
import time
import datetime
import traceback
from concurrent.futures import ThreadPoolExecutor

OUTDIR = "reports"
TIME_BUDGET = 100.0
TOP_N = 10
MAX_CONS = 25
WORKERS = 4

_T0 = time.time()
_LOG = []


def over():
    return (time.time() - _T0) > TIME_BUDGET


def note(s):
    _LOG.append(s)


def col(df, *names):
    for n in names:
        if n in df.columns:
            return n
    return None


def retry(fn, tries=3, base=1.5, tag=""):
    last = ""
    for i in range(tries):
        if over():
            note("%s：超时预算，放弃" % tag)
            return None
        try:
            r = fn()
            if r is not None and len(r) > 0:
                return r
            last = "返回空"
        except Exception as e:
            last = str(e)[:90]
        time.sleep(base * (i + 1))
    note("%s：%d次全失败 → %s" % (tag, tries, last))
    return None


# ────────────── 板块列表：新浪优先，东财兜底 ──────────────
def boards_sina(ak):
    df = retry(lambda: ak.stock_sector_spot(indicator="行业"),
               tag="新浪行业(行业)")
    if df is None:
        df = retry(lambda: ak.stock_sector_spot(indicator="新浪行业"),
                   tag="新浪行业(新浪行业)")
    if df is None:
        return []
    c_lab = col(df, "label")
    c_name = col(df, "板块", "板块名称", "name")
    c_pct = col(df, "涨跌幅", "pct_chg")
    c_lead = col(df, "个股-名称", "名称", "领涨股票", "领涨股")
    if not (c_name and c_pct):
        note("新浪：列名不匹配 → %s" % list(df.columns)[:10])
        return []
    out = []
    for _, r in df.iterrows():
        try:
            out.append(("新浪行业", str(r[c_name]),
                        str(r[c_lab]) if c_lab else "",
                        float(r[c_pct]),
                        str(r[c_lead]).strip() if c_lead else ""))
        except Exception:
            continue
    note("新浪：取到 %d 个板块" % len(out))
    return out


def boards_em(ak):
    out = []
    for kind, fn in (("行业", lambda: ak.stock_board_industry_name_em()),
                     ("概念", lambda: ak.stock_board_concept_name_em())):
        df = retry(fn, tag="东财%s" % kind)
        if df is None:
            continue
        c_n = col(df, "板块名称", "name")
        c_c = col(df, "板块代码", "code")
        c_p = col(df, "涨跌幅", "pct_chg")
        c_l = col(df, "领涨股票", "领涨股")
        if not (c_n and c_p):
            continue
        for _, r in df.iterrows():
            try:
                out.append((kind, str(r[c_n]),
                            str(r[c_c]) if c_c else "",
                            float(r[c_p]),
                            str(r[c_l]).strip() if c_l else ""))
            except Exception:
                continue
    note("东财：取到 %d 个板块" % len(out))
    return out


# ────────────── 成分股：多源 ──────────────
def cons_of(ak, kind, name, code):
    tries = []
    if code:
        tries.append(("新浪明细",
                      lambda: ak.stock_sector_detail(sector=code)))
    if kind == "概念":
        tries.append(("东财概念cons",
                      lambda: ak.stock_board_concept_cons_em(symbol=name)))
    else:
        tries.append(("东财行业cons",
                      lambda: ak.stock_board_industry_cons_em(symbol=name)))

    for src, fn in tries:
        if over():
            return None
        try:
            df = fn()
            if df is None or len(df) == 0:
                continue
            c_n = col(df, "名称", "股票简称", "name")
            c_c = col(df, "代码", "股票代码", "symbol", "code")
            c_p = col(df, "涨跌幅", "changepercent", "pct_chg")
            if not c_n:
                continue
            rows = []
            for _, r in df.iterrows():
                try:
                    p = float(r[c_p]) if c_p else None
                except Exception:
                    p = None
                rows.append((str(r[c_n]), str(r[c_c]) if c_c else "", p))
            if rows:
                return (src, rows)
        except Exception as e:
            note("%s|%s → %s" % (name, src, str(e)[:60]))
    return None


def run():
    bj = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    ts = bj.strftime("%Y-%m-%d %H:%M")

    try:
        import akshare as ak
    except Exception as e:
        note("akshare 导入失败：%s" % e)
        ak = None

    boards = []
    if ak is not None:
        boards = boards_sina(ak)
        if not boards:
            note("新浪无结果 → 切换东财兜底")
            boards = boards_em(ak)

    # ───────── 表一：龙头榜 ─────────
    L = []
    L.append("=" * 66)
    L.append("👑【龙头榜】谁领涨了几个板块 | 北京 %s" % ts)
    L.append("   领涨≥3个板块 = 这条链的真龙头，趋势启动期【优先买它】")
    L.append("=" * 66)

    if not boards:
        L.append("🔴 板块列表取数失败，本表无数据（不编数）。过程日志：")
        for s in _LOG:
            L.append("   · %s" % s)
    else:
        tally = {}
        for kind, name, code, pct, lead in boards:
            if pct <= 0 or not lead or lead in ("nan", "-", ""):
                continue
            d = tally.setdefault(lead, {"n": 0, "b": []})
            d["n"] += 1
            d["b"].append("%s%+.1f%%" % (name, pct))
        ranked = sorted(tally.items(), key=lambda kv: -kv[1]["n"])
        up = len([b for b in boards if b[3] > 0])
        L.append("   板块 %d 个，其中上涨 %d 个，涉及领涨股 %d 只"
                 % (len(boards), up, len(ranked)))
        L.append("")
        L.append("-" * 66)
        L.append("👑 真龙头（领涨 ≥3 个板块）")
        L.append("-" * 66)
        top = [x for x in ranked if x[1]["n"] >= 3]
        if not top:
            L.append("   （今日无个股领涨3个以上板块 → 无明确主线龙头）")
        for nm, d in top[:12]:
            L.append("  ★ %s —— 领涨 %d 个板块" % (nm, d["n"]))
            L.append("     %s" % " ｜ ".join(d["b"][:8]))
        L.append("")
        L.append("-" * 66)
        L.append("🥈 次龙头（领涨 2 个板块）")
        L.append("-" * 66)
        sec = [x for x in ranked if x[1]["n"] == 2]
        if not sec:
            L.append("   （无）")
        for nm, d in sec[:15]:
            L.append("  · %s —— %s" % (nm, " ｜ ".join(d["b"][:4])))
        L.append("")
        L.append("-" * 66)
        L.append("📈 涨幅前20板块及领涨股")
        L.append("-" * 66)
        for kind, name, code, pct, lead in sorted(
                boards, key=lambda b: -b[3])[:20]:
            star = " 👑x%d" % tally[lead]["n"] if lead in tally else ""
            L.append("  %-8s %+6.2f%%  领涨:%s%s" % (name[:12], pct, lead, star))
    L.append("")
    L.append("⚠️ 用法：同链默认买领涨板块数最多的；要买领涨0个的，"
             "必须先答出'资金为什么错了'")
    L.append("   耗时 %.1f 秒" % (time.time() - _T0))
    L.append("=" * 66)

    # ───────── 表二：板块成分 ─────────
    C = []
    C.append("=" * 68)
    C.append("🧩【板块成分·谁还没涨】| 北京 %s" % ts)
    C.append("   只取涨幅TOP%d板块，成分按涨幅【从小到大】排" % TOP_N)
    C.append("=" * 68)

    picked = sorted(boards, key=lambda b: -b[3])[:TOP_N] if boards else []
    results = []
    if picked:
        def job(b):
            kind, name, code, pct, lead = b
            return (name, pct, cons_of(ak, kind, name, code))
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            results = list(ex.map(job, picked))

    ok = len([r for r in results if r[2]])
    C.append("   成分取数成功 %d / %d 个板块" % (ok, len(picked)))
    C.append("")
    if ok == 0:
        C.append("🔴 成分股全部失败，本表无数据（不编数）。过程日志：")
        for s in _LOG[-14:]:
            C.append("   · %s" % s)
    else:
        for name, pct, got in results:
            C.append("-" * 68)
            if not got:
                C.append("【%s】%+.2f%%  🔴成分取数失败" % (name, pct))
                continue
            src, rows = got
            r2 = [r for r in rows if r[2] is not None]
            r2.sort(key=lambda r: r[2])
            C.append("【%s】板块%+.2f%%  成分%d只  源:%s"
                     % (name, pct, len(rows), src))
            if not r2:
                C.append("   " + "、".join([r[0] for r in rows[:MAX_CONS]]))
                continue
            cold = [r for r in r2 if r[2] < 3.0]
            C.append("   ★板块在涨，这些还没涨(<3%%)：%d只★" % len(cold))
            for nm, cd, p in cold[:MAX_CONS]:
                flag = "🟢没涨" if p < 1.0 else "🟡微涨"
                C.append("     %s %-8s %-8s %+6.2f%%" % (flag, nm, cd, p))
            hot = [r for r in r2 if r[2] >= 9.0]
            if hot:
                C.append("   （已涨停 %d只：%s）"
                         % (len(hot), "、".join([h[0] for h in hot[:10]])))
    C.append("")
    C.append("⚠️ 用法：板块涨+该股没涨 = 首选；★必须配位置表★"
             "（没涨+距60日高点<-10%+缩量=最佳）；再配龙头榜")
    C.append("   耗时 %.1f 秒" % (time.time() - _T0))
    C.append("=" * 68)

    # ───────── 落盘 ─────────
    try:
        if not os.path.isdir(OUTDIR):
            os.makedirs(OUTDIR)
        d = bj.strftime("%Y%m%d")
        for fname, body in (("龙头榜", L), ("板块成分", C)):
            t = "\n".join(body)
            io.open(os.path.join(OUTDIR, "%s_最新.txt" % fname),
                    "w", encoding="utf-8").write(t)
            io.open(os.path.join(OUTDIR, "%s_%s.txt" % (fname, d)),
                    "w", encoding="utf-8").write(t)
        print("✅ patch_boardview: 两张表已写出，耗时 %.1f 秒"
              % (time.time() - _T0))
    except Exception as e:
        print("🔴 patch_boardview: 写文件失败 %s" % e)

    for s in _LOG:
        print("   [log] %s" % s)


try:
    run()
except Exception:
    print("🔴 patch_boardview 整体异常，已跳过，不影响主扫描：")
    traceback.print_exc()

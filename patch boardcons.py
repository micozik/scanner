# -*- coding: utf-8 -*-
"""
patch_boardcons.py  ——  放仓库【根目录】

★问题（2026-09-01 实测）★
   主扫描器报告写着：「成分股接口失败且无缓存 → 降级全市场筛选」
   后果：【每日选股】六关里第④⑤关废掉，天天输出"过④⑤关后无标的"。

★我的判断：不是接口被封，是调用量太大★
   主扫描器有 477 个板块。如果挨个取成分股 = 477 次请求 → 限流/超时 → 全挂。
   ★但选股根本不需要477个，只需要今天最强的十几个。★

★这个补丁做什么★
   ① 取板块列表（这个接口是通的，主报告每天都在用）
   ② ★只挑涨幅最高的 TOP_N 个板块★（默认12个，请求量从477降到12）
   ③ 取这些板块的成分股 + 每只成分股的当日涨跌幅
   ④ ★按涨幅【从小到大】排序输出★
       —— 直接回答那个最值钱的问题：这条链在爆发，谁还没涨？
   写到 reports/板块成分_最新.txt + 板块成分_日期.txt

★四个数据源自动切换，跑一次就知道哪个能用★
   东财行业cons / 东财概念cons / 同花顺cons / 新浪板块明细
   全失败就明确写出每个源的报错，不编数。

★安全性★
   · ★完全不修改 scanner_cloud.py★
   · 只写 reports/板块成分_*.txt
   · 90秒硬预算 + 4线程并发 + 全程异常捕获
   · 最坏情况本表空白，主扫描不受影响
"""

import io
import os
import time
import datetime
import traceback
from concurrent.futures import ThreadPoolExecutor

OUTDIR = "reports"
TIME_BUDGET = 90.0
TOP_N = 12          # 只取涨幅最高的12个板块，而不是477个
MAX_CONS = 30       # 每个板块最多列30只
WORKERS = 4

_T0 = time.time()
_ERRS = {}


def over():
    return (time.time() - _T0) > TIME_BUDGET


def col(df, *names):
    for n in names:
        if n in df.columns:
            return n
    return None


def board_list(ak):
    """返回 [(类型, 板块名, 板块代码, 涨幅), ...]"""
    out = []
    for kind, fn in (("行业", lambda: ak.stock_board_industry_name_em()),
                     ("概念", lambda: ak.stock_board_concept_name_em())):
        try:
            df = fn()
            c_n = col(df, "板块名称", "name")
            c_c = col(df, "板块代码", "code")
            c_p = col(df, "涨跌幅", "pct_chg")
            if not (c_n and c_p):
                continue
            for _, r in df.iterrows():
                try:
                    out.append((kind, str(r[c_n]),
                                str(r[c_c]) if c_c else "",
                                float(r[c_p])))
                except Exception:
                    continue
        except Exception as e:
            _ERRS["板块列表-" + kind] = str(e)[:80]
    return out


def get_cons(ak, kind, name, code):
    """四源依次试，返回 [(名称, 代码, 涨跌幅), ...] 或 None"""
    tries = []
    if kind == "行业":
        tries.append(("东财行业cons",
                      lambda: ak.stock_board_industry_cons_em(symbol=name)))
    else:
        tries.append(("东财概念cons",
                      lambda: ak.stock_board_concept_cons_em(symbol=name)))
    tries.append(("东财另一类cons",
                  lambda: (ak.stock_board_concept_cons_em(symbol=name)
                           if kind == "行业"
                           else ak.stock_board_industry_cons_em(symbol=name))))
    if code:
        tries.append(("同花顺cons",
                      lambda: ak.stock_board_cons_ths(symbol=code)))
    tries.append(("新浪板块明细",
                  lambda: ak.stock_sector_detail(sector=code or name)))

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
                    pct = float(r[c_p]) if c_p else None
                except Exception:
                    pct = None
                rows.append((str(r[c_n]),
                             str(r[c_c]) if c_c else "",
                             pct))
            if rows:
                return (src, rows)
        except Exception as e:
            _ERRS["%s|%s" % (name, src)] = str(e)[:60]
            continue
    return None


def run():
    buf = []

    def w(s=""):
        buf.append(s)

    bj = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    w("=" * 68)
    w("🧩【板块成分·谁还没涨】| 北京 %s" % bj.strftime("%Y-%m-%d %H:%M"))
    w("   只取今日涨幅TOP%d的板块（不是477个），成分按涨幅【从小到大】排" % TOP_N)
    w("   ★用途：这条链在爆发，找出还没涨的那只 —— 铁律N的直接数据源★")
    w("=" * 68)

    try:
        import akshare as ak
    except Exception as e:
        w("🔴 akshare 导入失败：%s" % e)
        ak = None

    boards = []
    if ak is not None:
        allb = board_list(ak)
        w("   板块列表取到 %d 个" % len(allb))
        boards = sorted(allb, key=lambda x: -x[3])[:TOP_N]

    results = []
    if boards:
        def job(b):
            kind, name, code, pct = b
            got = get_cons(ak, kind, name, code)
            return (kind, name, pct, got)
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            results = list(ex.map(job, boards))

    ok = len([r for r in results if r[3]])
    w("   成分股取数成功 %d / %d 个板块 | 耗时 %.1f 秒"
      % (ok, len(boards), time.time() - _T0))
    w("")

    if ok == 0:
        w("🔴 四个数据源全部失败，本表无数据（不编数）。各源报错：")
        for k, v in list(_ERRS.items())[:12]:
            w("   · %s → %s" % (k, v))
    else:
        for kind, name, pct, got in results:
            w("-" * 68)
            if not got:
                w("【%s·%s】%+.2f%%  🔴成分股取数失败" % (kind, name, pct))
                continue
            src, rows = got
            rows2 = [r for r in rows if r[2] is not None]
            rows2.sort(key=lambda r: r[2])
            w("【%s·%s】板块%+.2f%%  成分%d只  源:%s"
              % (kind, name, pct, len(rows), src))
            if not rows2:
                w("   （成分股无涨跌幅字段，只列名称）")
                w("   " + "、".join([r[0] for r in rows[:MAX_CONS]]))
                continue

            cold = [r for r in rows2 if r[2] < 3.0]
            w("   ★板块在涨，但这些还没涨（<3%%）：%d只★" % len(cold))
            for nm, cd, p in cold[:MAX_CONS]:
                flag = "🟢没涨" if p < 1.0 else "🟡微涨"
                w("     %s %-8s %-8s %+6.2f%%" % (flag, nm, cd, p))
            hot = [r for r in rows2 if r[2] >= 9.0]
            if hot:
                w("   （已涨停/接近涨停 %d只：%s）"
                  % (len(hot), "、".join([h[0] for h in hot[:10]])))
        w("")

    w("=" * 68)
    w("⚠️ 用法（AI每次决断必须引用）：")
    w("   ① 板块涨 + 该股没涨(<3%) = 铁律N首选")
    w("   ② ★必须配合位置表★：没涨 + 距60日高点<-10% + 缩量 = 最佳")
    w("      没涨但距高点0% = 它只是不动，不是没启动")
    w("   ③ ★必须配合龙头榜★：同链优先买领涨板块数多的")
    w("   ④ 没涨的原因可能是【基本面差】，推荐前必须答出①-B")
    w("   耗时 %.1f 秒" % (time.time() - _T0))
    w("=" * 68)

    text = "\n".join(buf)
    print(text)
    try:
        if not os.path.isdir(OUTDIR):
            os.makedirs(OUTDIR)
        io.open(os.path.join(OUTDIR, "板块成分_最新.txt"),
                "w", encoding="utf-8").write(text)
        io.open(os.path.join(OUTDIR, "板块成分_%s.txt" % bj.strftime("%Y%m%d")),
                "w", encoding="utf-8").write(text)
        print("✅ patch_boardcons: 已写出，耗时 %.1f 秒" % (time.time() - _T0))
    except Exception as e:
        print("🔴 patch_boardcons: 写文件失败 %s" % e)


try:
    run()
except Exception:
    print("🔴 patch_boardcons 整体异常，已跳过，不影响主扫描：")
    traceback.print_exc()

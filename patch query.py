# -*- coding: utf-8 -*-
"""
patch_query.py  ——  放仓库【根目录】，和 scanner_cloud.py 同一层

╔══════════════════════════════════════════════════════════╗
║  这是什么：一个【点单窗口】                                ║
║  你在仓库根目录建一个  查询.txt ，一行写一个：             ║
║      股票代码  /  股票名称  /  板块名称                    ║
║  跑一次扫描，它就把这些标的的全部可得数据写成报告：         ║
║      reports/查询结果_最新.txt  +  查询结果_日期.txt        ║
╚══════════════════════════════════════════════════════════╝

★为什么要它★
  2026-09-02 我连续两次在数据不足时就给了推荐：
    · 博云新材 —— 我以为"硬质合金=高温合金"，实际它78%收入是碳化钨基，
      跟燃气轮机叶片毫无关系，涨停原因是美伊冲突避险
    · 中航沈飞 —— 我不知道它H1净利-58.37%、市盈47.77倍、
      主力资金从20日7.5亿降到3日1.1亿（在减速不是加速）
  两次都靠用户截图当场推翻。
  ★根因：AI没有行情接口，清单外的票完全是瞎的。★

★能拿到什么（海外IP实测可行）★
  ✅ 现价 / 今日涨跌 / 成交额 / 换手 / 市盈（全市场快照）
  ✅ 60日涨跌 / 距60日高低点 / 连板天数 / 缩量倍数（K线自算）
  ✅ 板块成分股 + 每只涨跌，★按涨幅从小到大排★（找"谁还没涨"）
  🟡 主营构成 / 个股资金流 —— 会尝试，海外IP大概率失败
     失败就写【无数据】，★绝不编数★，那两项仍需截图

★安全性★
  · ★完全不修改 scanner_cloud.py / scanner_usa.py，一行都不碰★
  · 只读 查询.txt，只写 reports/查询结果_*.txt
  · 150秒硬预算 + 8线程并发 + 全程异常捕获
  · 查询.txt 不存在就跳过并打印用法，不报错
"""

import io
import os
import time
import datetime
import traceback
from concurrent.futures import ThreadPoolExecutor

QUERY_FILE = "查询.txt"
OUTDIR = "reports"
TIME_BUDGET = 150.0
MAX_ITEMS = 20
WORKERS = 8

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


def board_limit(code):
    if code.startswith("30") or code.startswith("68"):
        return 19.8
    if code[:2] in ("92", "83", "87"):
        return 29.5
    return 9.8


def load_snapshot(ak):
    """全市场快照：名称↔代码 + 现价。新浪优先，东财兜底"""
    for tag, fn in (("新浪", lambda: ak.stock_zh_a_spot()),
                    ("东财", lambda: ak.stock_zh_a_spot_em())):
        try:
            df = fn()
            if df is None or len(df) < 100:
                continue
            c_code = col(df, "代码", "symbol", "code")
            c_name = col(df, "名称", "name")
            c_price = col(df, "最新价", "trade", "现价")
            c_pct = col(df, "涨跌幅", "changepercent", "pct_chg")
            c_amt = col(df, "成交额", "amount")
            c_turn = col(df, "换手率", "turnoverratio")
            c_pe = col(df, "市盈率-动态", "per", "市盈率")
            if not (c_code and c_name):
                continue
            m = {}
            for _, r in df.iterrows():
                try:
                    digits = "".join([c for c in str(r[c_code]) if c.isdigit()])
                    code = digits[-6:]
                    if len(code) != 6:
                        continue
                    m[code] = {
                        "name": str(r[c_name]).strip(),
                        "price": _num(r, c_price),
                        "pct": _num(r, c_pct),
                        "amt": _num(r, c_amt),
                        "turn": _num(r, c_turn),
                        "pe": _num(r, c_pe),
                    }
                except Exception:
                    continue
            note("快照源[%s] 成功：%d 只" % (tag, len(m)))
            return m
        except Exception as e:
            note("快照源[%s] 失败：%s" % (tag, str(e)[:60]))
    return {}


def _num(r, c):
    if not c:
        return None
    try:
        return float(r[c])
    except Exception:
        return None


def kline_info(ak, code):
    if over():
        return None, "超时预算用尽"
    end = datetime.datetime.now().strftime("%Y%m%d")
    start = (datetime.datetime.now()
             - datetime.timedelta(days=95)).strftime("%Y%m%d")
    df = None
    err = ""
    for fn in (
        lambda: ak.stock_zh_a_hist(symbol=code, period="daily",
                                   start_date=start, end_date=end,
                                   adjust="qfq"),
        lambda: ak.stock_zh_a_hist(symbol=code, period="daily",
                                   start_date=start, end_date=end),
    ):
        try:
            d = fn()
            if d is not None and len(d) > 5:
                df = d
                break
        except Exception as e:
            err = str(e)[:50]
    if df is None:
        return None, err or "K线取数失败"
    try:
        c_close = col(df, "收盘", "close")
        c_pct = col(df, "涨跌幅", "pct_chg")
        c_vol = col(df, "成交量", "volume")
        closes = [float(x) for x in list(df[c_close])[-60:]]
        last = closes[-1]
        o = {"last": last, "d60": (last / closes[0] - 1) * 100,
             "hi": max(closes), "lo": min(closes),
             "streak": None, "volr": None}
        o["from_hi"] = (last / o["hi"] - 1) * 100
        o["from_lo"] = (last / o["lo"] - 1) * 100
        if c_pct is not None:
            pcts = [float(x) for x in list(df[c_pct])]
            lim = board_limit(code)
            n = 0
            for v in reversed(pcts):
                if v >= lim:
                    n += 1
                else:
                    break
            o["streak"] = n
        if c_vol is not None:
            vols = [float(x) for x in list(df[c_vol])]
            if len(vols) >= 60:
                v60 = sum(vols[-60:]) / 60.0
                if v60 > 0:
                    o["volr"] = (sum(vols[-5:]) / 5.0) / v60
        return o, ""
    except Exception as e:
        return None, str(e)[:50]


def main_biz(ak, code):
    for fn in (lambda: ak.stock_zygc_em(symbol=code),
               lambda: ak.stock_zygc_ym(symbol=code)):
        try:
            df = fn()
            if df is None or len(df) == 0:
                continue
            c_item = col(df, "主营构成", "分类", "项目")
            c_ratio = col(df, "收入比例", "占比", "营收占比")
            if not c_item:
                continue
            rows = []
            for _, r in df.head(6).iterrows():
                rows.append("%s %s" % (str(r[c_item]),
                                       str(r[c_ratio]) if c_ratio else ""))
            return rows
        except Exception:
            continue
    return None


def fund_flow(ak, code):
    mk = "sh" if code.startswith("6") else (
        "bj" if code[:2] in ("92", "83", "87") else "sz")
    for fn in (lambda: ak.stock_individual_fund_flow(stock=code, market=mk),
               lambda: ak.stock_individual_fund_flow(stock=code)):
        try:
            df = fn()
            if df is None or len(df) == 0:
                continue
            c_d = col(df, "日期", "date")
            c_m = col(df, "主力净流入-净额", "主力净流入")
            if c_m is None:
                continue
            rows = []
            for _, r in df.tail(5).iterrows():
                d = str(r[c_d])[:10] if c_d else ""
                rows.append("%s 主力%+.2f亿" % (d, float(r[c_m]) / 1e8))
            return rows
        except Exception:
            continue
    return None


def board_detail(ak, name):
    tries = []
    try:
        sec = ak.stock_sector_spot(indicator="行业")
        c_lab = col(sec, "label")
        c_nm = col(sec, "板块", "板块名称")
        if c_lab and c_nm:
            for _, r in sec.iterrows():
                if name in str(r[c_nm]):
                    lb = str(r[c_lab])
                    tries.append(("新浪",
                                  lambda x=lb: ak.stock_sector_detail(sector=x)))
                    break
    except Exception as e:
        note("板块列表(新浪) 失败：%s" % str(e)[:50])
    tries.append(("东财行业",
                  lambda: ak.stock_board_industry_cons_em(symbol=name)))
    tries.append(("东财概念",
                  lambda: ak.stock_board_concept_cons_em(symbol=name)))

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
                cd = ""
                if c_c:
                    cd = "".join([c for c in str(r[c_c]) if c.isdigit()])[-6:]
                rows.append((str(r[c_n]), cd, p))
            return (src, rows)
        except Exception as e:
            note("板块[%s|%s] %s" % (name, src, str(e)[:40]))
    return None


def _f(v):
    return "【无】" if v is None else ("%.2f" % v)


def _p(v):
    return "【无】" if v is None else ("%+.2f%%" % v)


def _amt(v):
    if v is None:
        return "【无】"
    return "%.2f亿" % (v / 1e8) if v > 1e6 else str(v)


def _save(L, bj):
    text = "\n".join(L)
    print(text)
    try:
        if not os.path.isdir(OUTDIR):
            os.makedirs(OUTDIR)
        d = bj.strftime("%Y%m%d")
        io.open(os.path.join(OUTDIR, "查询结果_最新.txt"),
                "w", encoding="utf-8").write(text)
        io.open(os.path.join(OUTDIR, "查询结果_%s.txt" % d),
                "w", encoding="utf-8").write(text)
        print("✅ patch_query: 已写出 reports/查询结果_最新.txt")
    except Exception as e:
        print("🔴 patch_query: 写文件失败 %s" % e)


def run():
    bj = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    L = []

    def w(s=""):
        L.append(s)

    w("=" * 68)
    w("🔎【点单查询结果】北京 %s" % bj.strftime("%Y-%m-%d %H:%M"))
    w("   来源：仓库根目录的 查询.txt（一行一个：代码 / 名称 / 板块名）")
    w("   ⚠️【无数据】= 真的取不到，绝不编数（铁律Y）")
    w("=" * 68)

    if not os.path.exists(QUERY_FILE):
        w("")
        w("📭 没找到 %s → 本次无查询" % QUERY_FILE)
        w("")
        w("   ── 怎么用 ──")
        w("   在仓库【根目录】新建 查询.txt，内容例如：")
        w("     002297")
        w("     中航沈飞")
        w("     军工装备")
        w("   然后 Actions 跑一次，结果就出现在这个文件里。")
        w("=" * 68)
        _save(L, bj)
        return

    lines = []
    for ln in io.open(QUERY_FILE, encoding="utf-8"):
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            lines.append(ln)
    lines = lines[:MAX_ITEMS]
    w("   本次查询 %d 项" % len(lines))

    try:
        import akshare as ak
    except Exception as e:
        w("🔴 akshare 导入失败：%s" % e)
        _save(L, bj)
        return

    snap = load_snapshot(ak)
    name2code = {}
    for cd, v in snap.items():
        name2code[v["name"].replace(" ", "")] = cd

    stocks, boards = [], []
    for q in lines:
        qq = q.replace(" ", "")
        if qq.isdigit() and len(qq) == 6:
            stocks.append(qq)
        elif qq in name2code:
            stocks.append(name2code[qq])
        else:
            boards.append(q)

    if stocks:
        w("")
        w("█" * 26)
        w("█  个 股  (%d只)" % len(stocks))
        w("█" * 26)

        def job(cd):
            k, err = kline_info(ak, cd)
            return (cd, k, err, main_biz(ak, cd), fund_flow(ak, cd))

        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            res = list(ex.map(job, stocks))

        for cd, k, err, biz, ff in res:
            s = snap.get(cd, {})
            w("")
            w("─" * 68)
            w("◆ %s(%s)" % (s.get("name", "?"), cd))
            if s:
                w("   现价%s ｜ 今日%s ｜ 成交%s ｜ 换手%s ｜ 市盈%s"
                  % (_f(s.get("price")), _p(s.get("pct")),
                     _amt(s.get("amt")), _p(s.get("turn")), _f(s.get("pe"))))
            else:
                w("   快照【无数据】")
            if k:
                pos = "🔴高点附近·追高区" if k["from_hi"] > -3 else (
                    "🟢60日低位·可埋伏" if k["from_lo"] < 8 else "🟡中段")
                w("   60日%+.1f%% ｜ 距高点%+.1f%% 距低点%+.1f%% %s"
                  % (k["d60"], k["from_hi"], k["from_lo"], pos))
                ex2 = []
                if k["streak"]:
                    ex2.append("🔥连板%d天" % k["streak"])
                if k["volr"] is not None:
                    t = "缩量" if k["volr"] < 0.8 else (
                        "放量" if k["volr"] > 1.5 else "常量")
                    ex2.append("5日/60日量=%.2f(%s)" % (k["volr"], t))
                if ex2:
                    w("   " + " ｜ ".join(ex2))
            else:
                w("   K线位置【无数据】%s" % err)
            if biz:
                w("   ★主营构成★ " + " / ".join(biz))
            else:
                w("   ★主营构成★【无数据】→ ⚠️需你截 F10→简况/市场印象")
            if ff:
                w("   个股资金 " + " ｜ ".join(ff))
            else:
                w("   个股资金【无数据】→ ⚠️需你截 F10→资金")

    for b in boards:
        if over():
            break
        w("")
        w("█" * 26)
        w("█  板 块：%s" % b)
        w("█" * 26)
        got = board_detail(ak, b)
        if not got:
            w("   🔴 取数失败，本板块【无数据】")
            continue
        src, rows = got
        r2 = [r for r in rows if r[2] is not None]
        r2.sort(key=lambda x: x[2])
        w("   成分%d只 ｜ 源:%s ｜ ★按涨幅从小到大排（找谁还没涨）★"
          % (len(rows), src))
        cold = [r for r in r2 if r[2] < 3.0]
        w("   ── 还没涨(<3%%)：%d只 ──" % len(cold))
        for nm, cd, p in cold[:30]:
            w("     %s %-8s %-8s %+6.2f%%"
              % ("🟢没涨" if p < 1.0 else "🟡微涨", nm, cd, p))
        hot = [r for r in r2 if r[2] >= 9.0]
        if hot:
            w("   （已涨停%d只：%s）"
              % (len(hot), "、".join([h[0] for h in hot[:10]])))

    w("")
    w("=" * 68)
    w("⚠️ 主营构成 / 个股资金 若为【无数据】= 海外IP拿不到（已知死结），")
    w("   那两项仍需截图。但现价/位置/连板/缩量/板块成分，以后不用再截。")
    w("   日志：")
    for s in _LOG[:10]:
        w("     · %s" % s)
    w("   耗时 %.1f 秒" % (time.time() - _T0))
    w("=" * 68)

    _save(L, bj)


try:
    run()
except Exception:
    print("🔴 patch_query 整体异常，已跳过，不影响主扫描：")
    traceback.print_exc()

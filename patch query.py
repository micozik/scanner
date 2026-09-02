# -*- coding: utf-8 -*-
"""
patch_query.py  ——  放仓库【根目录】，和 scanner_cloud.py 同一层

╔════════════════════════════════════════════════════════════════╗
║  怎么用（不用改任何文件）：                                      ║
║    Actions → A股自动扫描 → Run workflow                         ║
║    在那个输入框里直接填，多只用逗号分隔：                        ║
║        中航沈飞, 002297, 军工装备                               ║
║    跑完看 reports/查询结果_最新.txt                             ║
╚════════════════════════════════════════════════════════════════╝

★为什么能读到输入框★
  GitHub Actions 会把你填的内容写进一个 JSON 文件，
  路径在环境变量 GITHUB_EVENT_PATH 里。
  本程序直接读那个 JSON 的 inputs 字段 ——
  ★不管那个输入框在 scan.yml 里叫什么名字都能读到，
    也不需要改 scan.yml 一个字。★
  （备用：也支持读根目录的 查询.txt，两者都没有就跳过）

★为什么要这个工具★
  2026-09-02 我连续两次在数据不足时就下推荐：
    · 博云新材 —— 我以为"硬质合金=高温合金"，实际它78%收入是碳化钨基
    · 中航沈飞 —— 我不知道它H1净利-58.37%、市盈47.77、主力资金在减速
  两次都靠用户截图当场推翻。★根因：清单外的票我完全是瞎的。★

★能拿到什么（海外IP实测可行）★
  ✅ 现价/涨跌/成交额/换手/市盈
  ✅ 60日涨跌、距60日高低点、连板天数、缩量倍数（K线自算）
  ✅ 板块全部成分股，★按涨幅从小到大排★（找"谁还没涨"）
  🟡 主营构成/个股资金流 —— 会试，海外IP大概率失败
     失败写【无数据】，★绝不编数★

★安全性★
  · ★完全不改 scanner_cloud.py / scanner_usa.py / scan.yml★
  · 只写 reports/查询结果_*.txt
  · 150秒硬预算 + 8线程并发 + 全程异常捕获
"""

import io
import os
import re
import json
import time
import datetime
import traceback
from concurrent.futures import ThreadPoolExecutor

OUTDIR = "reports"
QUERY_FILE = "查询.txt"
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


# ═══════════ 读取"点单"：输入框优先，文件兜底 ═══════════
def read_query():
    raw = ""
    src = ""

    # ① Actions 输入框（读事件JSON，不依赖输入框叫什么名字）
    p = os.environ.get("GITHUB_EVENT_PATH", "")
    if p and os.path.exists(p):
        try:
            ev = json.load(io.open(p, encoding="utf-8"))
            inputs = ev.get("inputs") or {}
            vals = []
            for k, v in inputs.items():
                if v and str(v).strip():
                    vals.append(str(v).strip())
                    note("读到输入框[%s]=%s" % (k, str(v)[:40]))
            if vals:
                raw = ",".join(vals)
                src = "Actions输入框"
        except Exception as e:
            note("读事件JSON失败：%s" % str(e)[:60])

    # ② 环境变量兜底（万一 yml 把它塞进了 env）
    if not raw:
        for k, v in os.environ.items():
            if k.startswith("INPUT_") and v and v.strip():
                raw = v.strip()
                src = "环境变量 %s" % k
                break

    # ③ 文件兜底
    if not raw and os.path.exists(QUERY_FILE):
        try:
            lines = []
            for ln in io.open(QUERY_FILE, encoding="utf-8"):
                ln = ln.strip()
                if ln and not ln.startswith("#"):
                    lines.append(ln)
            if lines:
                raw = ",".join(lines)
                src = QUERY_FILE
        except Exception:
            pass

    if not raw:
        return [], ""

    parts = [x.strip() for x in re.split(r"[,，\s;；\n]+", raw) if x.strip()]
    return parts[:MAX_ITEMS], src


def _num(r, c):
    if not c:
        return None
    try:
        return float(r[c])
    except Exception:
        return None


def load_snapshot(ak):
    for tag, fn in (("新浪", lambda: ak.stock_zh_a_spot()),
                    ("东财", lambda: ak.stock_zh_a_spot_em())):
        try:
            df = fn()
            if df is None or len(df) < 100:
                continue
            c_code = col(df, "代码", "symbol", "code")
            c_name = col(df, "名称", "name")
            if not (c_code and c_name):
                continue
            c_price = col(df, "最新价", "trade", "现价")
            c_pct = col(df, "涨跌幅", "changepercent", "pct_chg")
            c_amt = col(df, "成交额", "amount")
            c_turn = col(df, "换手率", "turnoverratio")
            c_pe = col(df, "市盈率-动态", "per", "市盈率")
            m = {}
            for _, r in df.iterrows():
                try:
                    d = "".join([c for c in str(r[c_code]) if c.isdigit()])
                    code = d[-6:]
                    if len(code) != 6:
                        continue
                    m[code] = {"name": str(r[c_name]).strip(),
                               "price": _num(r, c_price),
                               "pct": _num(r, c_pct),
                               "amt": _num(r, c_amt),
                               "turn": _num(r, c_turn),
                               "pe": _num(r, c_pe)}
                except Exception:
                    continue
            note("快照[%s] %d只" % (tag, len(m)))
            return m
        except Exception as e:
            note("快照[%s]失败 %s" % (tag, str(e)[:50]))
    return {}


def kline_info(ak, code):
    if over():
        return None, "超时预算用尽"
    end = datetime.datetime.now().strftime("%Y%m%d")
    start = (datetime.datetime.now()
             - datetime.timedelta(days=95)).strftime("%Y%m%d")
    df, err = None, ""
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
        cc = col(df, "收盘", "close")
        cp = col(df, "涨跌幅", "pct_chg")
        cv = col(df, "成交量", "volume")
        closes = [float(x) for x in list(df[cc])[-60:]]
        last = closes[-1]
        o = {"last": last, "d60": (last / closes[0] - 1) * 100,
             "hi": max(closes), "lo": min(closes),
             "streak": None, "volr": None}
        o["from_hi"] = (last / o["hi"] - 1) * 100
        o["from_lo"] = (last / o["lo"] - 1) * 100
        if cp is not None:
            pcts = [float(x) for x in list(df[cp])]
            lim = board_limit(code)
            n = 0
            for v in reversed(pcts):
                if v >= lim:
                    n += 1
                else:
                    break
            o["streak"] = n
        if cv is not None:
            vols = [float(x) for x in list(df[cv])]
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
            ci = col(df, "主营构成", "分类", "项目")
            cr = col(df, "收入比例", "占比", "营收占比")
            if not ci:
                continue
            return ["%s %s" % (str(r[ci]), str(r[cr]) if cr else "")
                    for _, r in df.head(6).iterrows()]
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
            cd = col(df, "日期", "date")
            cm = col(df, "主力净流入-净额", "主力净流入")
            if cm is None:
                continue
            out = []
            for _, r in df.tail(5).iterrows():
                out.append("%s 主力%+.2f亿"
                           % (str(r[cd])[:10] if cd else "",
                              float(r[cm]) / 1e8))
            return out
        except Exception:
            continue
    return None


def board_detail(ak, name):
    tries = []
    try:
        sec = ak.stock_sector_spot(indicator="行业")
        cl = col(sec, "label")
        cn = col(sec, "板块", "板块名称")
        if cl and cn:
            for _, r in sec.iterrows():
                if name in str(r[cn]):
                    lb = str(r[cl])
                    tries.append(("新浪",
                                  lambda x=lb: ak.stock_sector_detail(sector=x)))
                    break
    except Exception as e:
        note("板块列表(新浪)失败 %s" % str(e)[:40])
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
            cn2 = col(df, "名称", "股票简称", "name")
            cc2 = col(df, "代码", "股票代码", "symbol", "code")
            cp2 = col(df, "涨跌幅", "changepercent", "pct_chg")
            if not cn2:
                continue
            rows = []
            for _, r in df.iterrows():
                try:
                    p = float(r[cp2]) if cp2 else None
                except Exception:
                    p = None
                cd = ""
                if cc2:
                    cd = "".join([c for c in str(r[cc2]) if c.isdigit()])[-6:]
                rows.append((str(r[cn2]), cd, p))
            return (src, rows)
        except Exception as e:
            note("板块[%s|%s] %s" % (name, src, str(e)[:35]))
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
    t = "\n".join(L)
    print(t)
    try:
        if not os.path.isdir(OUTDIR):
            os.makedirs(OUTDIR)
        d = bj.strftime("%Y%m%d")
        io.open(os.path.join(OUTDIR, "查询结果_最新.txt"),
                "w", encoding="utf-8").write(t)
        io.open(os.path.join(OUTDIR, "查询结果_%s.txt" % d),
                "w", encoding="utf-8").write(t)
        print("✅ patch_query: 已写出 reports/查询结果_最新.txt")
    except Exception as e:
        print("🔴 patch_query: 写文件失败 %s" % e)


def run():
    bj = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    L = []

    def w(s=""):
        L.append(s)

    items, src = read_query()

    w("=" * 68)
    w("🔎【点单查询】北京 %s" % bj.strftime("%Y-%m-%d %H:%M"))
    w("   ⚠️【无数据】= 真的取不到，绝不编数（铁律Y）")
    w("=" * 68)

    if not items:
        w("")
        w("📭 本次没有点单（输入框留空，也没有 查询.txt）")
        w("")
        w("   ── 怎么用 ──")
        w("   Actions → A股自动扫描 → Run workflow")
        w("   在输入框里填，逗号分隔，可混填：")
        w("       中航沈飞, 002297, 军工装备")
        w("=" * 68)
        _save(L, bj)
        return

    w("   点单来源：%s ｜ 共 %d 项：%s"
      % (src, len(items), "、".join(items)))

    try:
        import akshare as ak
    except Exception as e:
        w("🔴 akshare 导入失败：%s" % e)
        _save(L, bj)
        return

    snap = load_snapshot(ak)
    n2c = {}
    for cd, v in snap.items():
        n2c[v["name"].replace(" ", "")] = cd

    stocks, boards = [], []
    for q in items:
        qq = q.replace(" ", "")
        if qq.isdigit() and len(qq) == 6:
            stocks.append(qq)
        elif qq in n2c:
            stocks.append(n2c[qq])
        else:
            boards.append(q)

    if stocks:
        w("")
        w("█" * 26)
        w("█  个 股  (%d只)" % len(stocks))
        w("█" * 26)

        def job(cd):
            k, e = kline_info(ak, cd)
            return (cd, k, e, main_biz(ak, cd), fund_flow(ak, cd))

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
                e2 = []
                if k["streak"]:
                    e2.append("🔥连板%d天" % k["streak"])
                if k["volr"] is not None:
                    t = "缩量" if k["volr"] < 0.8 else (
                        "放量" if k["volr"] > 1.5 else "常量")
                    e2.append("5日/60日量=%.2f(%s)" % (k["volr"], t))
                if e2:
                    w("   " + " ｜ ".join(e2))
            else:
                w("   K线位置【无数据】%s" % err)
            w("   ★主营构成★ " + (" / ".join(biz) if biz
                               else "【无数据】→ ⚠️需截 F10→简况"))
            w("   个股资金 " + (" ｜ ".join(ff) if ff
                            else "【无数据】→ ⚠️需截 F10→资金"))

    for b in boards:
        if over():
            break
        w("")
        w("█" * 26)
        w("█  板 块：%s" % b)
        w("█" * 26)
        got = board_detail(ak, b)
        if not got:
            w("   🔴 取数失败【无数据】")
            continue
        s2, rows = got
        r2 = sorted([r for r in rows if r[2] is not None], key=lambda x: x[2])
        w("   成分%d只 ｜ 源:%s ｜ ★按涨幅从小到大排（找谁还没涨）★"
          % (len(rows), s2))
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
    w("⚠️ 主营构成/个股资金 若为【无数据】= 海外IP拿不到（已知死结），")
    w("   那两项仍需截图。位置/连板/缩量/板块成分 以后不用再截。")
    for s in _LOG[:8]:
        w("     · %s" % s)
    w("   耗时 %.1f 秒" % (time.time() - _T0))
    w("=" * 68)
    _save(L, bj)


try:
    run()
except Exception:
    print("🔴 patch_query 整体异常，已跳过，不影响主扫描：")
    traceback.print_exc()

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
TIME_BUDGET = 90.0
MAX_ITEMS = 20
WORKERS = 8

# ★★★ 安全开关 ★★★
# 主扫描 scan.yml 基线20分02秒、上限22分钟，只剩2分钟余量。
# #518 就是因为本补丁被 patch*.py 循环带进主扫描，跑到22m26s被强杀。
# → 只有独立的 query.yml 会设 QUERY_MODE=1，那时才干活；
#   在主扫描里被扫到时，0秒退出，★对主扫描零影响★。
if os.environ.get("QUERY_MODE") != "1":
    print("⏭️ patch_query: 非查询模式，跳过（对主扫描零耗时）")
    raise SystemExit(0)

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

    # ⓪ query.yml 直接传进来的（最可靠）
    qt = os.environ.get("QUERY_TEXT", "")
    if qt and qt.strip():
        return ([x.strip() for x in
                 re.split(r"[,，\s;；\n]+", qt.strip()) if x.strip()][:MAX_ITEMS],
                "Actions输入框")

    # ① Actions 事件JSON（不依赖输入框叫什么名字）
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
    # 2026-10-26 v2：新浪/东财都失败时，run() 里会用腾讯 qt.gtimg.cn 补快照、补当日主力资金
    # 2026-10-26 #37 两源同时 RemoteDisconnected → 10只全【无数据】。加一轮重试（间隔8秒）
    import time as _t
    for _round in range(2):
        m = _load_snapshot_once(ak)
        if m:
            return m
        if _round == 0:
            note("快照两源均失败，8秒后重试一轮")
            _t.sleep(8)
    return {}


def _load_snapshot_once(ak):
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


_TK = [None]   # ★11/01：K线单独计时。东财快照有时要90秒+，把总预算吃光，导致均线/买点关整段缺失（q57）


def kline_info(ak, code):
    if _TK[0] is None:
        _TK[0] = time.time()
    if time.time() - _TK[0] > 150:
        return None, "K线预算用尽"
    end = datetime.datetime.now().strftime("%Y%m%d")
    start = (datetime.datetime.now()
             - datetime.timedelta(days=200)).strftime("%Y%m%d")   # ★11/03 拉长到200天：要MA60/MA120
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
        # v3 2026-10-26：东财K线晚上断线（#39 十只全挂），用腾讯日K兜底（国家队雷达同源，一直能通）
        try:
            import json as _j
            import pandas as _pd
            mk = _tx_mk(code)
            raw = _tx_get("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=%s,day,,,140,qfq" % mk)
            dd = _j.loads(raw)["data"][mk]
            rows = dd.get("qfqday") or dd.get("day") or []
            recs, prev = [], None
            for r in rows:
                c = float(r[2])
                recs.append({"收盘": c, "成交量": float(r[5]), "最高": float(r[3]), "最低": float(r[4]),
                             "涨跌幅": ((c / prev - 1) * 100) if prev else 0.0})
                prev = c
            if len(recs) > 5:
                df = _pd.DataFrame(recs)
                note("K线[腾讯]兜底 %s" % code)
        except Exception as e2:
            err = (err + " | 腾讯:" + str(e2)[:40])
    if df is None:
        return None, err or "K线取数失败"
    try:
        cc = col(df, "收盘", "close")
        cp = col(df, "涨跌幅", "pct_chg")
        cv = col(df, "成交量", "volume")
        allc = [float(x) for x in list(df[cc])]
        closes = allc[-60:]
        last = closes[-1]
        o = {"last": last, "d60": (last / closes[0] - 1) * 100,
             "hi": max(closes), "lo": min(closes),
             "streak": None, "volr": None}
        o["from_hi"] = (last / o["hi"] - 1) * 100
        o["from_lo"] = (last / o["lo"] - 1) * 100
        # v4 2026-10-30：均线（买前必看20日线方向——招商轮船买在下行20日线下方的教训）
        if len(closes) >= 25:
            o["ma5"] = sum(closes[-5:]) / 5.0
            o["ma10"] = sum(closes[-10:]) / 10.0
            o["ma20"] = sum(closes[-20:]) / 20.0
            o["ma20p"] = sum(closes[-25:-5]) / 20.0
            o["d5"] = (last / closes[-6] - 1) * 100
            _m20 = o["ma20"]
            _sd = (sum((c - _m20) ** 2 for c in closes[-20:]) / 20.0) ** 0.5
            o["boll_lo"] = _m20 - 2 * _sd   # ★11/03：布林下轨，超跌错杀单用（招商10/23正好打到下轨15.87）
            o["boll_hi"] = _m20 + 2 * _sd
        # ★11/03 深查：MA60/MA120 + ATR14（止损/仓位用）
        try:
            o["ma60"] = sum(allc[-60:]) / 60.0 if len(allc) >= 60 else None
            o["ma120"] = sum(allc[-120:]) / 120.0 if len(allc) >= 120 else None
            o["d20"] = (last / allc[-21] - 1) * 100 if len(allc) >= 21 else None
            ch, cl_ = col(df, "最高", "high"), col(df, "最低", "low")
            if ch is not None and cl_ is not None:
                hs = [float(x) for x in list(df[ch])]
                ls = [float(x) for x in list(df[cl_])]
                trs = []
                for i in range(max(1, len(allc) - 14), len(allc)):
                    trs.append(max(hs[i] - ls[i], abs(hs[i] - allc[i - 1]), abs(ls[i] - allc[i - 1])))
                if trs:
                    o["atr"] = sum(trs) / len(trs)
                o["hi20"] = max(hs[-20:])
                o["lo20"] = min(ls[-20:])
        except Exception:
            pass
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
    """主营构成：东财(代码要带 SH/SZ 前缀，原来传6位一直失败) → 同花顺主营介绍兜底"""
    try:
        df = ak.stock_zygc_em(symbol=_tx_mk(code).upper())
        if df is not None and len(df):
            cd_ = col(df, "报告日期")
            if cd_:
                df = df[df[cd_].astype(str) == str(sorted(df[cd_].astype(str))[-1])]
            ct = col(df, "分类类型")
            if ct is not None:
                for pref in ("按产品分类", "按行业分类"):
                    sub = df[df[ct].astype(str) == pref]
                    if len(sub):
                        df = sub
                        break
            ci = col(df, "主营构成")
            cr = col(df, "收入比例")
            cm = col(df, "毛利率")
            if ci:
                out = []
                for _, r in df.head(6).iterrows():
                    try:
                        out.append("%s 占%.0f%%%s" % (r[ci], float(r[cr]) * 100,
                                                     (" 毛利%.0f%%" % (float(r[cm]) * 100)) if cm else ""))
                    except Exception:
                        out.append(str(r[ci]))
                return out
    except Exception as e:
        note("主营[东财]失败 %s %s" % (code, str(e)[:40]))
    try:
        df = ak.stock_zyjs_ths(symbol=code)
        if df is not None and len(df):
            r = df.iloc[0]
            out = []
            for c in ("主营业务", "产品类型", "产品名称"):
                if c in df.columns and str(r[c]) not in ("", "nan", "None"):
                    out.append("%s：%s" % (c, str(r[c])[:60]))
            if out:
                return out
    except Exception as e:
        note("主营[同花顺]失败 %s %s" % (code, str(e)[:40]))
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


def _tx_mk(code):
    return ("sh" if code.startswith(("6", "9")) and not code.startswith("92")
            else ("bj" if code[:2] in ("92", "83", "87", "43") else "sz")) + code


def _tx_get(url):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                               "Referer": "https://gu.qq.com/"})
    raw = urllib.request.urlopen(req, timeout=6).read()
    try:
        return raw.decode("gbk")
    except Exception:
        return raw.decode("utf-8", "ignore")


def _tx_quote(codes):
    """腾讯行情兜底（2026-10-26：新浪/东财快照晚上从海外连不上，腾讯K线一直能通）"""
    out = {}
    if not codes:
        return out
    try:
        txt = _tx_get("https://qt.gtimg.cn/q=" + ",".join(_tx_mk(c) for c in codes))
    except Exception as e:
        note("快照[腾讯]失败 %s" % str(e)[:50])
        return out
    for line in txt.split(";"):
        if '="' not in line:
            continue
        body = line.split('="', 1)[1].rstrip('"').strip()
        f = body.split("~")
        if len(f) < 40:
            continue
        code = f[2][-6:]

        def fl(i):
            try:
                return float(f[i])
            except Exception:
                return None
        amt = fl(37)
        out[code] = {"name": f[1].strip(), "price": fl(3), "pct": fl(32),
                     "amt": amt * 1e4 if amt is not None else None,
                     "turn": fl(38), "pe": fl(39)}
    if out:
        note("快照[腾讯] 补到%d只" % len(out))
    return out


def _tx_ff(code):
    """腾讯资金流向兜底：qt.gtimg.cn/q=ff_xxx（单位万元，只有当日）"""
    try:
        txt = _tx_get("https://qt.gtimg.cn/q=ff_" + _tx_mk(code))
        body = txt.split('="', 1)[1].split('"', 1)[0]
        f = body.split("~")
        if len(f) < 10:
            return None

        def fl(i):
            try:
                return float(f[i])
            except Exception:
                return None
        inn, outt, net = fl(1), fl(2), fl(3)
        if net is None:
            return ["腾讯资金原始：" + "~".join(f[:8])[:80]]
        dt = f[13] if len(f) > 13 else ""
        note("资金[腾讯]原始 %s（首次上线用来核对字段）" % "~".join(f[:5] + f[12:14]))
        return ["%s 主力净流入%+.2f亿（腾讯：流入%.2f亿 流出%.2f亿）"
                % (dt, net / 1e4, (inn or 0) / 1e4, (outt or 0) / 1e4)]
    except Exception as e:
        note("资金[腾讯]失败 %s %s" % (code, str(e)[:60]))
        return None


def _sina_ff(code):
    """v4 2026-10-30：新浪资金流向兜底（新浪快照在海外IP能通；腾讯ff_接口已返回空）。单位元。"""
    try:
        import json as _j, re as _r, urllib.request
        url = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
               "MoneyFlow.ssl_qsfx_zjlrqs?page=1&num=5&sort=opendate&asc=0&daima=" + _tx_mk(code))
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                                   "Referer": "https://finance.sina.com.cn/"})
        raw = urllib.request.urlopen(req, timeout=8).read()
        try:
            txt = raw.decode("gbk")
        except Exception:
            txt = raw.decode("utf-8", "ignore")
        txt = txt.strip()
        if not txt.startswith("["):
            note("资金[新浪]非预期返回 %s %s" % (code, txt[:60]))
            return None
        txt = _r.sub(r'([{,])\s*([A-Za-z_][A-Za-z0-9_]*)\s*:', r'\1"\2":', txt)
        rows = _j.loads(txt)
        out = []
        for r in rows[:5]:
            def g(k):
                try:
                    return float(r.get(k) or 0)
                except Exception:
                    return 0.0
            main = g("r0_net") + g("r1_net")   # 实测该接口只有 r0_net（=主力净流入），r1_net 为空
            out.append("%s 主力%+.2f亿（新浪）" % (str(r.get("opendate", ""))[:10], main / 1e8))
        if out:
            note("资金[新浪]兜底 %s" % code)
        return out or None
    except Exception as e:
        note("资金[新浪]失败 %s %s" % (code, str(e)[:60]))
        return None


# ════════════════════════════════════════════════════════════════════
# ★11/03 深查模块（Zikye：查一次就要有结论，100%全面）
#   估值 / 基本面 / 新闻公告 / 解禁 / 两融 / 行业板块 / 相对强弱 / 止损仓位 / 综合结论
#   每项独立 try，取不到就写【无数据】+原因，绝不编数
# ════════════════════════════════════════════════════════════════════
def _http(url, ref="https://finance.sina.com.cn/", timeout=8):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                                               "Referer": ref})
    try:
        raw = urllib.request.urlopen(req, timeout=timeout).read()
    except Exception:
        time.sleep(1.5)   # SSL握手偶发失败，重试一次
        raw = urllib.request.urlopen(req, timeout=timeout).read()
    for enc in ("gbk", "utf-8"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("utf-8", "ignore")


def _strip(h):
    import re as _r
    return _r.sub(r"\s+", " ", _r.sub(r"<[^>]+>", " ", h.replace("&nbsp;", " "))).strip()


def deep_valuation(code):
    """腾讯行情：PE(TTM)/PE静/PB/总市值/流通市值/量比/振幅/涨跌停价"""
    try:
        txt = _tx_get("https://qt.gtimg.cn/q=" + _tx_mk(code))
        f = txt.split('="', 1)[1].split('"', 1)[0].split("~")

        def fl(i):
            try:
                return float(f[i])
            except Exception:
                return None
        return {"pe": fl(39), "pe_d": fl(52) if len(f) > 52 else None, "pe_s": fl(53) if len(f) > 53 else None,
                "pb": fl(46), "mv": fl(45), "fmv": fl(44), "lb": fl(49), "zf": fl(43),
                "zt": fl(47), "dt": fl(48)}
    except Exception as e:
        note("估值[腾讯]失败 %s %s" % (code, str(e)[:50]))
        return None


_FIN_KEYS = [("营业总收入", "营收"), ("营业收入", "营收"), ("归母净利润", "归母净利"),
             ("归属于母公司所有者的净利润", "归母净利"), ("净利润", "净利"),
             ("扣非净利润", "扣非"), ("毛利率", "毛利率"), ("销售毛利率", "毛利率"),
             ("净资产收益率", "ROE"), ("ROE", "ROE"), ("经营现金流量净额", "经营现金流"),
             ("每股经营现金流", "每股经营现金流"), ("资产负债率", "负债率")]


def deep_fin(ak, code):
    """基本面：新浪关键指标（stock_financial_abstract）→ 同花顺兜底。返回[(名称,[(期,值)...])]"""
    out = []
    try:
        df = ak.stock_financial_abstract(symbol=code)
        if df is not None and len(df):
            dcols = [c for c in df.columns if str(c)[:2] in ("20", "19") and len(str(c)) == 8][:5]
            ncol = "指标" if "指标" in df.columns else df.columns[1]
            seen = set()
            for k, lab in _FIN_KEYS:
                if lab in seen:
                    continue
                hit = df[df[ncol].astype(str) == k]
                if len(hit):
                    r = hit.iloc[0]
                    vals = []
                    for c in dcols:
                        try:
                            vals.append((str(c), float(r[c])))
                        except Exception:
                            pass
                    if vals:
                        out.append((lab, vals))
                        seen.add(lab)
            if out:
                return out, "新浪"
    except Exception as e:
        note("基本面[新浪]失败 %s %s" % (code, str(e)[:60]))
    try:
        df = ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期")
        if df is not None and len(df):
            df = df.tail(5).iloc[::-1] if str(df.iloc[0, 0]) < str(df.iloc[-1, 0]) else df.head(5)
            pc = df.columns[0]
            for c in df.columns[1:]:
                cs = str(c)
                lab = None
                for k, l2 in [("营业总收入", "营收"), ("净利润", "净利"), ("扣非净利润", "扣非"),
                              ("销售毛利率", "毛利率"), ("净资产收益率", "ROE"), ("每股经营现金流", "每股经营现金流"),
                              ("资产负债率", "负债率"), ("净利润同比增长率", "净利同比"), ("营业总收入同比增长率", "营收同比")]:
                    if cs == k:
                        lab = l2
                if lab:
                    out.append((lab, [(str(r[pc]), str(r[c])) for _, r in df.iterrows()]))
            if out:
                return out, "同花顺"
    except Exception as e:
        note("基本面[同花顺]失败 %s %s" % (code, str(e)[:60]))
    return None, ""


_BAD = ("减持", "解禁", "质押", "问询", "立案", "处罚", "预亏", "首亏", "下修", "亏损", "终止", "诉讼", "冻结",
        "退市", "风险提示", "监管", "警示", "违规", "延期", "下滑", "暴跌", "辞职")
_GOOD = ("增持", "回购", "中标", "预增", "扭亏", "分红", "派息", "合同", "签约", "获批", "突破", "订单",
         "创新高", "大增", "战略合作", "入股", "举牌", "超预期")


def _flag(t):
    b = [k for k in _BAD if k in t]
    g = [k for k in _GOOD if k in t]
    return ("🔴" if b else ("🟢" if g else "·")), b, g


def deep_news(code, days=12):
    """新浪个股新闻 + 公告，近N天，自动标红绿"""
    import re as _r
    lim = (datetime.datetime.utcnow() + datetime.timedelta(hours=8) - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    news, ann = [], []
    pat = _r.compile(r"(\d{4}-\d{2}-\d{2})(?:\s|&nbsp;)*(?:\d{2}:\d{2})?(?:\s|&nbsp;)*<a[^>]*>([^<]{4,120})</a>")
    try:
        h = _http("https://vip.stock.finance.sina.com.cn/corp/go.php/vCB_AllNewsStock/symbol/%s.phtml" % _tx_mk(code))
        for d, t in pat.findall(h):
            if d >= lim:
                news.append((d, t.strip()))
    except Exception as e:
        note("新闻[新浪]失败 %s %s" % (code, str(e)[:50]))
        news = None
    try:
        h = _http("https://vip.stock.finance.sina.com.cn/corp/go.php/vCB_AllBulletin/stockid/%s.phtml" % code)
        for d, t in pat.findall(h):
            if d >= lim:
                ann.append((d, t.strip()))
    except Exception as e:
        note("公告[新浪]失败 %s %s" % (code, str(e)[:50]))
        ann = None
    return news, ann


def deep_unlock(ak, code):
    """限售解禁（未来/近期）：大额解禁=资本出货窗口"""
    try:
        df = ak.stock_restricted_release_queue_sina(symbol=code)
        if df is None or not len(df):
            return []
        today = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).date()
        cd_ = col(df, "解禁日期", "上市日期")
        cn = col(df, "解禁数量", "解禁数量(万股)")
        cr = col(df, "解禁股流通市值", "占总股本比例", "解禁市值")
        out = []
        for _, r in df.iterrows():
            try:
                d = datetime.datetime.strptime(str(r[cd_])[:10], "%Y-%m-%d").date()
            except Exception:
                continue
            if -30 <= (d - today).days <= 120:
                out.append("%s 解禁%s %s" % (d, r[cn] if cn else "", ("占比/市值 %s" % r[cr]) if cr else ""))
        return out
    except Exception as e:
        note("解禁失败 %s %s" % (code, str(e)[:50]))
        return None


def deep_margin(code):
    """两融：新浪融资融券明细页，取近10个交易日融资余额趋势"""
    import re as _r
    try:
        end = (datetime.datetime.utcnow() + datetime.timedelta(hours=8))
        bd = (end - datetime.timedelta(days=25)).strftime("%Y-%m-%d")
        h = _http("https://vip.stock.finance.sina.com.cn/q/go.php/vInvestConsult/kind/rzrq/index.phtml"
                  "?symbol=%s&bdate=%s&edate=%s" % (_tx_mk(code), bd, end.strftime("%Y-%m-%d")))
        rows = []
        for tr in _r.findall(r"<tr[^>]*>(.*?)</tr>", h, _r.S):
            tds = [_strip(x) for x in _r.findall(r"<td[^>]*>(.*?)</td>", tr, _r.S)]
            if len(tds) >= 3 and _r.match(r"\d{4}-\d{2}-\d{2}", tds[1] if len(tds) > 1 else ""):
                tds = tds[1:]
            if len(tds) >= 3 and _r.match(r"\d{4}-\d{2}-\d{2}$", tds[0]):
                try:
                    rows.append((tds[0], float(tds[1].replace(",", ""))))
                except Exception:
                    pass
        if not rows:
            note("两融[新浪]无表 %s 片段:%s" % (code, _strip(h)[:80]))
            return None
        rows = sorted(set(rows))[-10:]
        return rows
    except Exception as e:
        note("两融[新浪]失败 %s %s" % (code, str(e)[:50]))
        return None


def deep_industry(code):
    """所属行业/概念：新浪公司其他信息页（按表格单元格解析）"""
    import re as _r
    try:
        h = _http("https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_CorpOtherInfo/stockid/%s/menu_num/2.phtml" % code)
        cells = [_strip(x) for x in _r.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", h, _r.S)]
        cells = [x for x in cells if x]
        skip = ("板块名称", "同行业个股", "同概念个股", "点击查看", "所属行业板块", "所属概念板块", "所属系",
                "所属指数", "板块信息", "行业", "概念", "")

        def grab(mark, stops):
            out = []
            if mark not in cells:
                return out
            for x in cells[cells.index(mark) + 1:]:
                if x in stops:
                    break
                if x not in skip and not x.isdigit() and not x.startswith("备注") and len(x) <= 14 and x not in out:
                    out.append(x)
            return out[:8]
        inds = grab("所属行业板块", ("所属概念板块", "所属系", "所属指数"))
        con = grab("所属概念板块", ("所属系", "所属指数", "所属行业板块"))
        if not inds and not con:
            note("行业[新浪]解析不到 %s 单元格:%s" % (code, "|".join(cells[:14])[:120]))
        return inds, con
    except Exception as e:
        note("行业[新浪]失败 %s %s" % (code, str(e)[:50]))
        return None, None


_IDX = {}


def index_ret(sym="sh000300"):
    """指数5日/20日涨跌（相对强弱基准），腾讯K线"""
    if sym in _IDX:
        return _IDX[sym]
    try:
        import json as _j
        raw = _tx_get("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=%s,day,,,30,qfq" % sym)
        dd = _j.loads(raw)["data"][sym]
        rows = dd.get("qfqday") or dd.get("day") or []
        c = [float(r[2]) for r in rows]
        r = {"d5": (c[-1] / c[-6] - 1) * 100, "d20": (c[-1] / c[-21] - 1) * 100, "today": (c[-1] / c[-2] - 1) * 100}
    except Exception as e:
        note("指数[腾讯]失败 %s %s" % (sym, str(e)[:50]))
        r = None
    _IDX[sym] = r
    return r


def my_assets():
    """从 我的清单.txt 读 总资产/现金（万）"""
    import re as _r
    for fn in ("我的清单.txt",):
        try:
            t = open(fn, encoding="utf-8").read()
            a = _r.search(r"^账户\s*\|\s*总资产\s*\|\s*([\d.]+)", t, _r.M)
            c = _r.search(r"^账户\s*\|\s*现金\s*\|\s*([\d.]+)", t, _r.M)
            hold = _r.findall(r"^持仓\s*\|\s*(\d{6})", t, _r.M)
            return (float(a.group(1)) if a else None, float(c.group(1)) if c else None, hold)
        except Exception:
            pass
    return None, None, []


def deep_all(ak, code):
    d = {}
    for k, fn in (("val", lambda: deep_valuation(code)),
                  ("fin", lambda: deep_fin(ak, code)),
                  ("news", lambda: deep_news(code)),
                  ("unlock", lambda: deep_unlock(ak, code)),
                  ("margin", lambda: deep_margin(code)),
                  ("ind", lambda: deep_industry(code))):
        try:
            d[k] = fn()
        except Exception as e:
            d[k] = None
            note("深查%s异常 %s %s" % (k, code, str(e)[:40]))
    return d


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
        rn = os.environ.get("GITHUB_RUN_NUMBER", "")
        # 2026-10-26：#37 全部失败的结果覆盖了 #36 的好结果 → 失败时不许覆盖当天文件
        _ok = ("现价" in t)
        if rn:
            io.open(os.path.join(OUTDIR, "查询结果_q%s.txt" % rn),
                    "w", encoding="utf-8").write(t)
            print("✅ patch_query: 已写出 reports/查询结果_q%s.txt" % rn)
        io.open(os.path.join(OUTDIR, "查询结果_最新.txt"),
                "w", encoding="utf-8").write(t)
        if _ok:
            io.open(os.path.join(OUTDIR, "查询结果_%s.txt" % d),
                    "w", encoding="utf-8").write(t)
        else:
            print("🔴 patch_query: 本次全部无数据 → 不覆盖 查询结果_%s.txt（保留之前的好结果）" % d)
        print("✅ patch_query: 已写出 reports/查询结果_最新.txt")
    except Exception as e:
        print("🔴 patch_query: 写文件失败 %s" % e)


def _yi(v):
    try:
        v = float(v)
    except Exception:
        return str(v)
    return ("%.2f亿" % (v / 1e8)) if abs(v) >= 1e6 else ("%.2f" % v)


def _deep_out(w, cd, s, k, dp, ok, okb, sm, tag, hs, cy, TA, CASH, HOLD):
    """★11/03 深查输出 + 综合结论（一次查完就有结论）"""
    dp = dp or {}
    sc, veto = [], []
    pct = s.get("pct") if s else None
    last = (k or {}).get("last") or (s or {}).get("price")
    w("   ┄┄┄┄┄┄┄┄ 深查（估值/基本面/消息/解禁/两融/行业/强弱/支撑压力/仓位）┄┄┄┄┄┄┄┄")
    try:
        import re as _r
        sf = dp.get("sina_ff")
        if sf:
            vv = {}
            for x in sf:
                m_ = _r.search(r"(\d{4}-\d{2}-\d{2}).*?主力([+-]?[\d.]+)亿", str(x))
                if m_:
                    vv[m_.group(1)] = float(m_.group(2))
            if vv:
                ss = sum(vv[d] for d in sorted(vv)[-5:])
                agree = (ss > 0) == ((sm or 0) > 0)
                w("   ⓪资金交叉验证：新浪口径5日%+.2f亿 vs 东财口径%+.2f亿 → %s" % (
                    ss, sm or 0, "✅方向一致" if agree else "⚠️方向打架＝大单/超大单分歧，主力态度不明，资本视角降级为参考"))
                if not agree:
                    sm = None
                    tag = ""
    except Exception:
        pass
    if cd in (HOLD or []):
        w("   📌 已持仓")
    # ① 估值
    v = dp.get("val")
    if v:
        w("   ①估值：PE(TTM)%s ｜ PE动%s ｜ PE静%s ｜ PB %s ｜ 总市值%s亿 流通%s亿 ｜ 量比%s ｜ 振幅%s%% ｜ 涨停%s 跌停%s"
          % tuple(_f(v.get(x)) for x in ("pe", "pe_d", "pe_s", "pb", "mv", "fmv", "lb", "zf", "zt", "dt")))
        pe = v.get("pe")
        if pe is None or pe <= 0:
            sc.append(("估值", -1, "亏损/PE无效"))
        elif pe > 80:
            sc.append(("估值", -1, "PE%.0f偏贵，靠故事撑" % pe))
        elif pe < 25:
            sc.append(("估值", 1, "PE%.0f不贵" % pe))
        else:
            sc.append(("估值", 0, "PE%.0f中性" % pe))
    else:
        w("   ①估值【无数据】")
    # ② 基本面
    fin = dp.get("fin") or (None, "")
    rows, src = (fin if isinstance(fin, tuple) else (None, ""))
    if rows:
        w("   ②基本面（%s，最近5期，累计口径）：" % src)
        m = dict(rows)
        for lab, vals in rows:
            w("      %s：%s" % (lab, "  ".join("%s:%s" % (p[2:] if len(p) == 8 else p, _yi(x)) for p, x in vals)))
        try:
            ni = m.get("归母净利") or m.get("净利")
            if ni and len(ni) >= 5 and ni[0][0][4:] == ni[4][0][4:] and ni[4][1]:
                yoy = (ni[0][1] / ni[4][1] - 1) * 100 * (1 if ni[4][1] > 0 else -1)
                w("      → 净利同比 %+.1f%%（%s vs %s）" % (yoy, ni[0][0], ni[4][0]))
                sc.append(("业绩", 1 if yoy > 10 else (-1 if yoy < -10 else 0), "净利同比%+.0f%%" % yoy))
            elif m.get("净利同比"):
                y = float(str(m["净利同比"][0][1]).replace("%", ""))
                sc.append(("业绩", 1 if y > 10 else (-1 if y < -10 else 0), "净利同比%+.0f%%" % y))
            gm = m.get("毛利率")
            if gm and len(gm) >= 5 and src == "新浪":
                dg = gm[0][1] - gm[4][1]
                w("      → 毛利率同比 %+.2f个点（%.2f%%→%.2f%%）" % (dg, gm[4][1], gm[0][1]))
                if dg <= -2:
                    sc.append(("毛利", -1, "毛利率同比降%.1f点（宁德教训：降价换量）" % -dg))
                elif dg >= 1:
                    sc.append(("毛利", 1, "毛利率同比升%.1f点" % dg))
            cf = m.get("经营现金流")
            if cf and ni and src == "新浪" and ni[0][1]:
                r = cf[0][1] / ni[0][1]
                w("      → 经营现金流/净利 = %.2f（<0.5 利润含金量差）" % r)
                if r < 0.5:
                    sc.append(("现金流", -1, "现金流/净利%.2f" % r))
                elif r > 1:
                    sc.append(("现金流", 1, "现金流/净利%.2f" % r))
        except Exception as e:
            note("基本面计算异常 %s %s" % (cd, str(e)[:40]))
    else:
        w("   ②基本面【无数据】（新浪/同花顺都没取到）")
    # ③ 新闻 + 公告
    nw = dp.get("news") or (None, None)
    news, ann = nw if isinstance(nw, tuple) else (None, None)
    hard = ("减持", "立案", "处罚", "预亏", "首亏", "退市", "冻结")
    for title, lst, cap in (("③公告(近12天)", ann, 8), ("③新闻(近12天)", news, 8)):
        if lst is None:
            w("   %s【无数据】" % title)
            continue
        if not lst:
            w("   %s：无" % title)
            continue
        w("   %s：%d条" % (title, len(lst)))
        nb = ng = 0
        seen = set()
        for d, t in lst:
            if t in seen:
                continue
            seen.add(t)
            fl, b, g = _flag(t)
            nb += 1 if b else 0
            ng += 1 if g else 0
            if len(seen) <= cap:
                w("      %s %s %s" % (fl, d[5:], t[:46]))
            if "公告" in title and any(x in t for x in hard) and "完成" not in t and "结束" not in t:
                veto.append("公告风险：%s" % t[:24])
        if "公告" in title:
            if nb:
                sc.append(("公告", -1, "%d条负面公告" % nb))
            elif ng:
                sc.append(("公告", 1, "%d条正面公告" % ng))
        else:
            if nb > ng:
                sc.append(("新闻", -1, "负面%d>正面%d" % (nb, ng)))
            elif ng > nb:
                sc.append(("新闻", 1, "正面%d>负面%d" % (ng, nb)))
    # ④ 解禁
    ul = dp.get("unlock")
    if ul is None:
        w("   ④限售解禁【无数据】")
    elif not ul:
        w("   ④限售解禁：前30天~后120天 无")
    else:
        w("   ④限售解禁：" + " ｜ ".join(ul[:4]))
        _td = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d")
        if any(x[:10] >= _td for x in ul):
            sc.append(("解禁", -1, "未来120天有解禁（资本出货窗口）"))
        else:
            w("      （已过的解禁，不扣分；看解禁后资金是否承接）")
    # ⑤ 两融
    mg = dp.get("margin")
    if mg and len(mg) >= 2:
        ch = (mg[-1][1] / mg[0][1] - 1) * 100 if mg[0][1] else 0
        w("   ⑤融资余额：%s %s → %s %s（%+.1f%%，%d天）" % (mg[0][0][5:], _yi(mg[0][1]), mg[-1][0][5:], _yi(mg[-1][1]), ch, len(mg)))
        sc.append(("两融", 1 if ch > 3 else (-1 if ch < -3 else 0), "融资余额%+.1f%%" % ch))
    else:
        w("   ⑤融资余额【无数据】（非两融标的或页面取不到）")
    # ⑥ 行业概念
    ind = dp.get("ind") or (None, None)
    inds, con = ind if isinstance(ind, tuple) else (None, None)
    if inds or con:
        w("   ⑥行业：%s ｜ 概念：%s" % ("、".join(inds or []) or "—", "、".join(con or []) or "—"))
    else:
        w("   ⑥行业/概念【无数据】")
    # ⑦ 相对强弱
    if k and k.get("d20") is not None and hs:
        r5, r20 = k["d5"] - hs["d5"], k["d20"] - hs["d20"]
        t = "   ⑦相对强弱：5日%+.1f%% / 20日%+.1f%% ｜ 沪深300 5日%+.1f%% / 20日%+.1f%% → 超额 5日%+.1f / 20日%+.1f" % (
            k["d5"], k["d20"], hs["d5"], hs["d20"], r5, r20)
        if cy:
            t += " ｜ 创业板20日%+.1f%%" % cy["d20"]
        w(t)
        sc.append(("强弱", 1 if r20 > 0 else -1, "20日跑%s大盘%.1f点" % ("赢" if r20 > 0 else "输", abs(r20))))
    else:
        w("   ⑦相对强弱【无数据】")
    # ⑧ 支撑压力
    rr = None
    if k and last:
        sup, res_ = [], []
        for nm, x in (("MA5", k.get("ma5")), ("MA10", k.get("ma10")), ("MA20", k.get("ma20")), ("MA60", k.get("ma60")),
                      ("MA120", k.get("ma120")), ("布林下轨", k.get("boll_lo")), ("布林上轨", k.get("boll_hi")),
                      ("20日低", k.get("lo20")), ("20日高", k.get("hi20")), ("60日低", k.get("lo")), ("60日高", k.get("hi"))):
            if x:
                (sup if x < last else res_).append((x, nm))
        sup.sort(reverse=True)
        res_.sort()
        w("   ⑧支撑：" + " ".join("%s %.2f" % (n, x) for x, n in sup[:4]) + " ｜ 压力：" + (
            " ".join("%s %.2f" % (n, x) for x, n in res_[:4]) or "无（新高区）"))
        if k.get("ma60") and k.get("ma120"):
            w("      长周期：MA60 %.2f %s MA120 %.2f → %s" % (k["ma60"], ">" if k["ma60"] > k["ma120"] else "<", k["ma120"],
                                                         "长多排列" if last > k["ma60"] > k["ma120"] else (
                                                             "长空排列" if last < k["ma60"] < k["ma120"] else "长周期纠缠")))
        # ⑨ 止损 / 目标 / 仓位
        atr = k.get("atr")
        if atr:
            if okb:
                stop = k["lo"] * 0.97
            else:
                stop = max(last - 2 * atr, (k.get("ma20") or 0) * 0.97 if (k.get("ma20") or 0) < last else 0, k["lo"] * 0.97)
                stop = min(stop, last - 1.2 * atr)
            _rs = sorted(x for x in (k.get("hi20"), k.get("ma60"), k.get("ma120"), k.get("hi"), k.get("boll_hi"))
                         if x and x >= last * 1.03)
            tgt = _rs[0] if _rs else last + 3 * atr   # 目标=第一道≥3%的压力位（不拿60日高画大饼）
            rr = (tgt - last) / (last - stop) if last > stop else None
            w("   ⑨ATR14 %.2f(%.1f%%) ｜ 止损 %.2f(%.1f%%) ｜ 目标 %.2f(%+.1f%%，%s) ｜ 赔率 %s"
              % (atr, atr / last * 100, stop, (stop / last - 1) * 100, tgt, (tgt / last - 1) * 100,
                 "第一压力位" if _rs else "3×ATR", ("%.1f:1" % rr) if rr else "—"))
            if TA:
                risk = TA * 1e4 * 0.025
                sh = int(risk / (last - stop) / 100) * 100 if last > stop else 0
                cap = int((CASH or 0) * 1e4 / last / 100) * 100 if CASH else sh
                sh2 = min(sh, cap) if cap else sh
                w("      仓位：总资产%.2f万×2.5%%=单笔最多亏%.0f元 → 最多%d股≈%.1f万（现金%.2f万可买%d股）%s"
                  % (TA, risk, sh, sh * last / 1e4, CASH or 0, cap,
                     " ⚠️不足5万门槛＝止损太宽，等更近买点" if sh2 * last < 5e4 else ""))
                w("      建议股数：%d股≈%.1f万" % (sh2, sh2 * last / 1e4))
            if rr is not None:
                sc.append(("赔率", 1 if rr >= 2 else (-1 if rr < 1.5 else 0), "%.1f:1" % rr))
        else:
            w("   ⑨止损/仓位【无数据】（缺最高最低价）")
    # ⑩ 趋势/资金
    if ok:
        sc.append(("趋势", 2, "趋势单买点成立"))
    elif okb:
        sc.append(("超跌", 2, "超跌错杀单成立"))
    elif k and k.get("ma20"):
        sc.append(("买点", -1, "两种买点都不成立"))
        if last < k["ma20"] and k["ma20"] < k.get("ma20p", k["ma20"]):
            veto.append("在下行20日线下方且不满足超跌")
    try:
        if pct is not None and float(pct) > 4:
            veto.append("今日+%.1f%%>4%%不追" % float(pct))
    except Exception:
        pass
    if sm is not None:
        sc.append(("主力5日", 1 if sm > 0 else -1, "%+.2f亿" % sm))
        if tag.startswith("🔴派发"):
            veto.append("资本视角=派发（散户接盘）")
            sc.append(("资本视角", -2, "派发"))
        elif tag.startswith("🟢吸筹"):
            sc.append(("资本视角", 1, "吸筹"))
    # ★综合结论
    tot = sum(x[1] for x in sc)
    if veto:
        vd = "🔴不买（否决：%s）" % "；".join(veto)
    elif tot >= 4 and rr and rr >= 2:
        vd = "🟢可买"
    elif tot >= 2:
        vd = "🟡观察（分数够但赔率/买点未齐，等回踩支撑）"
    else:
        vd = "🔴不买"
    stage = ("资金方在【吸筹】阶段→可跟着埋伏" if tag.startswith("🟢吸筹") else
             "资金方在【拉升】阶段→只在回踩MA10/MA20跟，不追" if tag.startswith("🟡拉升") else
             "资金方在【派发】阶段→别当接盘侠" if tag.startswith("🔴派发") else
             "资金方在【出逃/砸盘】→等止跌信号" if tag else "资金阶段【无数据】")
    w("   ★综合结论★ %s ｜ 总分 %+d" % (vd, tot))
    w("      计分：" + " ".join("%s%+d(%s)" % (a, b, c) for a, b, c in sc))
    w("      站位：" + stage)
    w("      AI必须补完再下结论：①驱动/故事还在不在（世界新闻、美/韩/日映射）②板块处于资金方哪一步 ③下一个催化剂日期+两种结果赔率")


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

    if all(q.replace(" ", "").isdigit() and len(q.replace(" ", "")) == 6 for q in items):
        snap = {}   # ★11/03 全是代码：跳过新浪/东财快照（海外常失败白耗~100秒），直接腾讯补
    else:
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

    _miss = [c for c in stocks if c not in snap]
    if _miss:
        snap.update(_tx_quote(_miss))

    if stocks:
        w("")
        w("█" * 26)
        w("█  个 股  (%d只)" % len(stocks))
        w("█" * 26)

        def job(cd):
            k, e = kline_info(ak, cd)
            _em = fund_flow(ak, cd)
            _sn = _sina_ff(cd)
            # ★11/03 东财资金离谱值校验：五粮液日成交~18亿，东财却给出单日-69亿 → 单日主力净额绝对值>当日成交额1.5倍=脏数据，弃用
            try:
                import re as _rq
                _amt = (snap.get(cd) or {}).get("amt")
                if _em and _amt:
                    _mx = max(abs(float(_rq.search(r"主力([+-]?[\d.]+)亿", x).group(1))) for x in _em)
                    if _mx * 1e8 > 1.5 * float(_amt):
                        note("资金[东财]离谱值%.1f亿>成交额%.1f亿×1.5，弃用改新浪 %s" % (_mx, float(_amt) / 1e8, cd))
                        _em = None
            except Exception:
                pass
            dd = deep_all(ak, cd)
            dd["sina_ff"] = _sn if _em else None   # ★11/03 两个口径交叉验证（同一天东财+0.02亿 vs 新浪+10.7亿）
            return (cd, k, e, main_biz(ak, cd), _em or _sn or _tx_ff(cd), dd)

        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            res = list(ex.map(job, stocks))
        _hs = index_ret("sh000300")
        _cy = index_ret("sz399006")
        _TA, _CASH, _HOLD = my_assets()

        for cd, k, err, biz, ff, dp in res:
            ok = okb = None
            _sm = None
            _tag = ""
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
                if k.get("ma20"):
                    up = k["ma20"] > k["ma20p"]
                    above = k["last"] > k["ma20"]
                    pct = s.get("pct") if s else None
                    gate = []
                    gate.append("✅站上20日线" if above else "❌在20日线下方")
                    gate.append("✅20日线向上" if up else "❌20日线向下")
                    gate.append(("✅5日涨%.1f%%" if k["d5"] <= 15 else "❌5日涨%.1f%%>15%%") % k["d5"])
                    try:
                        gate.append(("✅今日%+.1f%%" if float(pct) <= 4 else "❌今日%+.1f%%>4%%") % float(pct))
                    except Exception:
                        pass
                    ok = above and up and k["d5"] <= 15
                    try:   # ★11/01：今日涨>4%（含涨停）= 不追，原来漏判，泸州老窖涨停也显示🟢
                        if float(pct) > 4:
                            ok = False
                    except Exception:
                        pass
                    w("   均线 MA5 %.2f ｜ MA10 %.2f ｜ MA20 %.2f(%s)" % (k["ma5"], k["ma10"], k["ma20"], "↗" if up else "↘"))
                    w("   买点关（趋势单）：" + " ".join(gate) + (" → 🟢可考虑" if ok else " → 🔴不买"))
                    # ★11/03 第二种买法：超跌错杀单（招商10/23从22.85跌到15.97、打到布林下轨，驱动VLCC运价却在60年新高——趋势关会把它挡掉）
                    try:
                        b1 = k["from_hi"] <= -25
                        b2 = k["from_lo"] <= 5 or (k.get("boll_lo") and k["last"] <= k["boll_lo"] * 1.02)
                        b3 = (k.get("volr") is not None and k["volr"] <= 1.0) or (pct is not None and float(pct) > 0)
                        bg = ["%s距60日高%.0f%%" % ("✅" if b1 else "❌", k["from_hi"]),
                              "%s贴近60日低/布林下轨(%.2f)" % ("✅" if b2 else "❌", k.get("boll_lo") or 0),
                              "%s抛压衰竭(缩量或收红)" % ("✅" if b3 else "❌")]
                        okb = b1 and b2 and b3
                        w("   超跌关（错杀单）：" + " ".join(bg) + (
                            " → 🟢可埋伏（AI须确认驱动仍在高位/改善；止损=60日低下3%%≈%.2f）" % (k["lo"] * 0.97) if okb else " → —"))
                    except Exception:
                        pass
            else:
                w("   K线位置【无数据】%s" % err)
            w("   ★主营构成★ " + (" / ".join(biz) if biz
                               else "【无数据】→ ⚠️需截 F10→简况"))
            w("   个股资金 " + (" ｜ ".join(ff) if ff
                            else "【无数据】→ ⚠️需截 F10→资金"))
            # ★11/03 资本视角：主力 vs 散户（主力净额的反面≈散户）。价涨+主力出＝派发给散户；价平/跌+主力进＝吸筹
            try:
                import re as _re_ff
                _dv = {}
                for _x in (ff or []):   # ★11/03修：不同数据源顺序相反（东财旧→新、新浪新→旧），按日期排序取最近5天
                    _m = _re_ff.search(r"(\d{4}-\d{2}-\d{2}).*?主力([+-]?[\d.]+)亿", str(_x))
                    if _m:
                        _dv[_m.group(1)] = float(_m.group(2))
                _vals = [_dv[d] for d in sorted(_dv)][-5:]
                if len(_vals) >= 3 and k and k.get("d5") is not None:
                    _sm = sum(_vals)
                    _d5 = k["d5"]
                    if _sm > 0 and _d5 <= 2:
                        _tag = "🟢吸筹（主力在买、价格没涨＝散户在卖给主力）"
                    elif _sm < 0 and _d5 >= 3:
                        _tag = "🔴派发（价格在涨、主力在卖＝散户在接盘）"
                    elif _sm > 0 and _d5 > 2:
                        _tag = "🟡拉升（主力边买边拉，留意放量滞涨＝转派发）"
                    else:
                        _tag = "⚪出逃/砸盘（主力卖、价格跌）"
                    w("   资本视角：近%d日主力合计%+.2f亿（截至%s）× 5日涨跌%+.1f%% → %s" % (len(_vals), _sm, sorted(_dv)[-1], _d5, _tag))
            except Exception:
                pass
            try:
                _deep_out(w, cd, s, k, dp, ok, okb, _sm, _tag, _hs, _cy, _TA, _CASH, _HOLD)
            except Exception as _e:
                w("   深查输出异常：%s" % str(_e)[:80])

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

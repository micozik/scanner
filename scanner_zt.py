# -*- coding: utf-8 -*-
"""
明日涨停猎手（2026-11-03 新建）
用户："明天还是有股票涨停的，既然知道这是肯定的事，你就不想找出来吗？"

涨停是资金（游资/主力）选好 题材+位置+情绪 后拉出来的。本脚本站在资金方角度：
  1. 情绪开关：昨日涨停今日表现、炸板率、跌停数 → 明天接力有没有肉
  2. 主线：今日涨停按行业扎堆 + 近3个交易日持续性
  3. 个股打分：首封时间、炸板次数、封单/流通市值、封单/成交额、连板高度、流通市值、换手率、行业集群
  4. 输出明日候选 Top8 + 明早竞价确认条件
  5. 自动对账：上一份预测今天中了几只（涨停命中率、次日平均涨幅），累计到 reports/zt_hit.json

MODE=auction（明早9:26后跑）：读最新预测，取腾讯开盘价，按竞价条件给 买/放弃。
所有分数是规则分，不是概率；概率要等命中率攒够样本再标定（铁律：不编数）。
"""
import os
import json
import time
import datetime
import traceback

OUT_DIR = "reports"
PRED_DIR = os.path.join(OUT_DIR, "zt_pred")
HIT_FILE = os.path.join(OUT_DIR, "zt_hit.json")
IND_HIST = os.path.join(OUT_DIR, "zt_ind_hist.json")
L = []
BASE = [None]


def w(s=""):
    L.append(str(s))
    print(s)


def bj_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=8)


def col(df, *names):
    for n in names:
        if n in df.columns:
            return n
    for n in names:
        for c in df.columns:
            if n in str(c):
                return c
    return None


def retry(fn, n=3, gap=4):
    err = None
    for i in range(n):
        try:
            return fn()
        except Exception as e:
            err = e
            time.sleep(gap * (i + 1))
    raise err


def fnum(x, d=None):
    try:
        v = float(x)
        return v if v == v else d
    except Exception:
        return d


def tm(s):
    """'092500' / '09:25:00' → 分钟数"""
    s = str(s).replace(":", "").zfill(6)
    try:
        return int(s[:2]) * 60 + int(s[2:4])
    except Exception:
        return None


def _tx_mk(code):
    return ("sh" if code.startswith(("6", "9")) and not code.startswith("92")
            else ("bj" if code[:2] in ("92", "83", "87", "43") else "sz")) + code


def tx_quote(codes):
    import urllib.request
    out = {}
    if not codes:
        return out
    url = "https://qt.gtimg.cn/q=" + ",".join(_tx_mk(c) for c in codes)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"})
    raw = urllib.request.urlopen(req, timeout=8).read()
    try:
        txt = raw.decode("gbk")
    except Exception:
        txt = raw.decode("utf-8", "ignore")
    for line in txt.split(";"):
        if '="' not in line:
            continue
        f = line.split('="', 1)[1].rstrip('"').split("~")
        if len(f) < 40:
            continue
        out[f[2][-6:]] = {"name": f[1], "price": fnum(f[3]), "prev": fnum(f[4]), "open": fnum(f[5]),
                          "pct": fnum(f[32]), "amt_wan": fnum(f[37]), "vol": fnum(f[6])}
    return out


def find_trade_date(ak):
    """从今天往前找有涨停池数据的交易日"""
    d = bj_now()
    if d.hour < 9 or (d.hour == 9 and d.minute < 30):
        d -= datetime.timedelta(days=1)
    for _ in range(8):
        ds = d.strftime("%Y%m%d")
        if d.weekday() < 5:
            try:
                df = retry(lambda: ak.stock_zt_pool_em(date=ds))
                if df is not None and len(df):
                    return ds, df
            except Exception as e:
                w("  [涨停池 %s 失败] %s" % (ds, str(e)[:60]))
        d -= datetime.timedelta(days=1)
    return None, None


def load_json(p, dft):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return dft


def save_json(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


# ───────────────────────── 收盘后：找明日涨停 ─────────────────────────
def run_hunt():
    import akshare as ak
    now = bj_now()
    w("=" * 64)
    w("🎯【明日涨停猎手】北京 %s" % now.strftime("%Y-%m-%d %H:%M"))
    w("   分数=规则分，不是概率；命中率见文末对账（铁律：不编数）")
    w("=" * 64)
    ds, zt = find_trade_date(ak)
    if zt is None:
        w("🔴 涨停池取不到（东财海外常断），本次无结论。")
        return
    intraday = ds == now.strftime("%Y%m%d") and now.hour < 15
    w("数据日：%s%s ｜ 涨停 %d 只" % (ds, "（⚠️盘中，未收盘，结论仅供参考）" if intraday else "", len(zt)))

    c_code, c_name = col(zt, "代码"), col(zt, "名称")
    c_ind, c_lbc = col(zt, "所属行业"), col(zt, "连板数")
    c_first, c_last = col(zt, "首次封板时间"), col(zt, "最后封板时间")
    c_zb, c_fd = col(zt, "炸板次数"), col(zt, "封板资金")
    c_mv, c_amt = col(zt, "流通市值"), col(zt, "成交额")
    c_turn, c_tj, c_px = col(zt, "换手率"), col(zt, "涨停统计"), col(zt, "最新价")

    # ── 1 情绪开关 ──
    w("")
    w("【一、情绪开关】（明天接力有没有肉）")
    mood = 0
    try:
        pv = retry(lambda: ak.stock_zt_pool_previous_em(date=ds))
        cp = col(pv, "涨跌幅")
        vals = [fnum(x) for x in pv[cp]] if cp else []
        vals = [x for x in vals if x is not None]
        if vals:
            avg = sum(vals) / len(vals)
            BASE[0] = avg   # 基准：随便买一只昨日涨停股的次日平均收益（我们的候选必须明显跑赢它）
            red = sum(1 for x in vals if x > 0) / len(vals) * 100
            w("  昨日涨停%d只 → 今日平均%+.2f%% ｜ 红盘率%.0f%%" % (len(vals), avg, red))
            mood += (1 if avg > 2 else (0 if avg > 0 else -2)) + (1 if red >= 60 else (-1 if red < 45 else 0))
    except Exception as e:
        w("  昨日涨停表现【无数据】%s" % str(e)[:50])
    try:
        zb = retry(lambda: ak.stock_zt_pool_zbgc_em(date=ds))
        nzb = len(zb) if zb is not None else 0
        rate = nzb / (nzb + len(zt)) * 100 if (nzb + len(zt)) else 0
        w("  炸板%d只 ｜ 炸板率%.0f%%（<30%%健康，>40%%接力亏钱）" % (nzb, rate))
        mood += 1 if rate < 30 else (-1 if rate > 40 else 0)
    except Exception as e:
        w("  炸板池【无数据】%s" % str(e)[:50])
    try:
        dt = retry(lambda: ak.stock_zt_pool_dtgc_em(date=ds))
        ndt = len(dt) if dt is not None else 0
        w("  跌停%d只（>20只=亏钱效应）" % ndt)
        mood += -1 if ndt > 20 else (1 if ndt < 8 else 0)
    except Exception as e:
        w("  跌停池【无数据】%s" % str(e)[:50])
    try:
        mx = int(max(fnum(x, 0) for x in zt[c_lbc])) if c_lbc else 0
        w("  最高连板 %d 板（空间高度）" % mx)
        mood += 1 if mx >= 5 else 0
    except Exception:
        pass
    gate = "🟢开（接力有肉）" if mood >= 2 else ("🟡中性（只做最强）" if mood >= 0 else "🔴关（明天不接力，只看不买）")
    w("  → 情绪分 %+d ｜ 接力开关：%s" % (mood, gate))

    # ── 2 主线 ──
    w("")
    w("【二、主线】（今日涨停按行业 + 近3个交易日持续性）")
    ind_cnt = {}
    if c_ind:
        for v in zt[c_ind]:
            ind_cnt[str(v)] = ind_cnt.get(str(v), 0) + 1
    hist = load_json(IND_HIST, {})
    if not intraday:
        hist[ds] = ind_cnt
        save_json(IND_HIST, dict(sorted(hist.items())[-30:]))
    # 历史不足2天：直接回拉前几个交易日的涨停池补齐（首次上线时库是空的）
    try:
        dd = datetime.datetime.strptime(ds, "%Y%m%d")
        got = 0
        for _ in range(7):
            dd -= datetime.timedelta(days=1)
            k = dd.strftime("%Y%m%d")
            if dd.weekday() >= 5:
                continue
            if k not in hist:
                try:
                    pz = retry(lambda: ak.stock_zt_pool_em(date=k), n=2)
                    ci = col(pz, "所属行业") if pz is not None and len(pz) else None
                    if ci:
                        cnt = {}
                        for v in pz[ci]:
                            cnt[str(v)] = cnt.get(str(v), 0) + 1
                        hist[k] = cnt
                except Exception:
                    pass
            if k in hist:
                got += 1
            if got >= 2:
                break
        save_json(IND_HIST, dict(sorted(hist.items())[-30:]))
    except Exception:
        pass
    prev_days = [k for k in sorted(hist) if k < ds][-2:]
    w("  （对比日：%s）" % "、".join(prev_days))
    main = {}
    for k, v in sorted(ind_cnt.items(), key=lambda x: -x[1])[:10]:
        streak = sum(1 for d in prev_days if hist.get(d, {}).get(k, 0) >= 2)
        main[k] = (v, streak)
        w("  %-8s 今日%2d只 ｜ 前2日≥2只的天数 %d %s" % (k, v, streak,
                                                    "← 持续主线" if streak >= 1 and v >= 3 else ""))

    # ── 3 个股打分 ──
    rows = []
    for _, r in zt.iterrows():
        code = str(r[c_code]).zfill(6)
        name = str(r[c_name])
        if "ST" in name or name[:1] in ("N", "C") or code[:2] in ("92", "83", "87", "43"):
            continue
        sc, why = 0, []
        ft = tm(r[c_first]) if c_first else None
        lt = tm(r[c_last]) if c_last else None
        mv = fnum(r[c_mv]) if c_mv else None
        fd = fnum(r[c_fd]) if c_fd else None
        amt = fnum(r[c_amt]) if c_amt else None
        turn = fnum(r[c_turn]) if c_turn else None
        zbn = int(fnum(r[c_zb], 0)) if c_zb else 0
        lb = int(fnum(r[c_lbc], 1)) if c_lbc else 1
        ind = str(r[c_ind]) if c_ind else ""
        yizi = ft is not None and ft <= 9 * 60 + 25 and (turn or 0) < 1.5
        if ft is not None:
            if ft <= 9 * 60 + 35:
                sc += 3; why.append("早盘秒封")
            elif ft <= 10 * 60:
                sc += 2; why.append("10点前封")
            elif ft <= 11 * 60 + 30:
                sc += 1; why.append("上午封")
            elif ft >= 14 * 60:
                sc -= 2; why.append("尾盘封(弱)")
        if lt is not None and lt >= 14 * 60 + 30 and zbn:
            sc -= 1; why.append("尾盘才回封")
        sc += 2 if zbn == 0 else (0 if zbn == 1 else -2)
        why.append("未炸板" if zbn == 0 else "炸%d次" % zbn)
        if fd and mv:
            fr = fd / mv * 100
            sc += 3 if fr >= 3 else (2 if fr >= 1 else (1 if fr >= 0.5 else 0))
            why.append("封单/流通%.1f%%" % fr)
        if fd and amt and fd >= amt:
            sc += 1; why.append("封单>成交额")
        n_ind, stk = main.get(ind, (ind_cnt.get(ind, 0), 0))
        sc += 3 if n_ind >= 5 else (2 if n_ind >= 3 else (1 if n_ind >= 2 else -1))
        why.append("%s涨停%d只" % (ind, n_ind))
        if stk >= 1 and n_ind >= 3:
            sc += 1; why.append("持续主线")
        sc += {1: 0, 2: 2, 3: 2, 4: 1}.get(lb, 0)
        why.append("%d板" % lb)
        if mv:
            yi = mv / 1e8
            sc += 1 if 20 <= yi <= 150 else (-1 if yi > 500 else 0)
            why.append("流通%.0f亿" % yi)
        if turn is not None:
            sc += 1 if 3 <= turn <= 20 else (-1 if turn > 30 else 0)
            why.append("换手%.1f%%" % turn)
        rows.append({"code": code, "name": name, "ind": ind, "lb": lb, "score": sc, "yizi": yizi,
                     "px": fnum(r[c_px]) if c_px else None, "why": " ".join(why)})
    rows.sort(key=lambda x: -x["score"])
    trad = [x for x in rows if not x["yizi"]]
    top = trad[:8]
    w("")
    w("【三、明日涨停候选 Top8】（剔除ST/新股/北交所/一字板买不到的）")
    for i, x in enumerate(top, 1):
        w("  %d. %s(%s) %s ｜ 分%+d ｜ %s" % (i, x["name"], x["code"], x["ind"], x["score"], x["why"]))
    yz = [x for x in rows if x["yizi"]][:5]
    if yz:
        w("  （一字板，明天大概率还强但散户买不到：%s）" % "、".join("%s%d板" % (x["name"], x["lb"]) for x in yz))
    w("")
    w("【四、明早竞价确认（9:25后，MODE=auction 自动判）】")
    w("  买：高开 +2%~+6%（主板）/ +3%~+9%（20cm），且所在行业至少2只同样高开")
    w("  放弃：低开或平开（资金没接力）、高开>7%（一致性太强易炸）、情绪开关🔴")
    w("  止损：开盘买入后跌破昨日收盘价（涨停价）−3% 即走；不隔夜死扛")
    w("  ⚠️ 这是投机仓（接力单D），必须先过七关⑤查股票；接力开关🔴时一律只看不买")
    w("  " + ",".join(x["code"] for x in top))

    # ── 5 对账 ──
    w("")
    w("【五、对账】（上一份预测 → 今天兑现）")
    try:
        files = sorted(f for f in os.listdir(PRED_DIR) if f.endswith(".json")) if os.path.isdir(PRED_DIR) else []
        prevf = [f for f in files if f[:8] < ds]
        hits = load_json(HIT_FILE, {})
        if prevf and not intraday:
            pd = load_json(os.path.join(PRED_DIR, prevf[-1]), {})
            codes = [x["code"] for x in pd.get("top", [])]
            zt_codes = set(str(x).zfill(6) for x in zt[c_code])
            pct_map = {}
            try:
                pv = retry(lambda: ak.stock_zt_pool_previous_em(date=ds))
                for _, r in pv.iterrows():
                    pct_map[str(r[col(pv, "代码")]).zfill(6)] = fnum(r[col(pv, "涨跌幅")])
            except Exception:
                pass
            h = [c for c in codes if c in zt_codes]
            pcs = [pct_map[c] for c in codes if pct_map.get(c) is not None]
            hits[ds] = {"pred_from": prevf[-1][:8], "n": len(codes), "hit": len(h), "hit_codes": h, "base_avg": BASE[0],
                        "avg_pct": (sum(pcs) / len(pcs)) if pcs else None}
            save_json(HIT_FILE, hits)
            w("  %s预测%d只 → 今日涨停%d只 %s ｜ 今日平均涨幅%s" % (
                prevf[-1][:8], len(codes), len(h), "、".join(h),
                ("%+.2f%%" % hits[ds]["avg_pct"]) if hits[ds]["avg_pct"] is not None else "【无数据】"))
        tot_n = sum(v["n"] for v in hits.values())
        tot_h = sum(v["hit"] for v in hits.values())
        aps = [v["avg_pct"] for v in hits.values() if v.get("avg_pct") is not None]
        if tot_n:
            w("  累计：%d天 %d只 命中%d只 命中率%.0f%% ｜ 次日平均涨幅%s" % (
                len(hits), tot_n, tot_h, tot_h / tot_n * 100,
                ("%+.2f%%" % (sum(aps) / len(aps))) if aps else "—"))
            if len(hits) < 10:
                w("  （涨停命中率只是辅助；真正成绩看《选股命中率》里的模拟交易：胜率/每笔平均/盈亏比）")
        else:
            w("  首次运行，明天开始对账")
    except Exception as e:
        w("  对账异常 %s" % str(e)[:60])
    if not intraday:
        save_json(os.path.join(PRED_DIR, ds + ".json"),
                  {"date": ds, "mood": mood, "gate": gate, "top": top, "made": now.strftime("%Y-%m-%d %H:%M")})


# ───────────────────────── 明早：竞价确认 ─────────────────────────
def run_auction():
    now = bj_now()
    w("=" * 64)
    w("⏰【涨停猎手·竞价确认】北京 %s" % now.strftime("%Y-%m-%d %H:%M"))
    w("=" * 64)
    files = sorted(f for f in os.listdir(PRED_DIR) if f.endswith(".json")) if os.path.isdir(PRED_DIR) else []
    if not files:
        w("🔴 没有预测文件")
        return
    pd = load_json(os.path.join(PRED_DIR, files[-1]), {})
    top = pd.get("top", [])
    w("预测来源：%s ｜ 情绪开关：%s" % (pd.get("date"), pd.get("gate")))
    q = tx_quote([x["code"] for x in top])
    ok_ind = {}
    res = []
    for x in top:
        d = q.get(x["code"], {})
        op, pv = d.get("open"), d.get("prev")
        gap = (op / pv - 1) * 100 if op and pv else None
        res.append((x, d, gap))
        if gap is not None and gap >= 2:
            ok_ind[x["ind"]] = ok_ind.get(x["ind"], 0) + 1
    for x, d, gap in res:
        big = x["code"].startswith(("30", "68"))
        lo, hi = (3, 9) if big else (2, 6)
        if gap is None:
            v = "【无数据】"
        elif "🔴" in str(pd.get("gate")):
            v = "放弃（情绪开关关）"
        elif gap < lo:
            v = "放弃（高开不足，资金没接）"
        elif gap > (hi + 1):
            v = "放弃（高开过猛易炸）"
        elif ok_ind.get(x["ind"], 0) < 2:
            v = "🟡观察（同行业没有第2只跟）"
        else:
            v = "🟢可买（须过七关⑤查股票），止损=昨收×0.97=%.2f" % (d.get("prev", 0) * 0.97)
        w("  %s(%s) %s ｜ 开盘%s 高开%s ｜ 现%s → %s" % (
            x["name"], x["code"], x["ind"], d.get("open"), ("%+.1f%%" % gap) if gap is not None else "—",
            d.get("price"), v))


def main():
    mode = os.environ.get("MODE", "hunt").strip() or "hunt"
    try:
        run_auction() if mode == "auction" else run_hunt()
    except Exception:
        w("🔴 异常：" + traceback.format_exc()[-400:])
    os.makedirs(OUT_DIR, exist_ok=True)
    tag = "竞价" if mode == "auction" else "猎手"
    fn = os.path.join(OUT_DIR, "涨停%s_%s.txt" % (tag, bj_now().strftime("%Y%m%d_%H%M")))
    with open(fn, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    with open(os.path.join(OUT_DIR, "涨停%s_最新.txt" % tag), "w", encoding="utf-8") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    main()

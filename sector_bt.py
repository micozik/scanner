# -*- coding: utf-8 -*-
"""
板块轮动回测（2026-11-10 新建，用户："真的很难，你必须要找到突破口"）

背景：backtest.py / factor_search.py（11/03）已证明——纯个股价格形态规则在样本外几乎没有优势
（检验段胜率≈50%、每笔≈0%）。所以我们选股"十次错六次"不是运气，是方法本身没有边际。
这里检验我们真正信的东西：资金在板块之间搬家（抢先理念：量先价后；启动第1天；不追连涨3天）。

数据：东财行业板块日K（akshare stock_board_industry_hist_em），约2.5年；沪深300（腾讯日K）做大盘环境。
规则：D日收盘出信号 → D+1开盘买 → 持有H天收盘卖（H=3/5/10），双边成本0.2%。
对比：同一天"全部板块平均"的同期收益（基准）。样本切分：前60%时间=训练，后40%=检验。
合格：检验段 胜率≥55% 且 每笔超额≥+0.5% 且 训练段同向——才算"有边际"。
所有数字是历史统计，不是承诺。
"""
import os, json, time, datetime, urllib.request
import statistics as st

L = []
def w(s=""):
    L.append(str(s)); print(s)

COST = 0.2
HOLDS = [3, 5, 10]
START = os.environ.get("BT_START", "20240301")
END = datetime.datetime.utcnow().strftime("%Y%m%d")


def hs300():
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh000300,day,,,700,qfq"
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"})
            d = json.loads(urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "ignore"))["data"]["sh000300"]
            rows = d.get("qfqday") or d.get("day") or []
            return {r[0]: float(r[2]) for r in rows}
        except Exception:
            time.sleep(1 + i)
    return {}


def load_sectors():
    import akshare as ak
    names = []
    for i in range(3):
        try:
            df = ak.stock_board_industry_name_em()
            names = list(df["板块名称"])
            break
        except Exception as e:
            w(f"  板块列表失败{i+1}：{type(e).__name__}"); time.sleep(3)
    data = {}
    for n in names:
        for i in range(3):
            try:
                df = ak.stock_board_industry_hist_em(symbol=n, start_date=START, end_date=END, period="日k", adjust="")
                rows = []
                for _, r in df.iterrows():
                    rows.append({"d": str(r["日期"])[:10], "o": float(r["开盘"]), "c": float(r["收盘"]),
                                 "a": float(r["成交额"])})
                if len(rows) > 120:
                    data[n] = rows
                break
            except Exception:
                time.sleep(1.5 + i)
        time.sleep(0.25)
    return data


def main():
    t0 = time.time()
    w("=" * 70)
    w("🧭【板块轮动回测】北京 %s ｜ 持有3/5/10天 ｜ 成本0.2%%" %
      (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M"))
    w("=" * 70)
    data = load_sectors()
    if len(data) < 30:
        w(f"⚠️ 板块数据不足（{len(data)}个），终止"); return
    days = sorted({r["d"] for rows in data.values() for r in rows})
    idx = {n: {r["d"]: k for k, r in enumerate(rows)} for n, rows in data.items()}
    h3 = hs300()
    h3d = sorted(h3)
    def strong(d):  # 沪深300在60日线上
        ks = [x for x in h3d if x <= d][-60:]
        if len(ks) < 60: return None
        return h3[ks[-1]] >= sum(h3[x] for x in ks) / 60
    split = days[int(len(days) * 0.6)]
    w(f"板块数：{len(data)} ｜ 交易日：{days[0]} → {days[-1]}（{len(days)}天）｜ 训练/检验分界：{split}")

    # 预计算每个板块每天的特征
    feat = {}
    for n, rows in data.items():
        for k in range(60, len(rows)):
            c = rows[k]["c"]
            r1 = (c / rows[k-1]["c"] - 1) * 100
            r3 = (c / rows[k-3]["c"] - 1) * 100
            r5 = (c / rows[k-5]["c"] - 1) * 100
            r20 = (c / rows[k-20]["c"] - 1) * 100
            a5 = sum(x["a"] for x in rows[k-4:k+1]) / 5
            a60 = sum(x["a"] for x in rows[k-59:k+1]) / 60
            up3 = all(rows[k-j]["c"] > rows[k-j-1]["c"] for j in range(3))
            ma20 = sum(x["c"] for x in rows[k-19:k+1]) / 20
            feat[(n, rows[k]["d"])] = dict(r1=r1, r3=r3, r5=r5, r20=r20, ar=a5 / a60 if a60 else 0,
                                            up3=up3, above20=c >= ma20)

    def fwd(n, d, H):
        k = idx[n].get(d)
        rows = data[n]
        if k is None or k + 1 + H - 1 >= len(rows): return None
        o = rows[k+1]["o"]; c = rows[k+H]["c"]
        return (c / o - 1) * 100 - COST

    # 每天的基准：所有板块平均前向收益
    bench = {}
    for H in HOLDS:
        for d in days:
            v = [fwd(n, d, H) for n in data if (n, d) in feat]
            v = [x for x in v if x is not None]
            if len(v) >= 20: bench[(d, H)] = sum(v) / len(v)

    def rank_top(d, key, k=3, rev=True, cond=None):
        c = [(n, feat[(n, d)]) for n in data if (n, d) in feat and (cond is None or cond(feat[(n, d)]))]
        c.sort(key=lambda x: x[1][key], reverse=rev)
        return [n for n, _ in c[:k]]

    S = {
        "M1 5日动量前3": lambda d: rank_top(d, "r5"),
        "M2 20日动量前3": lambda d: rank_top(d, "r20"),
        "R1 20日最弱3个(反转)": lambda d: rank_top(d, "r20", rev=False),
        "Q1 抢先:量先价后(量比≥1.3,5日−3~+3%,20日≤0)": lambda d: [n for n in data if (n, d) in feat and
            feat[(n, d)]["ar"] >= 1.3 and -3 <= feat[(n, d)]["r5"] <= 3 and feat[(n, d)]["r20"] <= 0],
        "Q2 抢先+今日收红": lambda d: [n for n in data if (n, d) in feat and feat[(n, d)]["ar"] >= 1.3 and
            -3 <= feat[(n, d)]["r5"] <= 3 and feat[(n, d)]["r20"] <= 0 and feat[(n, d)]["r1"] > 0],
        "B1 启动第1天(今日涨幅前3且20日≤0)": lambda d: rank_top(d, "r1", cond=lambda f: f["r20"] <= 0),
        "B2 启动第1天+放量(量比≥1.3)": lambda d: rank_top(d, "r1", cond=lambda f: f["r20"] <= 0 and f["ar"] >= 1.3),
        "C1 追连涨3天(3日>5%)": lambda d: [n for n in data if (n, d) in feat and feat[(n, d)]["up3"] and feat[(n, d)]["r3"] > 5],
        "T1 站上20日线+5日动量前3": lambda d: rank_top(d, "r5", cond=lambda f: f["above20"]),
    }

    res = {}
    for name, fn in S.items():
        for H in HOLDS:
            rec = {"tr": [], "te": [], "trs": [], "tes": [], "trw": [], "tew": []}
            for d in days:
                if (d, H) not in bench: continue
                picks = fn(d)
                for n in picks:
                    r = fwd(n, d, H)
                    if r is None: continue
                    ex = r - bench[(d, H)]
                    seg = "te" if d >= split else "tr"
                    rec[seg].append(ex)
                    sg = strong(d)
                    if sg is not None:
                        rec[seg + ("s" if sg else "w")].append(ex)
            res[(name, H)] = rec

    def fmt(v):
        if len(v) < 30: return "   样本不足"
        return "%5d笔 胜%3d%% 超额%+.2f%%" % (len(v), round(100 * sum(1 for x in v if x > 0) / len(v)), sum(v) / len(v))

    w("\n说明：'超额'=该策略每笔收益 − 同日全部板块平均；'胜'=跑赢平均的比例。检验段才是真本事。")
    good = []
    for H in HOLDS:
        w(f"\n—— 持有{H}天 ——")
        w("  %-40s %-28s %-28s" % ("策略", "训练段", "★检验段"))
        for name in S:
            r = res[(name, H)]
            w("  %-40s %-28s %-28s" % (name[:40], fmt(r["tr"]), fmt(r["te"])))
            if len(r["te"]) >= 30 and len(r["tr"]) >= 30:
                te_m = sum(r["te"]) / len(r["te"]); tr_m = sum(r["tr"]) / len(r["tr"])
                te_w = sum(1 for x in r["te"] if x > 0) / len(r["te"])
                if te_m >= 0.5 and te_w >= 0.55 and tr_m > 0:
                    good.append((name, H, te_m, te_w))
            w("     └ 检验段 强市：%s ｜ 弱市：%s" % (fmt(r["tes"]), fmt(r["tew"])))
    w("\n" + "=" * 70)
    if good:
        w("✅ 样本外仍有效（检验段胜≥55%且超额≥+0.5%、训练段同向）：")
        for name, H, m, wr in sorted(good, key=lambda x: -x[2]):
            w(f"   {name} ｜ 持有{H}天 ｜ 检验段超额{m:+.2f}% 胜{wr*100:.0f}%")
    else:
        w("❌ 没有一条板块规则在样本外站得住 → 不能把它当买入依据")
    # ===== 今日信号（最后一个交易日）=====
    last = days[-1]
    sg = strong(last)
    w("\n" + "=" * 70)
    w(f"📍今日（{last}）信号 ｜ 大盘环境：沪深300 {'在60日线上=强市' if sg else ('在60日线下=弱市' if sg is not None else '未知')}")
    ks = [x for x in h3d if x <= last][-60:]
    if len(ks) == 60:
        w(f"   沪深300 {h3[ks[-1]]:.2f} ｜ MA60 {sum(h3[x] for x in ks)/60:.2f}")
    for name in ["M2 20日动量前3", "R1 20日最弱3个(反转)", "M1 5日动量前3"]:
        picks = S[name](last)
        w(f"   {name}：" + "、".join(f"{n}(20日{feat[(n,last)]['r20']:+.1f}% 5日{feat[(n,last)]['r5']:+.1f}%)" for n in picks))
    top10 = rank_top(last, "r20", k=10)
    w("   20日动量前10：" + "、".join(f"{n}{feat[(n,last)]['r20']:+.1f}%" for n in top10))
    w(f"耗时 {time.time()-t0:.0f} 秒")
    os.makedirs("reports", exist_ok=True)
    open("reports/板块回测.txt", "w", encoding="utf-8").write("\n".join(L))


if __name__ == "__main__":
    main()

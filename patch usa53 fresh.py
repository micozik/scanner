# -*- coding: utf-8 -*-
"""
patch_usa53_fresh.py —— 美股扫描器：根治【美股数据串日】

2026-10-21 事故（us138 / r891）：
  报告 07:19 生成，美股 10/20 早已收盘，但：
    · 四大指数全是 10/19 的（⚠️距今2天）
    · 27 只个股一半 10/19、一半 10/20，混在同一张表里
    · us_quote.json 原样写进去 → A股【美股联动核对】说『存储 美+2.04% 同向联动』
      实际 10/20 存储是跌的（海力士跌超2%、美光-0.98%）——方向反了
  根因：日K接口（index_us_stock_sina / stock_us_daily / stock_us_hist）
        在北京早上还没结算最新一根；全量快照四源又全挂。

修法（三层）：
  ① 新增【新浪实时报价 gb_】作为第一数据源：一次请求拿全部个股+指数，
     自带最新成交时间 → 换算出真实交易日
  ② 指数同样先走新浪实时，失败才退回日K
  ③ ★同日闸门★：所有个股按交易日对齐，取最新交易日为准，
     日期落后的票【踢出 us_quote.json】，宁可报空不报错，
     报告里逐只列出被踢的票
"""
import io
import os
import sys

MARK = "patch_usa53_fresh"
path = next((c for c in ["scanner_usa.py", "scanner_usa__1_.py"] if os.path.exists(c)), None)
if path is None:
    print("跳过 patch_usa53：找不到 scanner_usa.py")
    sys.exit(0)

s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch_usa53 已打过，跳过（幂等）")
    sys.exit(0)

# ── 锚点 ──
A1 = "US_SPOT_DATE = {}  # tk -> 'YYYY-MM-DD' 真实交易日（非今天）"
A2 = ('    for fname in ("stock_us_spot_em", "stock_us_spot", "stock_us_famous_spot_em",\n'
      '                  "stock_us_pink_spot_em"):')
A3 = "        for name, sym in US_INDEX:"
A4 = "    scan_stocks()\n"
for i, a in enumerate((A1, A2, A3, A4), 1):
    if s.count(a) != 1:
        print(f"!! patch_usa53 中止：锚点{i} 命中 {s.count(a)} 次（需要先打 patch12）")
        sys.exit(0)

FUNCS = r'''
# ===== @@MARK@@：新浪实时报价 + 同日闸门 =====
P53_INDEX_SINA = [("道琼斯", "$dji"), ("纳斯达克", "$ixic"), ("标普500", "$inx"),
                  ("费城半导体", "$sox")]
P53_DROPPED = []


def _p53_session_date(ts):
    """新浪时间戳 → 美股真实交易日。
    北京时间早上(<12点)看到的价 = 前一个美国交易日的收盘；
    中午以后(含美东时间写法)就是当天。周末往前推到周五。"""
    try:
        dt = datetime.datetime.strptime(str(ts).strip()[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        try:
            dt = datetime.datetime.strptime(str(ts).strip()[:10], "%Y-%m-%d")
            dt = dt.replace(hour=12)
        except Exception:
            return None
    d = dt.date() - datetime.timedelta(days=1) if dt.hour < 12 else dt.date()
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _p53_sina(codes):
    """批量抓新浪美股实时：codes 形如 ['nvda', '$dji']
    返回 {code: (价格, 涨跌幅%, 交易日)}，失败返回 {}"""
    import re as _re
    try:
        import requests as _rq
    except Exception:
        return {}
    out = {}
    for i in range(0, len(codes), 40):
        part = codes[i:i + 40]
        url = "https://hq.sinajs.cn/list=" + ",".join("gb_" + c for c in part)
        try:
            r = _rq.get(url, timeout=15, headers={
                "Referer": "https://finance.sina.com.cn",
                "User-Agent": "Mozilla/5.0"})
            r.encoding = "gbk"
            txt = r.text
        except Exception:
            continue
        for m in _re.finditer(r'hq_str_gb_([^=]+)="([^"]*)"', txt):
            code, body = m.group(1), m.group(2)
            f = body.split(",")
            if len(f) < 4:
                continue
            try:
                px = float(f[1])
                pct = float(f[2])
            except Exception:
                continue
            if px <= 0 or abs(pct) > 60:
                continue
            d = _p53_session_date(f[3])
            if d:
                out[code.lower()] = (px, pct, d)
    return out


def _p53_spot():
    """个股：新浪实时 → spot_map {TK: (价, 涨跌幅)}，同时写 US_SPOT_DATE"""
    m = {}
    want = {}
    for _cn, tk in US_TICKERS:
        want[tk.lower()] = tk.upper()
        want[tk.lower().replace(".", "")] = tk.upper()
    got = _p53_sina(sorted(set(want)))
    for code, (px, pct, d) in got.items():
        tk = want.get(code)
        if not tk or tk in m:
            continue
        m[tk] = (px, pct)
        US_SPOT_DATE[tk] = d
    return m


def _p53_index():
    """指数：新浪实时。返回已写出的指数名集合；没拿到的交给下面日K兜底"""
    got = _p53_sina([c for _, c in P53_INDEX_SINA])
    done = set()
    if not got:
        return done
    w("  （实时指数源：新浪 gb_ 实时报价 · patch_usa53；缺的用日K补，日K会标⚠️距今N天）")
    for name, c in P53_INDEX_SINA:
        v = got.get(c)
        if v:
            w(f"    {name}：{v[0]} {v[1]:+.2f}%  [{v[2]}]{_stale_tag(v[2])}")
            done.add(name)
    return done


def _p53_session_guard():
    """★同日闸门★：US_QUOTE 里日期落后于最新交易日的票全部踢掉"""
    try:
        if not US_QUOTE:
            return
        dates = [v[2] for v in US_QUOTE.values() if len(v) > 2 and v[2]]
        if not dates:
            return
        latest = max(dates)
        for tk in list(US_QUOTE.keys()):
            d = US_QUOTE[tk][2] if len(US_QUOTE[tk]) > 2 else ""
            if d != latest:
                P53_DROPPED.append((tk, d, US_QUOTE[tk][0]))
                del US_QUOTE[tk]
        w("")
        w(f"  ★【同日闸门 · patch_usa53】最新美股交易日 = {latest}")
        if P53_DROPPED:
            w(f"  🔴 以下 {len(P53_DROPPED)} 只是旧日数据，已踢出联动表（宁可报空不报错）：")
            w("     " + "、".join(f"{tk}[{d}]" for tk, d, _ in P53_DROPPED))
            w("     ★它们的真实涨跌看【新闻】一节，别用上面那张表的数")
        else:
            w(f"  ✅ {len(US_QUOTE)} 只全部是 {latest} 的数据，可直接用")
    except Exception as e:
        w(f"  [patch_usa53] 同日闸门失败：{type(e).__name__}: {e}")
# ===== @@MARK@@ 结束 =====
'''.replace("@@MARK@@", MARK)

s = s.replace(A1, A1 + "\n" + FUNCS, 1)

s = s.replace(A2,
    "    # ★@@MARK@@：新浪实时第一优先★\n"
    "    try:\n"
    "        _m53 = _p53_spot()\n"
    "        if len(_m53) >= max(5, len(US_TICKERS) // 2):\n"
    "            w(f\"  ✅ 实时行情源：新浪 gb_（{len(_m53)}/{len(US_TICKERS)}只，带真实交易日）\")\n"
    "            return _m53\n"
    "        w(f\"  [切换] 新浪实时只拿到{len(_m53)}只，换下一个源\")\n"
    "    except Exception as _e53:\n"
    "        w(f\"  [切换] 新浪实时失败({type(_e53).__name__})\")\n".replace("@@MARK@@", MARK)
    + A2, 1)

s = s.replace(A3,
    "        # ★@@MARK@@：指数先走新浪实时，日K只补缺的★\n"
    "        try:\n"
    "            _done53 = _p53_index()\n"
    "        except Exception:\n"
    "            _done53 = set()\n".replace("@@MARK@@", MARK)
    + A3 + "\n            if name in _done53:\n                continue", 1)

s = s.replace(A4, A4 + "    _p53_session_guard()  # ★" + MARK + "\n", 1)

io.open(path, "w", encoding="utf-8").write(s)
print("OK: patch_usa53 已打上 —— 新浪实时第一源 + 指数实时 + 同日闸门 → " + path)

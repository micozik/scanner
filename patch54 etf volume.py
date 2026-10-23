# -*- coding: utf-8 -*-
"""
patch54_etf_volume.py —— 【国家队雷达·宽基ETF成交额】
2026-10-23 用户截图抓到我漏的：创业板ETF易方达(159915)成交195亿，
  创924行情以来最高（前高2024-10-08 474亿、10-09 385亿）；
  沪深300ETF华泰柏瑞、科创50ETF华夏同日均超150亿。
  我只报了『净流入约90亿』，漏了『成交额创纪录』这个最硬的国家队信号。
做法（全自动）：
  ① 8只宽基ETF逐只取日K（腾讯K线 → 失败再用 akshare 东财），算今日成交额；
  ② 对比近250日最高、近20日均值；创一年新高或≥3倍均量 → 报警；
  ③ 结合位置判读：低位巨量=托底/投降（底部特征）；高位巨量=警惕924式见顶
     （2024-10-08 创业板ETF 474亿当天就是那一轮的顶）；
  ④ 每日存 reports/etf_amt_hist.json，数据源全挂时至少还有历史可比。
  插在【今日硬线索】正上方（报告第一屏）。
"""
import io, os, sys
MARK = "patch54_etf_volume"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch54 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch54 已打过"); sys.exit(0)

D = '''    os.makedirs("reports", exist_ok=True)
    text = "\\n".join(REPORT)'''
if s.count(D) != 1:
    print("!! patch54 中止：报告写出锚点命中 %d 次" % s.count(D)); sys.exit(0)

NEW = r'''    # ===== @@MARK@@：国家队雷达·宽基ETF成交额 =====
    try:
        import json as _j54, urllib.request as _u54, datetime as _d54
        _ETF54 = [("sz159915", "创业板ETF易方达"), ("sh588000", "科创50ETF华夏"),
                  ("sh510300", "沪深300ETF华泰柏瑞"), ("sh510310", "沪深300ETF易方达"),
                  ("sz159919", "沪深300ETF嘉实"), ("sh510050", "上证50ETF华夏"),
                  ("sh510500", "中证500ETF南方"), ("sh512100", "中证1000ETF南方")]

        def _tx54(code):
            url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=%s,day,,,260,"
                   % code)
            req = _u54.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            raw = _u54.urlopen(req, timeout=8).read().decode("utf-8", "ignore")
            d = _j54.loads(raw)["data"][code]
            rows = d.get("day") or d.get("qfqday") or []
            out = []
            for r in rows:
                try:   # [日期, 开, 收, 高, 低, 量(手)]
                    out.append((str(r[0]), float(r[2]), float(r[5]) * 100 * float(r[2])))
                except Exception:
                    continue
            return out

        def _em54(code):
            df = ak.fund_etf_hist_em(symbol=code[2:], period="daily",
                                     start_date=(_d54.date.today() - _d54.timedelta(days=400)).strftime("%Y%m%d"),
                                     end_date=_d54.date.today().strftime("%Y%m%d"), adjust="")
            cd, cc, ca = pick_col(df, ["日期"]), pick_col(df, ["收盘"]), pick_col(df, ["成交额"])
            return [(str(r[cd])[:10], float(r[cc]), float(r[ca])) for _, r in df.iterrows()]

        _hp54 = "reports/etf_amt_hist.json"
        try:
            _hist54 = _j54.load(open(_hp54, encoding="utf-8"))
        except Exception:
            _hist54 = {}

        _L54 = ["", "=" * 60,
                "🏛️🏛️【国家队雷达·宽基ETF成交额】创纪录=大资金进场的最硬证据 🏛️🏛️",
                "=" * 60]
        _alarm54 = []
        for _code, _nm in _ETF54:
            _rows, _src = [], ""
            for _fn, _tag in ((_tx54, "腾讯"), (_em54, "东财")):
                try:
                    _rows = _fn(_code)
                    if len(_rows) >= 21:
                        _src = _tag
                        break
                except Exception:
                    _rows = []
            if len(_rows) < 21:
                _old = _hist54.get(_code, {})
                _L54.append(f"  {_nm}({_code[2:]}) 【无数据】两源均失败"
                            + (f"，历史库{len(_old)}天" if _old else ""))
                continue
            _dt, _px, _amt = _rows[-1]
            _prev = [a for _, _, a in _rows[:-1]]
            _max250 = max(_prev[-250:])
            _avg20 = sum(_prev[-20:]) / 20.0
            _ratio = _amt / _avg20 if _avg20 else 0
            _pxs = [p for _, p, _ in _rows]
            _hi120 = max(_pxs[-120:])
            _off = (_px / _hi120 - 1) * 100 if _hi120 else 0
            _chg = (_px / _rows[-2][1] - 1) * 100 if _rows[-2][1] else 0
            _hist54.setdefault(_code, {})[_dt] = round(_amt / 1e8, 2)
            _tag54 = ""
            if _amt >= _max250:
                _tag54 = "🚨创一年新高"
            elif _ratio >= 3:
                _tag54 = "🔥放量%.1f倍" % _ratio
            _L54.append(f"  {_nm}({_code[2:]}) 成交{_amt/1e8:.1f}亿 ｜20日均{_avg20/1e8:.1f}亿(×{_ratio:.1f}) "
                        f"｜一年最高{_max250/1e8:.1f}亿 ｜今日{_chg:+.2f}% ｜距120日高{_off:+.1f}% "
                        f"[{_src}{_dt}] {_tag54}")
            if _tag54:
                _alarm54.append((_nm, _tag54, _off, _chg))
        if _alarm54:
            _L54.append("")
            _L54.append(f"  ★★报警 {len(_alarm54)} 只★★")
            for _nm, _tg, _off, _chg in _alarm54:
                if _off <= -12:
                    _jd = "低位巨量 → 托底/投降盘被接（底部特征）"
                elif _off >= -3:
                    _jd = "高位巨量 → ⚠️警惕924式见顶（2024-10-08 创业板ETF 474亿当天即顶）"
                else:
                    _jd = "中位巨量 → 看次日能否守住今日振幅中点"
                _L54.append(f"   {_tg} {_nm} 今日{_chg:+.2f}% 距120日高{_off:+.1f}% → {_jd}")
            _kinds = {n[:3] for n, _, _, _ in _alarm54}
            if any(k in ("创业板", "科创5") for k in _kinds):
                _L54.append("   ★创业板/科创ETF在报警名单里 = 资金定向托【成长/科技】，不只是托权重")
            _L54.append("  ★AI必做：回复第一段就写这条，并说明是底部巨量还是顶部巨量")
        else:
            _L54.append("  （今日无宽基ETF创纪录/放量≥3倍）")
        _L54.append("=" * 60)
        try:
            os.makedirs("reports", exist_ok=True)
            for _c in list(_hist54):
                _ks = sorted(_hist54[_c])[-400:]
                _hist54[_c] = {k: _hist54[_c][k] for k in _ks}
            _j54.dump(_hist54, open(_hp54, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception:
            pass
        _pos54 = next((i for i, l in enumerate(REPORT) if "今日硬线索" in str(l)), 8)
        _pos54 = max(0, _pos54 - 1)
        REPORT[_pos54:_pos54] = _L54
    except Exception as _e54:
        REPORT.insert(8, f"  [patch54] 国家队雷达失败：{type(_e54).__name__}: {str(_e54)[:60]}")

'''.replace("@@MARK@@", MARK)

s = s.replace(D, NEW + D, 1)
io.open(path, "w", encoding="utf-8").write(s)
print("OK 1: patch54 国家队雷达·宽基ETF成交额 已插入（报告第一屏）")

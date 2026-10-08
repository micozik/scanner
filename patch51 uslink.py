# -*- coding: utf-8 -*-
"""
patch51_uslink.py —— A股报告新增【美股联动核对】
2026-10-08 用户：『美股什么涨？对应A股是否有联动？什么原因？你不去找？
                这样的话，我弄美股雷达有何用？』
实情：美股报告只对『持仓』做影响判断；美股里涨的减肥药/疫苗/美光、
     跌的卡特彼勒/GEV/康宁，对应A股今天是跟还是不跟，没人核对。
做法（全自动）：
  读 reports/us_quote.json（美股补丁 patch_usa50 写的），
  按 16 条链把美股涨跌 → 对应A股代表股今日平均涨跌，逐条判：
    ✅同向联动  ｜  ⚠️背离（美涨A跌 / 美跌A涨）→ AI必须写出原因
  美股按涨跌排序，A股代表股用全市场快照，不额外请求接口。
"""
import io, os, sys
MARK = "patch51_uslink"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch51 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch51 已打过"); sys.exit(0)
D = '''    os.makedirs("reports", exist_ok=True)
    text = "\\n".join(REPORT)'''
if s.count(D) != 1:
    print("!! patch51 中止：报告写出锚点命中 %d 次" % s.count(D)); sys.exit(0)

NEW = r'''    # ===== @@MARK@@：美股联动核对 =====
    try:
        _CH51 = [
            ("存储", ["MU", "SNDK", "WDC", "STX"],
             ["300475", "301308", "001309", "603986", "688525"]),
            ("算力/CPO/服务器", ["NVDA", "AVGO", "AMD"],
             ["300308", "300502", "601138", "000977", "300476"]),
            ("半导体设备/代工", ["TSM", "ASML", "AMAT", "LRCX"],
             ["002371", "688012", "688981", "688072"]),
            ("玻璃基板", ["GLW"], ["600552", "603773", "600707"]),
            ("光芯片", ["COHR"], ["688498", "688048", "688313"]),
            ("减肥药/创新药", ["LLY"], ["600276", "300199", "688166", "000963"]),
            ("疫苗", ["MRNA"], ["300122", "300142", "688185"]),
            ("特斯拉/机器人", ["TSLA"], ["601689", "002050", "002472"]),
            ("燃机/电力设备", ["GEV"], ["600875", "601727", "603308"]),
            ("黄金", ["NEM"], ["601899", "600547", "600489"]),
            ("果链", ["AAPL"], ["002475", "300433", "002241"]),
            ("锂矿", ["ALB", "SQM"], ["002466", "002460"]),
            ("固态电池", ["QS"], ["300450", "300073"]),
            ("油运", ["FRO", "DHT"], ["600026", "601975", "601872"]),
            ("油气", ["XOM", "CVX", "OXY"], ["600938", "601857", "300164"]),
            ("AI应用/云", ["MSFT", "GOOGL", "AMZN", "META"],
             ["688111", "002230", "300033"]),
        ]
        _L51 = ["", "=" * 60,
                "🌉🌉【美股联动核对】昨夜美股涨跌 → 对应A股今天跟没跟？🌉🌉",
                "=" * 60]
        _fp51 = "reports/us_quote.json"
        if not os.path.exists(_fp51):
            _L51.append("  ⚠️ 没有 reports/us_quote.json（美股补丁 patch_usa50 未生效或美股还没跑）")
        else:
            with open(_fp51, encoding="utf-8") as _f:
                _js51 = json.load(_f)
            _q51 = _js51.get("quote", {}) or {}
            _nm51 = _js51.get("name", {}) or {}
            _L51.append(f"  美股数据生成于 {_js51.get('made', '?')}，共 {len(_q51)} 只")
            _rk = sorted(_q51.items(), key=lambda x: x[1][0], reverse=True)
            if _rk:
                _L51.append("  美股涨幅前5：" + "，".join(
                    f"{_nm51.get(k, k)}{v[0]:+.2f}%" for k, v in _rk[:5]))
                _L51.append("  美股跌幅前5：" + "，".join(
                    f"{_nm51.get(k, k)}{v[0]:+.2f}%" for k, v in _rk[-5:][::-1]))
                _L51.append(f"  （数据日期：{_rk[0][1][2]}）")
            _sp = globals().get("SPOT_DF")
            if _sp is None:
                try:
                    _sp = get_spot()
                except Exception:
                    _sp = None
            _a51 = {}
            if _sp is not None and len(_sp):
                _cc = pick_col(_sp, ["代码", "code", "symbol"])
                _cn = pick_col(_sp, ["名称", "name"])
                _cg = pick_col(_sp, ["涨跌幅", "changepercent"])
                for _, _r in _sp.iterrows():
                    try:
                        _a51[str(_r[_cc])[-6:]] = (
                            str(_r[_cn]), float(pd.to_numeric(_r[_cg], errors="coerce")))
                    except Exception:
                        continue
            _L51.append("")
            _L51.append("  链条              美股       A股代表股今日     判定")
            _div = []
            for _ch, _us, _as in _CH51:
                _uv = [_q51[t][0] for t in _us if t in _q51]
                if not _uv:
                    continue
                _um = sum(_uv) / len(_uv)
                _av = [(_a51[c][0], _a51[c][1]) for c in _as
                       if c in _a51 and _a51[c][1] == _a51[c][1]]
                if not _av:
                    _L51.append(f"  {_ch:<14} {_um:+.2f}%   A股快照无数据")
                    continue
                _am = sum(x[1] for x in _av) / len(_av)
                if abs(_um) < 0.8:
                    _tag = "⚪美股无方向"
                elif (_um > 0) == (_am > 0):
                    _tag = "✅同向联动"
                else:
                    _tag = "⚠️背离·美涨A跌" if _um > 0 else "⚠️背离·美跌A涨"
                    _div.append(_ch)
                _det = " ".join(f"{n}{p:+.1f}" for n, p in _av[:3])
                _L51.append(f"  {_ch:<12} 美{_um:+.2f}%  A{_am:+.2f}%  {_tag}  ({_det})")
            _L51.append("")
            if _div:
                _L51.append("  ★AI必做：背离的链逐条写原因（亚洲盘/港股先跌了？国内利空？"
                            "估值透支？资金轮动？）→ " + "、".join(_div))
            _L51.append("  ★同向联动且美股≥+2%的链 = 今天的顺风方向，去链里找没涨透的票")
        _L51.append("=" * 60)
        _pos51 = next((i for i, l in enumerate(REPORT) if "数据可信度体检" in str(l)), 8)
        _pos51 = max(0, _pos51 - 1)
        REPORT[_pos51:_pos51] = _L51
    except Exception as _e51:
        REPORT.insert(8, f"  [patch51] 美股联动核对失败：{type(_e51).__name__}: {str(_e51)[:60]}")
    # ===== @@MARK@@ 结束 =====
'''.replace("@@MARK@@", MARK)
s = s.replace(D, NEW + D, 1)
io.open(path, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n# " + MARK + "\n")
print("OK 1: 【美股联动核对】将插在报告顶部 → " + path)

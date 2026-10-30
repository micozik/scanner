# -*- coding: utf-8 -*-
"""
patch57_risk_alarm.py —— 【持仓风险预警·提前量】不等止损，先看"这条线是不是烂了"
2026-10-30 用户：『昨天的行情已经很危险，你一点感觉都没有，只会说还没到点所以不动，
  你并没有去看这条线是不是烂了。』
复盘：10/29 报告风险分9/16、上涨占比14.7%、跌停52只、科技链失血309亿；
  兆易三季报+729%当天股价−4.8%（利好不涨）、兆易/富联双双跌破60日低点；
  谷歌−12.6%、亚马逊盘后−12%。信号全在，AI只看"止损破没破"，没给任何提前动作。
做法（全自动，每次扫描都跑）：
  对 我的清单.txt 里每只持仓逐条打分（每条=1个危险信号）：
    ① 大盘风险分 ≥ 8/16
    ② 跌破60日最低价（趋势在破，不是"低位"）
    ③ 收在20日均线下方 且 20日线在下行
    ④ 今日跑输所属板块 ≥ 2 个百分点（板块涨它跌 = 死亡信号）
    ⑤ 所属板块今日资金净流出 ≥ 20亿 且 板块跌 > 1%
    ⑥ 距止损 ≤ 2%
  0–1个=🟢绿（不动）；2个=🟡黄（必须写出风险提示+预案价）；≥3个=🔴红（建议次日开盘先减半，等用户确认）
  红/黄都写在报告第一屏，AI回复第一段必须先说这一节。
"""
import io, os, sys
MARK = "patch57_risk_alarm"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch57 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch57 已打过"); sys.exit(0)
D = '''    os.makedirs("reports", exist_ok=True)
    text = "\\n".join(REPORT)'''
if s.count(D) != 1:
    print("!! patch57 中止：报告写出锚点命中 %d 次" % s.count(D)); sys.exit(0)

NEW = r'''    # ===== @@MARK@@：持仓风险预警·提前量 =====
    try:
        import re as _re57, json as _j57, urllib.request as _u57
        _L57 = ["", "=" * 60,
                "🚦🚦【持仓风险预警·提前量】不等止损，先看这条线烂没烂 🚦🚦",
                "=" * 60]
        # --- 持仓：读 我的清单.txt ---
        _hold57 = []
        for _fn in ("我的清单.txt", "我的清单 .txt"):
            if os.path.exists(_fn):
                for _ln in open(_fn, encoding="utf-8"):  # scanner 没有 import io
                    _p = [x.strip() for x in _ln.split("|")]
                    if len(_p) >= 6 and _p[0] == "持仓" and _re57.fullmatch(r"\d{6}", _p[1]):
                        try:
                            _hold57.append((_p[1], _p[2], float(_p[3]), float(_p[5])))
                        except Exception:
                            pass
                break
        _txt57 = "\n".join(str(x) for x in REPORT)
        _m = _re57.search(r"风险分：(\d+)/16", _txt57)
        _risk57 = int(_m.group(1)) if _m else None
        _m = _re57.search(r"上涨占比([\d.]+)%", _txt57)
        _br57 = float(_m.group(1)) if _m else None
        _L57.append(f"  大盘：风险分 {_risk57 if _risk57 is not None else '?'}/16 ｜ 上涨占比 {_br57 if _br57 is not None else '?'}%"
                    + ("  ⚠️高危" if (_risk57 or 0) >= 8 else ""))

        def _k57(code):
            mk = ("sh" if code.startswith(("6", "9")) else "sz") + code
            url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=%s,day,,,130,qfq" % mk
            raw = _u57.urlopen(_u57.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=8).read().decode("utf-8", "ignore")
            d = _j57.loads(raw)["data"][mk]
            rows = d.get("qfqday") or d.get("day") or []
            return [(str(r[0]), float(r[2]), float(r[4])) for r in rows]   # 日期, 收, 低

        _red57, _yel57 = [], []
        for _cd, _nm, _cost, _stop in _hold57:
            _sig, _info = [], ""
            try:
                _rows = _k57(_cd)
                _cl = [c for _, c, _ in _rows]
                _lo = [l for _, _, l in _rows]
                _px = _cl[-1]
                _chg = (_px / _cl[-2] - 1) * 100 if len(_cl) > 1 else 0
                _lo60 = min(_lo[-61:-1]) if len(_lo) > 61 else min(_lo[:-1])
                _ma20 = sum(_cl[-20:]) / 20
                _ma20p = sum(_cl[-25:-5]) / 20
                _info = f"现价{_px:.2f}（{_chg:+.2f}%）｜60日低{_lo60:.2f}｜20日线{_ma20:.2f}"
                if (_risk57 or 0) >= 8:
                    _sig.append("大盘风险分≥8")
                if _px < _lo60:
                    _sig.append(f"跌破60日低点{_lo60:.2f}")
                if _px < _ma20 and _ma20 < _ma20p:
                    _sig.append("在下行的20日线下方")
                _bm = _re57.search(r"◆ " + _re57.escape(_nm) + r"\(" + _cd + r"\).*?\n\s*└ 板块\[(.+?)\] ([-\d.]+)% 资金([-+\d.]+)亿", _txt57)
                if _bm:
                    _spc, _sfl = float(_bm.group(2)), float(_bm.group(3))
                    _info += f"｜板块[{_bm.group(1)}]{_spc:+.2f}% 资金{_sfl:+.1f}亿"
                    if _chg - _spc <= -2:
                        _sig.append(f"跑输板块{_chg - _spc:.1f}个点")
                    if _sfl <= -20 and _spc < -1:
                        _sig.append("板块大额净流出且下跌")
                _dist = (_px / _stop - 1) * 100 if _stop else 99
                _info += f"｜距止损{_stop}：{_dist:+.1f}%"
                if _dist <= 2:
                    _sig.append("距止损≤2%")
            except Exception as _e:
                _info = f"K线取不到（{type(_e).__name__}）→ 只按大盘判"
                if (_risk57 or 0) >= 8:
                    _sig.append("大盘风险分≥8")
            _lv = "🔴红" if len(_sig) >= 3 else ("🟡黄" if len(_sig) == 2 else "🟢绿")
            _act = {"🔴红": "建议次日开盘先减半（等用户确认），剩余半仓守止损",
                    "🟡黄": "必须给风险提示+预案：再出现1个信号就减半",
                    "🟢绿": "不动"}[_lv]
            _L57.append(f"  {_lv} {_nm}({_cd}) 危险信号{len(_sig)}个：{('、'.join(_sig) or '无')}")
            _L57.append(f"      {_info}")
            _L57.append(f"      → {_act}")
            (_red57 if _lv == "🔴红" else _yel57 if _lv == "🟡黄" else []).append(_nm)
        if not _hold57:
            _L57.append("  （我的清单.txt 里没读到持仓）")
        if _red57 or _yel57:
            _L57.append(f"  ★★AI必做：回复第一段先说这一节——红：{('、'.join(_red57) or '无')}｜黄：{('、'.join(_yel57) or '无')}，"
                        "每只给出具体动作和价位，不许只说『还没到止损』★★")
        _L57.append("=" * 60)
        _pos57 = next((i for i, l in enumerate(REPORT) if "主线锁定" in str(l)), None)
        if _pos57 is None:
            _pos57 = next((i for i, l in enumerate(REPORT) if "今日硬线索" in str(l)), 8)
        _pos57 = max(0, _pos57 - 2)
        REPORT[_pos57:_pos57] = _L57
    except Exception as _e57:
        REPORT.insert(8, f"  [patch57] 持仓风险预警失败：{type(_e57).__name__}: {str(_e57)[:60]}")

'''.replace("@@MARK@@", MARK)

s = s.replace(D, NEW + D, 1)
io.open(path, "w", encoding="utf-8").write(s)
print("OK 1: patch57 持仓风险预警·提前量 已插入（报告第一屏）")

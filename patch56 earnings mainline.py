# -*- coding: utf-8 -*-
"""
patch56_earnings_mainline.py —— 修 patch55【业绩大增→明日候选】漏掉鸣志电器
2026-10-28 用户：『看看你漏了的鸣志』
根因（查 r941 / r945 原文确认）：
  ① 10/27 17:12 新闻池里已有『鸣志电器：前三季度净利润同比增长101.05%』，正则也抓到了，
     但 B 段按增速从大到小排、只显示前25条 —— 第25条是包钢+112%，鸣志+101% 排第26被截掉。
     排序只看增速、不看主线：扭亏的化工/钢铁排前面，机器人主线里的鸣志反而被挤出。
  ② 次日 10:56 盘中报告只扫『当天』新闻池（从凌晨起），前一晚的业绩快讯全丢 →
     r945 写『今天新闻/公告池里没有业绩大增公告』。
  ③ 抓的是前三季+101%，没抓单季 Q3 +175.3%（单季才是加速信号）。
做法：
  A. 排序改成：主线/强板块里的票（名字出现在报告的候选股、A股标的、弹性榜、主线行里）排最前，
     其次单季增速、再次累计增速；显示上限 25 → 60。
  B. 每次命中写 reports/earnings_hist.json；下一次运行把『最近2个自然日』的命中合并进来，
     盘中报告不再丢前一晚的公告。
  C. 正则补『第三季度/单季』增速，同一只取较大值。
"""
import io, os, sys
MARK = "patch56_earnings_mainline"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch56 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch56 已打过"); sys.exit(0)
if "patch55_actionable" not in s:
    print("!! patch56 中止：patch55 还没打上（patch56 必须排在 patch55 之后）"); sys.exit(0)

A1 = "        _hits55.sort(reverse=True)\n"
A2 = "        for _g, _nm, _cd, _pc, _tt in _hits55[:25]:\n"
if s.count(A1) != 1 or s.count(A2) != 1:
    print("!! patch56 中止：锚点命中 %d/%d 次" % (s.count(A1), s.count(A2))); sys.exit(0)

NEW1 = r'''        # ===== @@MARK@@：主线优先 + 跨日合并 + 单季增速 =====
        try:
            _rxq56 = _re55.compile(r"(?<!前)(第三季度|三季度|Q3|单季)[^。；]{0,20}?(净利润|归母净利润)[^。；]{0,25}?(增长|增)\s*([\d.]+)\s*%")
            _best56 = {}
            for _t in _pool55:
                _mq = _rxq56.search(_t)
                if not _mq:
                    continue
                for _h in _hits55:
                    if _h[1] in _t:
                        try:
                            _best56[_h[1]] = max(_best56.get(_h[1], 0.0), float(_mq.group(4)))
                        except Exception:
                            pass
            # 跨日合并：读昨晚的命中
            _hf56 = os.path.join("reports", "earnings_hist.json")
            _old56 = {}
            try:
                _old56 = _j55.load(open(_hf56, encoding="utf-8"))
            except Exception:
                _old56 = {}
            _now56 = _d55.datetime.now(_d55.timezone.utc) + _d55.timedelta(hours=8)
            _have56 = {h[1] for h in _hits55}
            for _nm, _v in list(_old56.items()):
                try:
                    _dt = _d55.datetime.strptime(_v["d"], "%Y-%m-%d %H:%M")
                    if (_now56.replace(tzinfo=None) - _dt).days > 2 or _nm in _have56:
                        continue
                    _cd, _pc = _n2c55.get(_nm, (_v.get("c", ""), None))
                    _hits55.append((float(_v["g"]), _nm, _cd, _pc, "[%s公告] " % _v["d"][5:] + _v["t"]))
                    if _v.get("q"):
                        _best56[_nm] = max(_best56.get(_nm, 0.0), float(_v["q"]))
                except Exception:
                    continue
            # 写回（只留2天）
            _keep56 = {}
            for _nm, _v in _old56.items():
                try:
                    if (_now56.replace(tzinfo=None) - _d55.datetime.strptime(_v["d"], "%Y-%m-%d %H:%M")).days <= 2:
                        _keep56[_nm] = _v
                except Exception:
                    pass
            for _g, _nm, _cd, _pc, _tt in _hits55:
                if _nm not in _keep56 and not _tt.startswith("["):
                    _keep56[_nm] = {"d": _now56.strftime("%Y-%m-%d %H:%M"), "g": _g, "c": _cd,
                                    "q": _best56.get(_nm, 0.0), "t": _tt[:50]}
            os.makedirs("reports", exist_ok=True)
            open(_hf56, "w", encoding="utf-8").write(_j55.dumps(_keep56, ensure_ascii=False))
            # 主线判定：名字出现在报告的候选/标的/弹性/主线行里
            _rep56 = [ln for ln in globals().get("REPORT", []) if isinstance(ln, str) and
                      any(k in ln for k in ("A股标的", "弹性", "候选", "主线", "领涨"))]
            _rep56 = "\n".join(_rep56)
            def _key56(h):
                _g, _nm = h[0], h[1]
                _ml = 1 if _nm in _rep56 else 0
                _q = _best56.get(_nm, 0.0)
                return (_ml, max(_q, min(_g, 998.0)))
            _hits55.sort(key=_key56, reverse=True)
            _ML56 = {h[1] for h in _hits55 if h[1] in _rep56}
            _Q56 = _best56
        except Exception as _e56:
            print("patch56 出错（回退原排序）:", _e56)
            _hits55.sort(reverse=True)
            _ML56, _Q56 = set(), {}
'''.replace("@@MARK@@", MARK)

NEW2 = '''        for _g, _nm, _cd, _pc, _tt in _hits55[:60]:
            if _nm in _ML56:
                _L55.append(f"   ★主线×业绩 {_nm}" + (f"｜单季+{_Q56[_nm]:.0f}%" if _Q56.get(_nm) else ""))
'''

s = s.replace(A1, NEW1, 1).replace(A2, NEW2, 1)
io.open(path, "w", encoding="utf-8").write(s)
print("OK 1: patch56 已打上（业绩大增：主线优先 + 跨日合并 + 单季增速，上限60）")

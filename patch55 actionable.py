# -*- coding: utf-8 -*-
"""
patch55_actionable.py —— 【主线锁定 + 明日可执行信号】
2026-10-27 用户：『每天都有涨的股票，你反省哪里做错了，改，立刻改』
复盘找出的两个根因：
  ① 最强主线（机器人：10/20、10/22、10/23、10/26、10/27 连续成为涨停最集中方向）摆在眼前，
     AI却去下跌板块抄底 → 没有一个模块每天明确告诉我『主线是谁、持续几天了』；
  ② 雷赛10/22盘后公告三季报+86.8%、10/23涨停 —— 消息早收到了，却只写进复盘、没变成买入代码
     → 没有一个模块把『业绩大增公告』直接变成『明日候选代码』。
做法（全自动）：
  A.【主线锁定】从报告里的【涨停池】按行业数涨停，存 reports/mainline_hist.json；
     近3个交易日里 ≥2天 涨停≥3只 的行业 = 主线；今天资金也流入的 = ★强主线。
  B.【业绩大增→明日候选】扫新闻+公告池里『净利润…增长X%』(X≥50) /『扭亏』，
     对上全市场快照拿到代码和今日涨幅：今日涨幅≤4% = ✅明日可买候选；>4% = ⏫今天已涨。
  插在【今日硬线索】正上方（报告第一屏），排在国家队雷达之后。
"""
import io, os, sys
MARK = "patch55_actionable"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch55 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch55 已打过"); sys.exit(0)

D = '''    os.makedirs("reports", exist_ok=True)
    text = "\\n".join(REPORT)'''
if s.count(D) != 1:
    print("!! patch55 中止：报告写出锚点命中 %d 次" % s.count(D)); sys.exit(0)

NEW = r'''    # ===== @@MARK@@：主线锁定 + 明日可执行信号 =====
    try:
        import re as _re55, json as _j55, datetime as _d55
        _L55 = ["", "=" * 60,
                "🎯🎯【主线锁定 + 明日可执行信号】钱在哪条线、明天买哪只 🎯🎯",
                "=" * 60]
        _today55 = (_d55.datetime.now(_d55.timezone.utc) + _d55.timedelta(hours=8)).strftime("%Y-%m-%d")

        # ---- A. 主线锁定：从报告文字里读【涨停池】行业分布 + 【行业净流入】 ----
        _lu55, _in55, _sec = {}, set(), None
        for _ln in list(REPORT):
            _t = str(_ln)
            if "【五、涨停池】" in _t:
                _sec = "lu"; continue
            if "行业净流入前10" in _t:
                _sec = "in"; continue
            if _sec == "lu":
                if "最高连板" in _t or _t.startswith("【"):
                    _sec = None; continue
                _m = _re55.match(r"\s+(\S+?)：(\d+)只", _t)
                if _m:
                    _lu55[_m.group(1).replace("Ⅱ", "")] = int(_m.group(2))
            elif _sec == "in":
                if "净流出" in _t or _t.startswith("【"):
                    _sec = None; continue
                _m = _re55.match(r"\s+(\S+?)\s*\|\s*[-\d.]+%\s*\|\s*\+?(-?[\d.]+)亿", _t)
                if _m and float(_m.group(2)) > 0:
                    _in55.add(_m.group(1).replace("Ⅱ", ""))
        _hp55 = "reports/mainline_hist.json"
        try:
            _h55 = _j55.load(open(_hp55, encoding="utf-8"))
        except Exception:
            _h55 = {}
        # v2：盘中报告没有【涨停池】→ 用仓库里历史盘后报告自举主线库（10/27 首次上线时库是空的）
        if len(_h55) < 3:
            try:
                import glob as _g55
                _fs = sorted(_g55.glob("reports/r[0-9]*.txt"), key=lambda f: int(_re55.sub(r"\D", "", f) or 0))[-40:]
                for _f in _fs:
                    _tx = open(_f, encoding="utf-8", errors="ignore").read()
                    _hd = _re55.search(r"\|\s*(20\d\d-\d\d-\d\d)\s", _tx[:400])
                    if not _hd or "【五、涨停池】" not in _tx:
                        continue
                    _seg = _tx.split("【五、涨停池】", 1)[1].split("最高连板", 1)[0]
                    _dct = {}
                    for _mm in _re55.finditer(r"\n\s+(\S+?)：(\d+)只", _seg):
                        _dct[_mm.group(1).replace("Ⅱ", "")] = int(_mm.group(2))
                    if _dct and _hd.group(1) != _today55:
                        _h55[_hd.group(1)] = _dct
            except Exception:
                pass
        if _lu55:
            _h55[_today55] = _lu55
        _days55 = sorted(_h55)[-3:]
        _cnt55 = {}
        for _dd in _days55:
            for _ind, _n in _h55[_dd].items():
                if _n >= 3:
                    _cnt55[_ind] = _cnt55.get(_ind, 0) + 1
        _ml55 = sorted([(c, _lu55.get(i, 0), i) for i, c in _cnt55.items() if c >= 2], reverse=True)
        _top15 = []
        _flag = False
        for _ln in list(REPORT):
            _t = str(_ln)
            if "行业涨幅前15" in _t:
                _flag = True; continue
            if _flag:
                _m = _re55.match(r"\s+(\S+?)\s*\|\s*(-?[\d.]+)%", _t)
                if _m:
                    _top15.append((_m.group(1), float(_m.group(2))))
                elif "◆" in _t or _t.startswith("【"):
                    break
        _L55.append("  ── A. 主线锁定（近%d个交易日，≥2天涨停≥3只的行业）──" % len(_days55))
        if not _lu55:
            _L55.append("  （盘中报告无【涨停池】→ 主线用历史盘后数据，今天强弱看行业涨幅前15）")
        if _ml55:
            for _c, _nt, _i in _ml55:
                _hit = any(n.startswith(_i[:2]) or _i.startswith(n[:2]) for n in _in55)
                _rk = next((k + 1 for k, (n, _p) in enumerate(_top15) if n.startswith(_i[:2]) or _i.startswith(n[:2])), None)
                _star = "★强主线(今天资金也在流入)" if _hit else "主线(今天资金未进前10)"
                _rks = (f"｜今天行业涨幅第{_rk}" if _rk else ("｜今天不在涨幅前15" if _top15 else ""))
                _nts = (f"今天涨停{_nt}只" if _lu55 else "今天涨停(盘后统计)")
                _L55.append(f"   {_i}：近{len(_days55)}天有{_c}天涨停≥3只｜{_nts}{_rks} → {_star}")
            _L55.append("  ★新买入只从主线里挑；不抄下跌板块的底（10/27反省第1条）")
        else:
            _L55.append("   今天还没有连续≥2天的主线（库里%d天数据，满3天后才准）" % len(_h55))
            if _lu55:
                _top = sorted(_lu55.items(), key=lambda x: -x[1])[:3]
                _L55.append("   今天涨停最集中：" + "、".join(f"{k}{v}只" for k, v in _top))

        # ---- B. 业绩大增公告 → 明日候选 ----
        def _t55(it):
            if isinstance(it, dict):
                return str(it.get("title") or it.get("t") or it.get("content") or "")
            if isinstance(it, (tuple, list)):
                return " ".join(str(x) for x in it)
            return str(it)
        _pool55 = [_t55(x) for x in (list(globals().get("TODAY_NEWS", []) or []) +
                                     list(globals().get("TODAY_ANNOUNCE_RAW", []) or []))]
        _sp55 = globals().get("SPOT_DF")
        _n2c55 = {}
        if _sp55 is not None and len(_sp55):
            _cc = pick_col(_sp55, ["代码", "code", "symbol"])
            _cn = pick_col(_sp55, ["名称", "name"])
            _cg = pick_col(_sp55, ["涨跌幅", "changepercent"])
            for _, _r in _sp55.iterrows():
                try:
                    _n2c55[str(_r[_cn]).replace(" ", "")] = (str(_r[_cc])[-6:],
                                                            float(pd.to_numeric(_r[_cg], errors="coerce")))
                except Exception:
                    continue
        _hits55, _seen55 = [], set()
        _RX55 = _re55.compile(r"【?([一-龥A-Za-z]{2,8}?)(?:[：:]|(?=前三季度|第三季度|三季度|上半年|前三季)).{0,40}?(净利润|归母净利润|扣非净利润).{0,20}?(增长|增|同比增长)\s*([\d.]+)\s*[%倍]")
        _RX55b = _re55.compile(r"【?([一-龥A-Za-z]{2,8})[：:].{0,30}?扭亏")
        for _t in _pool55:
            _nm, _g = None, None
            _m = _RX55.search(_t)
            if _m:
                _nm = _m.group(1).replace(" ", "")
                try:
                    _g = float(_m.group(4))
                    if "倍" in _t[_m.start(4):_m.end(4) + 2]:
                        _g *= 100
                except Exception:
                    _g = None
            else:
                _m = _RX55b.search(_t)
                if _m:
                    _nm, _g = _m.group(1).replace(" ", ""), 999.0
            if not _nm or _g is None or _g < 50 or _nm in _seen55 or "ST" in _nm:
                continue
            if _nm not in _n2c55 and not _re55.search(_re55.escape(_nm) + r"[：:]", _t):
                continue   # 无冒号的写法（如"创世纪前三季度…"）必须能对上快照，防止"公司前三季度"这类误抓
            if any(k in _t for k in ("下降", "下滑", "亏损扩大", "同比减少")):
                continue
            _seen55.add(_nm)
            _cd, _pc = _n2c55.get(_nm, ("", None))
            _hits55.append((_g, _nm, _cd, _pc, _re55.sub(r"\s+", " ", _t)[:60]))
        _hits55.sort(reverse=True)
        _L55.append("")
        _L55.append("  ── B. 业绩大增（≥50%或扭亏）→ 明日候选 ──（10/27反省第2条：雷赛+86.8%次日涨停却没推）")
        if not _hits55:
            _L55.append("   今天新闻/公告池里没有业绩大增公告")
        _ok55 = []
        for _g, _nm, _cd, _pc, _tt in _hits55[:25]:
            _gs = "扭亏" if _g >= 999 else ("+%.0f%%" % _g)
            if _pc is None or not _cd:
                _L55.append(f"   ❔ {_nm} {_gs} ｜ 代码/涨幅对不上快照 ｜ {_tt}")
            elif _pc <= 4:
                _ok55.append(_cd)
                _L55.append(f"   ✅ {_nm}({_cd}) {_gs} ｜ 今日{_pc:+.2f}% → 明日可买候选（查位置+资金）")
            else:
                _L55.append(f"   ⏫ {_nm}({_cd}) {_gs} ｜ 今日{_pc:+.2f}% → 今天已涨，不追")
        if _ok55:
            _L55.append("  ★明日候选代码（复制去查股票）：" + ",".join(_ok55[:12]))
        _L55.append("  ★AI必做：主线里有业绩大增的 = 双重确认，优先；只有业绩没主线的 = 次选")
        _L55.append("=" * 60)
        try:
            os.makedirs("reports", exist_ok=True)
            _keep = {k: _h55[k] for k in sorted(_h55)[-40:]}
            _j55.dump(_keep, open(_hp55, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception:
            pass
        _pos55 = next((i for i, l in enumerate(REPORT) if "今日硬线索" in str(l)), 8)
        _pos55 = max(0, _pos55 - 1)
        REPORT[_pos55:_pos55] = _L55
    except Exception as _e55:
        REPORT.insert(8, f"  [patch55] 主线锁定失败：{type(_e55).__name__}: {str(_e55)[:60]}")

'''.replace("@@MARK@@", MARK)

s = s.replace(D, NEW + D, 1)
io.open(path, "w", encoding="utf-8").write(s)
print("OK 1: patch55 主线锁定+明日可执行信号 已插入（报告第一屏）")

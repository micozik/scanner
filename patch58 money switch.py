# -*- coding: utf-8 -*-
"""
patch58_money_switch.py —— 【资金开关 + 资金轮动】大资金今天是"敢冒险"还是"躲起来"，钱从哪搬到哪
2026-10-30 用户：『为什么资金会同时做同一件事？昨天还好好的，今天全部撤离进别的板块。
  掌握这个逻辑，我们就把自己当成资金，他们动我们也跟着动。化繁为简。』
原理：几千个大资金看同一块屏幕（美股科技、利率/油价、A股广度），用相似规则做决定
  → 风险偏好开关一拨，同一天一起搬家；拥挤的先跑，钱流向便宜有现金流的地方。
做法（全自动）：
  ① 开关：数"风险关"信号——费半隔夜≤−2%、纳指≤−1%、A股上涨占比<30%、
     风险分≥8、成长板块今日合计净流出≤−100亿 → ≥3个=🔴关 / ≤1个且成长净流入=🟢开 / 其余🟡观望
  ② 轮动：用 reports/sector_flow_hist.json 算近3天【成长篮子】vs【防御篮子】资金合计，
     和行业3日累计净流入/流出前5（标出连续≥2天同向的=趋势，1天=噪音）
  插在报告第一屏（持仓风险预警上方）。AI回复第一句必须先报开关。
"""
import io, os, sys
MARK = "patch58_money_switch"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch58 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch58 已打过"); sys.exit(0)
D = '''    os.makedirs("reports", exist_ok=True)
    text = "\\n".join(REPORT)'''
if s.count(D) != 1:
    print("!! patch58 中止：报告写出锚点命中 %d 次" % s.count(D)); sys.exit(0)

NEW = r'''    # ===== @@MARK@@：资金开关 + 资金轮动 =====
    try:
        import re as _re58, json as _j58, glob as _g58
        _GROW58 = ["半导体", "通信设备", "元件", "消费电子", "计算机设备", "软件开发", "IT服务",
                   "光学光电子", "其他电子", "电子化学品", "自动化设备", "电机", "通用设备",
                   "专用设备", "汽车零部件", "军工电子"]
        _DEF58 = ["银行", "保险", "煤炭开采加工", "白酒", "饮料制造", "电力", "港口航运",
                  "油气开采及服务", "石油加工贸易", "公路铁路运输", "燃气", "中药", "化学制药", "医疗服务"]
        _txt58 = "\n".join(str(x) for x in REPORT)
        _L58 = ["", "=" * 60, "🔀🔀【资金开关 + 资金轮动】大资金今天敢不敢冒险、钱从哪搬到哪 🔀🔀", "=" * 60]
        # --- 隔夜美股：读最新 us<N>.txt ---
        _sox58 = _ndq58 = None
        _us = sorted(_g58.glob("reports/us[0-9]*.txt"), key=lambda f: int(_re58.sub(r"\D", "", f) or 0))
        if _us:
            _ut = open(_us[-1], encoding="utf-8", errors="ignore").read()[:3000]
            _m = _re58.search(r"费城半导体：[\d.]+ ([-+]?[\d.]+)%", _ut)
            _sox58 = float(_m.group(1)) if _m else None
            _m = _re58.search(r"纳斯达克：[\d.]+ ([-+]?[\d.]+)%", _ut)
            _ndq58 = float(_m.group(1)) if _m else None
        _m = _re58.search(r"上涨占比([\d.]+)%", _txt58)
        _br58 = float(_m.group(1)) if _m else None
        _m = _re58.search(r"风险分：(\d+)/16", _txt58)
        _rk58 = int(_m.group(1)) if _m else None
        # --- 板块资金历史 ---
        try:
            _h58 = _j58.load(open("reports/sector_flow_hist.json", encoding="utf-8"))
        except Exception:
            _h58 = {}
        _days58 = sorted(_h58)[-3:]
        def _bk(day, names):
            dd = _h58.get(day, {})
            return sum(float(dd.get(n, 0) or 0) for n in names)
        _g_today = _bk(_days58[-1], _GROW58) if _days58 else None
        _d_today = _bk(_days58[-1], _DEF58) if _days58 else None
        # --- 开关 ---
        _off, _why = 0, []
        if _sox58 is not None and _sox58 <= -2: _off += 1; _why.append(f"费半隔夜{_sox58:+.2f}%")
        if _ndq58 is not None and _ndq58 <= -1: _off += 1; _why.append(f"纳指隔夜{_ndq58:+.2f}%")
        if _br58 is not None and _br58 < 30: _off += 1; _why.append(f"A股上涨占比{_br58:.0f}%")
        if _rk58 is not None and _rk58 >= 8: _off += 1; _why.append(f"风险分{_rk58}/16")
        if _g_today is not None and _g_today <= -100: _off += 1; _why.append(f"成长篮子今日净流出{_g_today:.0f}亿")
        if _off >= 3:
            _sw = "🔴关（风险规避：钱在躲，成长股逆风）"
        elif _off <= 1 and (_g_today or 0) > 0:
            _sw = "🟢开（风险偏好：钱敢进成长）"
        else:
            _sw = "🟡观望（信号打架，成长仓不加）"
        _L58.append(f"  ★今日资金开关：{_sw}")
        _L58.append("    信号：" + ("、".join(_why) if _why else "无风险关信号")
                    + f"｜（费半{_sox58 if _sox58 is not None else '?'}% 纳指{_ndq58 if _ndq58 is not None else '?'}% "
                      f"上涨占比{_br58 if _br58 is not None else '?'}% 风险分{_rk58 if _rk58 is not None else '?'}）")
        # --- 篮子对比 ---
        if _days58:
            _L58.append("  ── 成长 vs 防御 资金（亿，近3个交易日）──")
            for _d in _days58:
                _g, _df = _bk(_d, _GROW58), _bk(_d, _DEF58)
                _tag = "钱→防御" if _df - _g > 30 else ("钱→成长" if _g - _df > 30 else "均衡")
                _L58.append(f"    {_d[5:]}  成长{_g:+8.1f} ｜ 防御{_df:+8.1f} ｜ {_tag}")
            # --- 行业3日累计 + 连续性 ---
            _sum58 = {}
            for _d in _days58:
                for _k, _v in _h58[_d].items():
                    try:
                        _sum58.setdefault(_k, []).append(float(_v))
                    except Exception:
                        pass
            def _streak(vals, sign):
                n = 0
                for v in reversed(vals):
                    if (v > 0) == (sign > 0) and v != 0:
                        n += 1
                    else:
                        break
                return n
            _rank = sorted(_sum58.items(), key=lambda kv: -sum(kv[1]))
            _L58.append("  ── 钱搬进去（3日累计净流入前5）──")
            for _k, _vs in _rank[:5]:
                _st = _streak(_vs, 1)
                _L58.append(f"    {_k}：{sum(_vs):+.1f}亿（逐日 {'/'.join(f'{v:+.0f}' for v in _vs)}）"
                            + (f" ✅连续{_st}天流入=趋势" if _st >= 2 else " ⚪仅1天=噪音"))
            _L58.append("  ── 钱搬出去（3日累计净流出前5）──")
            for _k, _vs in _rank[::-1][:5]:
                _st = _streak(_vs, -1)
                _L58.append(f"    {_k}：{sum(_vs):+.1f}亿（逐日 {'/'.join(f'{v:+.0f}' for v in _vs)}）"
                            + (f" 🔴连续{_st}天流出=在撤" if _st >= 2 else " ⚪仅1天=噪音"))
        else:
            _L58.append("  （sector_flow_hist.json 读不到，轮动无法计算）")
        _L58.append("  ★AI必做：①第一句报开关；②站在公募/保险/游资/量化/国家队的位置各写一句'明天我会怎么做'；"
                    "③开关🔴时成长仓不加、对冲腿（油运/红利）拿住；开关🟢时加主线成长")
        _L58.append("=" * 60)
        _pos58 = next((i for i, l in enumerate(REPORT) if "持仓风险预警" in str(l)), None)
        if _pos58 is None:
            _pos58 = next((i for i, l in enumerate(REPORT) if "主线锁定" in str(l)), None)
        if _pos58 is None:
            _pos58 = next((i for i, l in enumerate(REPORT) if "今日硬线索" in str(l)), 9)
        _pos58 = max(0, _pos58 - 2)
        REPORT[_pos58:_pos58] = _L58
    except Exception as _e58:
        REPORT.insert(8, f"  [patch58] 资金开关失败：{type(_e58).__name__}: {str(_e58)[:60]}")

'''.replace("@@MARK@@", MARK)

s = s.replace(D, NEW + D, 1)
io.open(path, "w", encoding="utf-8").write(s)
print("OK 1: patch58 资金开关+资金轮动 已插入（报告第一屏）")

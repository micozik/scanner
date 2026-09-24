# -*- coding: utf-8 -*-
"""
patch38_morning.py —— 按用户2026-09-24的要求重构输出：早晨简报模式
用户原话：
  『第一，每天新闻必须搜集，国内国外影响股票的所有新闻消息！一点都不能妥协！
    第二，根据信息面和技术面，找出板块的带动情况，找出强势板块！
    第三，从板块找出股票，然后把相对应的股票代码发给我，我去查股票帮你查！』

做两件事：
① 报告最前面加【晨间简报】：强势板块TOP5 + 每个板块的候选股代码（可直接拿去查股票）
   —— 用户睡醒第一屏就能看到"今天该查哪几只"
② 关掉与这三件事无关、且历史胜率<45%的模块，省时间、减BUG面：
   事件驱动雷达(19%)、选股器回测、事件雷达回测、埋伏池回测、
   跳升榜回测、深层含义解读器、隐形主线、异动无解释、定增、游资席位
   ★新闻、板块榜、资金、跳升、全板块交叉、领涨挖掘、盯盘、龙虎榜、美股
     —— 这九个一个不关（用户点名要的）
"""
import io, os, sys
MARK = "patch38_morning"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch38 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch38 已打过"); sys.exit(0)
ok = 0

# ① 扩充关闭名单（保留用户点名的九个模块）
A1 = '_SKIP29 = ("持仓/候选 深度体检", "定增破发雷达", "个股级选股器")  # patch30'
if A1 in s:
    s = s.replace(A1, '''_SKIP29 = ("持仓/候选 深度体检", "定增破发雷达", "个股级选股器",
           "事件驱动雷达", "事件雷达回测", "选股器回测", "埋伏池回测",
           "跳升榜回测", "深层含义", "隐形主线", "异动无解释", "异动未解释",
           "游资席位", "每日选股")  # ''' + MARK + '''
# ★保留不关：新闻电报流/板块全景榜/板块资金流向/启动日雷达/全板块交叉/
#   强板块领涨挖掘/重点盯盘/龙虎榜/涨停池/催化热力图/推演引擎/公告雷达''', 1)
    ok += 1; print("OK 1: 已关闭10个低胜率模块（新闻+板块+选股九件套全保留）")
else:
    print("!! 1: 关闭名单锚点未命中（patch29/30没打？）")

# ② 晨间简报置顶
A2 = '''    os.makedirs("reports", exist_ok=True)
    text = "\\n".join(REPORT)'''
if A2 in s:
    s = s.replace(A2, '''    # ''' + MARK + '''：晨间简报置顶
    try:
        _L38 = ["", "=" * 60,
                "☀️☀️【晨间简报】睡醒先看这一屏 —— 板块→个股→代码 ☀️☀️",
                "=" * 60]
        _bd38 = []
        for _k38 in ("行业", "概念"):
            for _n38, _v38 in (globals().get("TODAY_BOARD_" + _k38) or {}).items():
                try:
                    _p38 = float(_v38.get("pct"))
                except Exception:
                    continue
                _j38 = SECTOR_JUMP_MAP.get(_n38, 0) or 0
                _f38 = _sector_flow_of(_n38) if _k38 == "行业" else None
                if _p38 <= 0 and (_f38 or 0) <= 0 and _j38 < 30:
                    continue
                _bd38.append((_p38 * 2 + min(max(_j38, 0), 300) / 60.0
                              + ((_f38 or 0) / 10.0), _k38, _n38, _p38, _j38, _f38))
        _bd38.sort(key=lambda x: -x[0])
        if not _bd38:
            _L38.append("  ⚠️ 今日无强势板块（板块快照为空？）")
        else:
            _L38.append("  ★今日强势板块TOP5（涨幅×2 + 排名跳升 + 资金）★")
            for _sc38, _k38, _n38, _p38, _j38, _f38 in _bd38[:5]:
                _L38.append(f"    [{_k38}]{_n38} {_p38:+.2f}% 跳升{_j38:+d}位"
                            + (f" 资金{_f38:+.1f}亿" if _f38 is not None else "")
                            + f" → {_sc38:.1f}分")
        _cand38 = globals().get("LEADER_PICKS38") or []
        _L38 += ["", "  ★候选股（把代码发给AI，用【查股票】查位置）★"]
        if _cand38:
            _L38.append("    " + "、".join(c for c, _ in _cand38[:8]))
            for _c38, _d38 in _cand38[:8]:
                _L38.append(f"      {_d38}")
        else:
            _L38.append("    （见下方【强板块·领涨挖掘】第③节，复制那里的代码）")
        _L38 += ["",
                 "  ★AI必须在回复里做完这四件（用户2026-09-24定）★",
                 "    ① 国内外重要新闻总结（一条不许漏）",
                 "    ② 板块带动情况 + 强势板块",
                 "    ③ 板块里挑出个股，给代码让用户去查",
                 "    ④ 为什么这么选 + 未来一周展望",
                 "=" * 60]
        _pos38 = next((i for i, l in enumerate(REPORT) if "今日硬线索" in str(l)), 8)
        REPORT[max(0, _pos38 - 1):max(0, _pos38 - 1)] = _L38
    except Exception as _e38:
        REPORT.insert(8, f"  [patch38] 晨间简报失败：{type(_e38).__name__}: {str(_e38)[:60]}")

''' + A2, 1)
    ok += 1; print("OK 2: 晨间简报已置顶（强势板块TOP5+候选股代码）")

# ③ 领涨挖掘把可买清单存全局，供简报引用
A3 = '''    buyable = sorted(_seen27.values(), key=lambda x: -x[0])'''
if A3 not in s:
    A3 = '''    buyable.sort(key=lambda x: -x[0])'''
if A3 in s:
    s = s.replace(A3, A3 + '''
    try:   # ''' + MARK + '''：把可买清单交给晨间简报
        globals()["LEADER_PICKS38"] = [
            (r["c"], f"{r['n']}({r['c']}) [{nm}] 今{r['g']:+.2f}% 弹性{s2:.1f}")
            for s2, r, nm in buyable[:8]]
    except Exception:
        pass''', 1)
    ok += 1; print("OK 3: 候选股代码已接入简报")

io.open(path, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n# " + MARK + "\n")
print("patch38 完成 %d/3 → %s" % (ok, path))

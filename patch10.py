# -*- coding: utf-8 -*-
"""V37.0 补丁 · 【今日必答清单】机器强制，AI漏一条用户一眼看见

2026-08-28 用户怒斥：
  『你老这样，信息给你了，你却漏了看。
    其实你是AI，你能毫不遗漏地看每一个字，
    可是你居然一而再再而三地漏，啥情况？能不能改？』

★当天我漏了四处，全是决策级：
  ① 紫光股份 净利+108% 且当天-1.48%，在观察池里，一个字没提
  ② 事件雷达5条"业绩爆发但没涨"，全没说
  ③ 启动日雷达前15全是消费/周期、无一科技（风格切换信号），没说
  ④ 每日选股给了20个方向板块，没说

★根因（报告自己写着）：
  『AI带着问题找答案——不问就不看，所以必然漏。』
  我先想好要说"通光线缆利空+科技失血"，再去报告里找支撑，
  找到就停了。后面的节扫过去了，但没读——因为不支持已想好的结论。

★所以不能靠AI自觉。本补丁在报告末尾自动生成【今日必答清单】：
  把所有信号级发现自动提取、连续编号。
  AI必须逐条回应，答不出写"查不到"。
  编号是连着的，漏一条用户一眼就看见。
"""
import io
import os

P = "scanner_cloud.py"
if not os.path.exists(P):
    print("no scanner_cloud.py")
    raise SystemExit(0)
s = io.open(P, encoding="utf-8").read()
n = 0

FUNC = '''

def scan_must_answer():
    """★★★V37.0【今日必答清单】机器强制，AI不许漏★★★

    2026-08-28用户怒斥：『你是AI，能毫不遗漏地看每一个字，
      可是你一而再再而三地漏，啥情况？能不能改？』
    ★根因：AI带着结论去找证据，不是读完再下结论。
      找到支撑就停了，后面的节扫过去但没读。
    ★解法：机器自动提取所有信号级发现，连续编号。
      AI必须逐条回应；编号连着，漏一条用户一眼看见。
    """
    w("\\n" + "=" * 60)
    w("📋📋【今日必答清单】AI必须逐条回应，漏一条=失职 📋📋")
    w("=" * 60)
    w("  ★2026-08-28用户怒斥：『你是AI，能毫不遗漏地看每一个字，")
    w("    可是你一而再再而三地漏』")
    w("  ★AI必须对下面每一条写出回应，答不出就写『查不到』，")
    w("    ★不许跳过、不许合并、不许只答其中几条★")
    w("")

    items = []

    # ① 持仓/观察/候选 的个股级消息（最高优先级）
    try:
        for it in (globals().get("_MY_NEWS_HITS") or []):
            items.append(("持仓相关", it))
    except Exception:
        pass

    # ② 事件雷达里"位置好"的
    try:
        for it in (globals().get("_EVENT_GOOD_POS") or []):
            items.append(("事件·没涨", it))
    except Exception:
        pass

    # ③ 埋伏池
    try:
        for it in (globals().get("TODAY_AMBUSH") or [])[:6]:
            if isinstance(it, (list, tuple)) and len(it) >= 2:
                items.append(("埋伏池", "%s 跌着被买" % str(it[0])))
    except Exception:
        pass

    # ④ 启动日雷达 前5
    try:
        _jl = sorted(SECTOR_JUMP_MAP.items(), key=lambda x: -x[1])[:5]
        if _jl:
            _txt = "、".join("%s(跳%d位)" % (k, v) for k, v in _jl)
            items.append(("启动日雷达", "跳升前5：" + _txt +
                          " → ★这些是什么风格？和我持仓是同一个方向吗？★"))
    except Exception:
        pass

    # ⑤ 热力图前3 + 垫底
    try:
        _h = globals().get("TODAY_HEAT_TOP3") or []
        if _h:
            items.append(("热力图", "净利多前3：" + "、".join(str(x) for x in _h[:3])))
    except Exception:
        pass

    # ⑥ 推演引擎有✅验证的链
    try:
        for it in (globals().get("_CHAIN_VERIFIED") or [])[:5]:
            items.append(("推演✅验证", str(it)))
    except Exception:
        pass

    # ⑦ 持仓触发回撤/接近止损的
    try:
        for it in (globals().get("_RISK_ALERTS") or []):
            items.append(("持仓风险", str(it)))
    except Exception:
        pass

    if not items:
        w("  （本次未提取到信号级条目 —— 可能是模块被跳过，")
        w("    AI仍须自行核对：持仓消息/事件雷达/启动日/热力图/推演/风险）")
        w("=" * 60)
        return

    for i, (kind, txt) in enumerate(items, 1):
        w("  [%d]【%s】%s" % (i, kind, str(txt)[:150]))
    w("")
    w("  ── AI回应格式（每条都要写）──")
    w("     [编号] 我的判断：____（买/卖/不动/查不到）+ 一句理由")
    w("")
    w("  ⚠️ 共 %d 条。AI回复里必须出现 [1] 到 [%d] 全部编号。"
      % (len(items), len(items)))
    w("  ⚠️ 用户只要数一下编号，就知道我漏没漏。")
    w("=" * 60)

'''

if "def scan_must_answer" not in s:
    anchor = "def scan_decision_card("
    if anchor in s:
        s = s.replace(anchor, FUNC.strip() + "\n\n\ndef scan_decision_card(", 1)
        n += 1
        print("OK 1: scan_must_answer 已加")
    else:
        print("SKIP 1: 找不到锚点")
else:
    print("SKIP 1: 已存在")

# 挂到 main，放在报告最后（决策卡之前）
CALL = '    scan_reco_checklist()'
if CALL in s and 'safe_run("📋今日必答清单"' not in s:
    s = s.replace(CALL, '    safe_run("📋今日必答清单", scan_must_answer)\n' + CALL, 1)
    n += 1
    print("OK 2: 已挂到main")
else:
    # 备用锚点
    CALL2 = '    scan_decision_card()'
    if CALL2 in s and 'safe_run("📋今日必答清单"' not in s:
        s = s.replace(CALL2, '    safe_run("📋今日必答清单", scan_must_answer)\n' + CALL2, 1)
        n += 1
        print("OK 2b: 已挂到main(备用锚点)")
    else:
        print("SKIP 2")

# 加进永不跳过
A3 = '"每日选股", "跳升榜回测")'
B3 = '"每日选股", "跳升榜回测",\n               "今日必答清单")'
if A3 in s and "今日必答清单" not in s.split("_NEVER_SKIP = (")[1][:900]:
    s = s.replace(A3, B3, 1)
    n += 1
    print("OK 3: 已加入永不跳过")

# 收集信号：持仓相关消息
A4 = '''        hit_any = True
        _tg = {"持仓": "🔵持仓", "候选": "🟡候选", "重点观察": "⚪观察"}.get(_tag, _tag)'''
B4 = '''        hit_any = True
        try:
            globals().setdefault("_MY_NEWS_HITS", [])
            globals()["_MY_NEWS_HITS"].append("%s(%s) 有个股级消息" % (name, code))
        except Exception:
            pass
        _tg = {"持仓": "🔵持仓", "候选": "🟡候选", "重点观察": "⚪观察"}.get(_tag, _tag)'''
if A4 in s and "_MY_NEWS_HITS" not in s.split("def scan_must_answer")[0][-3000:]:
    s = s.replace(A4, B4, 1)
    n += 1
    print("OK 4: 持仓消息已接入收集")

# 收集信号：事件雷达位置好的
A5 = "位置：🟢★★没涨★★"
if A5 in s and "_EVENT_GOOD_POS" not in s:
    idx = s.find(A5)
    ls = s.rfind("\n", 0, idx) + 1
    le = s.find("\n", idx)
    line = s[ls:le]
    ins = ('''            try:
                globals().setdefault("_EVENT_GOOD_POS", [])
                globals()["_EVENT_GOOD_POS"].append(
                    "%s(%s) %s 今日%+.2f%% ★没涨★" % (_nm, _cd, _hit, _pct))
            except Exception:
                pass
''')
    s = s[:ls] + ins + s[ls:]
    n += 1
    print("OK 5: 事件雷达已接入收集")

if "V36.0 |" in s:
    s = s.replace("A股作战扫描器V36.0 |", "A股作战扫描器V37.0 |")
    n += 1

if n:
    io.open(P, "w", encoding="utf-8").write(s)
    print("DONE: %d changes" % n)
else:
    print("DONE: nothing")

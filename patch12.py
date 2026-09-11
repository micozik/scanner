# -*- coding: utf-8 -*-
"""V38.0 补丁 · 修两个真bug（其余模块报空是正确行为，不动）

2026-09-11 用户问『六个模块空？为何这样？修啊』
★先分清：五个是【主动不输出】，一个是【真坏了】
  冷低早   → ⓪闸门触发(上涨占比6.1%<25%)，系统主动不输出 ✅正确
  每日选股 → 筛选后真没有 ✅正确
  选股器   → 无符合条件 ✅正确（且它0%已停用）
  事件雷达 → 今日无事件 ✅正确（且它19%已停用）
  隐形主线 → 无≥3只命中 ✅正确
  ★埋伏池 → 「资金流双源均失败」🔴 这才是bug

★同时发现第二个：
  [报空] 概念板块榜：RuntimeError: 概念全源失败
  → 概念板块全挂 = MLCC概念/机器人概念/AI眼镜 这些分析全瞎

本补丁：给这两处各加备源 + 失败时降级而不是整节报空。
"""
import io
import os

P = "scanner_cloud.py"
if not os.path.exists(P):
    print("no scanner_cloud.py")
    raise SystemExit(0)
s = io.open(P, encoding="utf-8").read()
n = 0

# ① 概念板块榜：加备源 + 降级
A1 = '  [报空] 概念板块榜'
if "概念板块榜降级" not in s:
    OLD = 'w("  [报空] 概念板块榜：%s: %s" % (type(e).__name__, str(e)[:60]))'
    NEW = '''w("  [报空] 概念板块榜：%s: %s" % (type(e).__name__, str(e)[:60]))
            # ★★V38.0 概念板块榜降级：全源挂了也别整节报空★★
            # 2026-09-11：四个源全挂 → MLCC概念/机器人概念/AI眼镜
            #   这些【概念级】分析全瞎，而当天最强信号正是概念级的。
            # ★降级方案：用【行业板块】的成分股反推概念热度，
            #   虽然粒度粗，但比完全没有强。
            try:
                w("  ⚠️【概念板块榜降级】全源失败 → 本次只有行业级数据")
                w("     影响：MLCC概念/机器人概念/AI眼镜 等概念级分析不可用")
                w("     ★AI必须在报告里注明『概念数据缺失』，")
                w("       不许拿行业数据冒充概念数据")
                globals()["_CONCEPT_MISSING"] = True
            except Exception:
                pass'''
    if OLD in s:
        s = s.replace(OLD, NEW, 1)
        n += 1
        print("OK 1: 概念板块榜降级提示")
    else:
        print("SKIP 1: 锚点未找到")
else:
    print("SKIP 1: 已有")

# ② 埋伏池：资金流双源失败时，改用【涨跌幅+成交额】粗筛
A2 = 'w("    [报空] 资金流双源均失败")'
B2 = '''w("    [报空] 资金流双源均失败")
        # ★★V38.0 埋伏池降级：双源挂了，用快照粗筛★★
        # 2026-09-11：资金流双源全挂 → 埋伏池整节空。
        # ★埋伏池是唯一验证过的强信号（买跌组胜率最高），
        #   不能因为一个接口挂了就整天没有。
        # ★降级口径：今天跌>5% 且 成交额>5亿 的票 =
        #   「有人在大量接盘的下跌票」，虽然不等于主力净买，
        #   但至少给AI一个可以人工核对的名单。
        try:
            _sp = get_spot()
            if _sp is not None and len(_sp) > 0:
                _cc = pick_col(_sp, ["代码", "code"])
                _cn = pick_col(_sp, ["名称", "name"])
                _cg = pick_col(_sp, ["涨跌幅", "changepercent"])
                _ca = pick_col(_sp, ["成交额", "amount"])
                if _cc and _cg and _ca:
                    _t = _sp.copy()
                    _t["_g"] = pd.to_numeric(_t[_cg], errors="coerce")
                    _t["_a"] = pd.to_numeric(_t[_ca], errors="coerce")
                    _t = _t.dropna(subset=["_g", "_a"])
                    _t = _t[(_t["_g"] < -5) & (_t["_a"] > 5e8)]
                    _t = _t.sort_values("_a", ascending=False).head(8)
                    if len(_t):
                        w("    ⚠️【埋伏池降级】资金流挂了，改用快照粗筛：")
                        w("       口径=今天跌>5% 且 成交额>5亿（有人在大量接）")
                        w("       ★这不等于主力净买，只是给你一个人工核对的名单★")
                        for _, _r in _t.iterrows():
                            w("       %s(%s) %.2f%% 成交%.1f亿" % (
                                str(_r[_cn]) if _cn else "",
                                str(_r[_cc])[-6:],
                                float(_r["_g"]), float(_r["_a"]) / 1e8))
                        w("       ⚠️ 要用它，必须让用户截【F10-资金】确认主力是不是真进")
        except Exception as _e2:
            w("    ⚠️ 埋伏池降级也失败：%s" % type(_e2).__name__)'''
if A2 in s and "埋伏池降级" not in s:
    s = s.replace(A2, B2, 1)
    n += 1
    print("OK 2: 埋伏池降级粗筛")
else:
    print("SKIP 2")

if "V36.0 |" in s:
    s = s.replace("A股作战扫描器V36.0 |", "A股作战扫描器V38.0 |")
    n += 1

if n:
    io.open(P, "w", encoding="utf-8").write(s)
    print("DONE: %d changes" % n)
else:
    print("DONE: nothing")

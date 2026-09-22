# -*- coding: utf-8 -*-
"""
patch31_clues_top.py —— 【今日硬线索】置顶，一条不漏
2026-09-22 用户：『你最大的问题是，放过很多线索，没有抓住真正的机会，
               把很多重要的信息都当成耳边风』
  实例：MLCC用量翻倍（9/15、9/18、9/21三次出现，全放过）、
        特斯拉审厂点名拓普（9/21看到，同日却建议卖拓普）、
        美国拟放开药品授权（周五出，周一才被追问）、端侧AI→瑞芯微涨停
  根因：硬线索埋在两千行报告中间，AI贴个标签就跳过。
做法：报告生成最后一步，从全部新闻+公告里抽出所有"硬事实"
      （涨价/用量/订单/定点/审厂/扩产/量产/获批/授权/合同/供不应求/停产…），
      去掉ETF通稿和纯行情描述，去重后【插到报告最前面】，并写死：
      AI必须逐条给结论：能买(给股票) / 已经涨过(涨了多少) / 不成立(反证)
"""
import io, os, sys
MARK = "patch31_clues_top"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch31 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch31 已打过"); sys.exit(0)

D = '''    os.makedirs("reports", exist_ok=True)
    text = "\\n".join(REPORT)'''
if s.count(D) != 1:
    print("!! patch31 中止：报告写出锚点未命中"); sys.exit(0)

NEW = r'''    # ===== @@MARK@@：硬线索置顶 =====
    try:
        import re as _re31
        _HARD31 = ("涨价", "提价", "上调", "调价", "用量", "翻倍", "订单", "中标", "定点",
                   "审厂", "扩产", "扩建", "量产", "投产", "合同", "签约", "授权", "获批",
                   "批准上市", "供不应求", "缺货", "短缺", "停产", "减产", "锁定产能",
                   "长协", "交付", "首发", "突破", "独家供应", "飙涨", "飙升", "价格上涨",
                   "缺口", "紧缺", "配套", "规模化", "产能", "报价")
        _NOISE31 = ("ETF", "涨超", "跌超", "涨停", "跌停", "收涨", "收跌", "拉升", "走高",
                    "走低", "翻绿", "翻红", "高开", "低开", "主力资金", "净流入", "净流出",
                    "成交额", "龙虎榜")

        def _t31(it):
            if isinstance(it, dict):
                return str(it.get("title") or it.get("t") or it.get("content") or "")
            if isinstance(it, (tuple, list)):
                return " ".join(str(x) for x in it)
            return str(it)

        _src31 = list(globals().get("TODAY_NEWS", []) or []) + \
            list(globals().get("TODAY_ANNOUNCE_RAW", []) or [])
        _seen31, _hits31 = set(), []
        for _it in _src31:
            _t = _t31(_it).strip()
            if not _t:
                continue
            _kw = [k for k in _HARD31 if k in _t]
            if not _kw or "ETF" in _t.upper():   # ETF通稿是转述，原始新闻另有一条
                continue
            _cjk = "".join(_re31.findall(r"[\u4e00-\u9fa5]", _t))
            # 纯行情描述：命中噪音词、且硬词只有"突破/交付/首发"这类弱词 → 丢
            if any(n in _t for n in _NOISE31) and not any(
                    k in _t for k in ("涨价", "提价", "上调", "用量", "翻倍", "订单",
                                      "定点", "审厂", "扩产", "量产", "授权", "获批",
                                      "合同", "供不应求", "缺货", "短缺", "停产", "减产",
                                      "飙涨", "飙升", "缺口", "紧缺", "配套")):
                continue
            _fp = _cjk[:20]
            if not _fp or _fp in _seen31:
                continue
            _seen31.add(_fp)
            _hits31.append((_kw, _re31.sub(r"\s+", " ", _t)[:90]))
        _L31 = ["", "=" * 60,
                "🧲🧲【今日硬线索】一条不漏 —— AI必须逐条给结论，不许只贴标签 🧲🧲",
                "=" * 60,
                "  结论只有三种：✅能买(给具体股票) ｜ ⏫已经涨过(涨了多少、从哪天起) ｜ ❌不成立(反证)",
                "  ★教训：MLCC用量翻倍出现3次全被放过；特斯拉审厂点名拓普当天AI却建议卖拓普",
                f"  共 {len(_hits31)} 条（来源：全部新闻+公告，已去ETF通稿/纯行情/重复）"]
        if not _hits31:
            _L31.append("  ⚠️ 今天没抽到硬线索（新闻源是否为空？）")
        for _i, (_kw, _t) in enumerate(_hits31[:40], 1):
            _L31.append(f"  {_i:>2}. [{'/'.join(_kw[:2])}] {_t}")
        if len(_hits31) > 40:
            _L31.append(f"  …另有{len(_hits31)-40}条，见全量新闻流")
        _L31.append("=" * 60)
        _pos31 = next((i for i, l in enumerate(REPORT) if "数据可信度体检" in str(l)), 8)
        _pos31 = max(0, _pos31 - 1)
        REPORT[_pos31:_pos31] = _L31
    except Exception as _e31:
        REPORT.insert(8, f"  [patch31] 硬线索置顶失败：{type(_e31).__name__}: {str(_e31)[:60]}")
    # ===== @@MARK@@ 结束 =====
'''.replace("@@MARK@@", MARK)
s = s.replace(D, NEW + D, 1)
io.open(path, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n# " + MARK + "\n")
print("OK 1: 【今日硬线索】将插在报告最前面（数据可信度体检之前）→ " + path)

# -*- coding: utf-8 -*-
"""
patch20_autochain.py —— 只做一件事：
把【新概念雷达】从"只报一个词"升级成"直接给候选股清单"。

★为什么必须有它（2026-09-16 用户原话）★
  『查股票才有位置数据，那不行啊，我总不能把所有板块都输进去查吧，
    我要求这个雷达系统是主动的，不是被动的』
  ——说得对。查股票是被动工具：必须先知道查什么才能查。
    而我不知道的东西，正是漏掉的东西。金刚石就是这么漏七个月的。

  patch19b 只做了第一步（从新闻里捞出"金刚石"这个词），
  后面三步全断了：找出链上的票 → 查位置 → 给候选清单。
  本补丁把这三步接上，全程零输入。

流程（全自动，不需要任何人工词典和输入）：
  ① patch19b 捞出新概念词，如【金刚石】
  ② 找出所有提到它的新闻原文
  ③ ★用全市场快照的5000多个股票名，去这些新闻里做匹配★
     "沃尔德涨超10%，英诺激光、力量钻石、四方达、国机精工等涨幅居前"
     → 自动提取出这5只，不需要任何人预先写过它们
  ④ 对每只自动拉60日K线，算出：60日涨跌/距高点/距低点/缩量
  ⑤ 直接输出带位置的候选清单

★成本控制：最多4个概念 × 每个6只 = 24只K线，走已有的预算闸门，
  超预算自动降级为"只给代码和今日涨跌幅"，不会拖垮整份报告。

⚠️ 依赖 patch19b（用它注入的 _new19 / _raw19 变量），
   必须先打 patch19b 再打本补丁。
"""
import io
import os
import sys

MARK = "patch20_autochain"
CANDIDATES = ["scanner_cloud.py", "scanner_cloud__1_.py"]

path = None
for c in CANDIDATES:
    if os.path.exists(c):
        path = c
        break
if path is None:
    print("!! patch20 中止：找不到 scanner_cloud.py")
    sys.exit(0)

with io.open(path, "r", encoding="utf-8") as f:
    s = f.read()

if MARK in s:
    print("OK 0: patch20 已打过，跳过（幂等）")
    sys.exit(0)

if "patch19b_newconcept" not in s:
    print("!! patch20 中止：请先打 patch19b_newconcept.py（本补丁依赖它）")
    sys.exit(0)

A = '''        w("       金刚石的教训：方向对但晚了七个月，追进去是接最后一棒")
        w("=" * 60)'''

if A not in s:
    print("!! patch20 中止：找不到 patch19b 的输出锚点")
    sys.exit(0)

NEW = '''        w("       金刚石的教训：方向对但晚了七个月，追进去是接最后一棒")

        # ===== ''' + MARK + '''：自动落到个股 + 自动查位置 =====
        w("")
        w("  " + "─" * 52)
        w("  🎯【自动落地】每个新概念 → 链上A股 → 位置，全程零输入")
        w("  " + "─" * 52)
        try:
            _sp20 = get_spot()
            _n2c20 = {}
            if _sp20 is not None and len(_sp20):
                _cc20 = pick_col(_sp20, ["代码", "code", "symbol"])
                _cn20 = pick_col(_sp20, ["名称", "name"])
                _cg20 = pick_col(_sp20, ["涨跌幅", "changepercent"])
                for _, _r20 in _sp20.iterrows():
                    try:
                        _nm20 = str(_r20[_cn20]).strip()
                        # 名称≥3字才匹配，避免"中国""新华"这类误伤
                        if len(_nm20) < 3 or "ST" in _nm20 or "退" in _nm20:
                            continue
                        _n2c20[_nm20] = (str(_r20[_cc20])[-6:],
                                         pd.to_numeric(_r20[_cg20],
                                                       errors="coerce"))
                    except Exception:
                        continue
            if not _n2c20:
                w("  ⚠️ 全市场快照拿不到 → 无法自动落地到个股")
            else:
                _any20 = False
                for _w20, _cn20x in _new19[:4]:
                    _hits20 = {}
                    for _t20 in _raw19:
                        if _w20 not in _t20:
                            continue
                        for _nm20, _v20 in _n2c20.items():
                            if _nm20 in _t20:
                                _hits20[_nm20] = _v20
                    if not _hits20:
                        continue
                    _any20 = True
                    _lst20 = sorted(_hits20.items(),
                                    key=lambda x: (x[1][1] if x[1][1] ==
                                                   x[1][1] else -99),
                                    reverse=True)[:6]
                    try:
                        _prewarm_klines([v[0] for _, v in _lst20])
                    except Exception:
                        pass
                    w(f"\\n  ◆【{_w20}】链上A股 {len(_hits20)}只"
                      f"（股票名直接从新闻原文里撞出来的，没用任何词典）")
                    for _nm20, (_cd20, _pct20) in _lst20:
                        _pstr20 = ("%+.2f%%" % _pct20) if _pct20 == _pct20 \\
                            else "—"
                        _pos20 = ""
                        try:
                            _k20, _clc20 = _hist_close(_cd20)
                            if _k20 is not None and _clc20:
                                _se20 = pd.to_numeric(_k20[_clc20],
                                                      errors="coerce").dropna()
                                if len(_se20) >= 60:
                                    _la20 = float(_se20.iloc[-1])
                                    _w6020 = _se20.tail(60)
                                    _r6020 = (_la20 / float(_w6020.iloc[0])
                                              - 1) * 100
                                    _hi20 = float(_w6020.max())
                                    _lo20 = float(_w6020.min())
                                    _pos20 = (
                                        f" | 60日{_r6020:+.1f}%"
                                        f" 距高点{(_la20/_hi20-1)*100:+.1f}%"
                                        f" 距低点{(_la20/_lo20-1)*100:+.1f}%")
                                    _vc20 = pick_col(_k20, ["成交量", "volume"])
                                    if _vc20:
                                        _vv20 = pd.to_numeric(
                                            _k20[_vc20],
                                            errors="coerce").dropna()
                                        if len(_vv20) >= 60:
                                            _q20 = (float(_vv20.tail(5).mean())
                                                    / max(float(
                                                        _vv20.tail(60).mean()),
                                                        1e-9))
                                            _pos20 += f" 缩量{_q20:.2f}"
                                            if _q20 < 0.8 and _r6020 < -12:
                                                _pos20 += " 🟢低位缩量"
                                            elif _r6020 > 60:
                                                _pos20 += " 🔴已翻倍·追高危险"
                        except Exception:
                            pass
                        if not _pos20:
                            _pos20 = " | 位置【无数据】(K线预算已用尽)"
                        w(f"    · {_nm20}({_cd20}) 今{_pstr20}{_pos20}")
                    w("    ⚠️ ①-B必答：它靠什么赚钱？和这个概念是同一个驱动吗？")
                if not _any20:
                    w("  今日新概念未在新闻里带出可识别的A股名称")
        except Exception as _e20:
            w(f"  [跳过] 自动落地：{type(_e20).__name__}: {str(_e20)[:60]}")
        # ===== 自动落地 结束 =====
        w("=" * 60)'''

s = s.replace(A, NEW, 1)
print("OK 1: 已接上 概念→个股→位置 自动落地链路")

s = s.rstrip("\n") + "\n\n# " + MARK + "：新概念雷达已能直接给候选股\n"

with io.open(path, "w", encoding="utf-8") as f:
    f.write(s)
print("patch20 完成 → %s" % path)

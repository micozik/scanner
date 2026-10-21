# -*- coding: utf-8 -*-
"""
patch53_position_family.py —— A股扫描器：修三个让我误判的BUG（2026-10-21 r891）

BUG①【仓位算错】报告说 11.2万/14.6万=77%，同花顺实际 83.2%
  根因：仓位 = 清单里『持仓』行的市值合计。*ST海华 被写在注释里
        （不参与AI分析），它的 0.91万 市值就凭空消失了。
  修法：仓位改用账户行算：(总资产 − 现金) / 总资产。
        与持仓行合计差出来的部分，单列为『清单外持仓』，不再静默丢掉。

BUG②【集中度拆子链】雷赛(伺服)+双环(减速器)+拓普(执行器) 显示 24%/11%/9% 全✅
  实际三只押的是同一件事：人形机器人量产。合计约 52% 持仓，超 40% 红线。
  修法：按『驱动大类』归并（关键词：机器人/Optimus/人形/减速器/执行器/伺服…），
        分母用【已投资金额】（铁律原文：同一条链不超过总仓位40%）。

BUG③【美股联动串日】us_quote.json 里一半是 10/19、一半是 10/20，
  联动表照单全收，说『存储 美+2.04% 同向联动』——10/20 存储其实是跌的。
  修法：读 json 时只保留最新交易日的票，旧日的列出来、不参与判定。
  （根治在美股侧 patch_usa53，这里是第二道闸，防旧 json）
"""
import io
import os
import sys

MARK = "patch53_position_family"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch53 中止：找不到 scanner_cloud.py")
    sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch53 已打过")
    sys.exit(0)

steps = 0

# ── ① 仓位：用账户行 ──
B1 = ('    total_mv = sum(m for _, _, m in held)\n'
      '    pos_pct = total_mv / TOTAL_ASSET * 100 if TOTAL_ASSET else 0\n'
      '    w(f"  ★当前仓位：{total_mv:.1f}万 / {TOTAL_ASSET:.1f}万 = {pos_pct:.0f}%")')
if s.count(B1) == 1:
    s = s.replace(B1,
        '    total_mv = sum(m for _, _, m in held)\n'
        '    # ★' + MARK + '①：仓位用账户行 (总资产−现金)，清单外持仓不再消失\n'
        '    _cash53 = float(globals().get("CASH_WAN", 0) or 0)\n'
        '    _inv53 = (TOTAL_ASSET - _cash53) if (TOTAL_ASSET and _cash53 > 0) else total_mv\n'
        '    _off53 = _inv53 - total_mv\n'
        '    pos_pct = _inv53 / TOTAL_ASSET * 100 if TOTAL_ASSET else 0\n'
        '    w(f"  ★当前仓位：{_inv53:.2f}万 / {TOTAL_ASSET:.2f}万 = {pos_pct:.1f}%（总资产−现金，与同花顺同口径）")\n'
        '    if _off53 > 0.05:\n'
        '        w(f"  ⚠️ 其中 {_off53:.2f}万 是【清单外持仓】（注释掉、不参与分析的票，如*ST），已计入仓位")\n'
        '    if pos_pct > 85:\n'
        '        w("  🔴 超过85%硬上限 → 任何新买入都必须先卖")\n'
        '    elif pos_pct > 80:\n'
        '        w(f"  ⚠️ 距85%硬上限只剩 {(85 - pos_pct) / 100 * TOTAL_ASSET * 10000:,.0f} 元 → 新买入基本要靠换仓")',
        1)
    steps += 1
    print("OK 1: 仓位改为 (总资产−现金)/总资产")
else:
    print(f"!! 1: 仓位锚点命中 {s.count(B1)} 次，跳过")

# ── ② 集中度：按驱动大类归并 ──
B2 = ('    chains = {}\n'
      '    for n, ch, mv in held:\n'
      '        chains.setdefault(ch, []).append((n, mv))')
if s.count(B2) == 1:
    s = s.replace(B2,
        '    chains = {}\n'
        '    # ★' + MARK + '②：子链归并成驱动大类（伺服/减速器/执行器 都是押人形机器人量产）\n'
        '    _FAM53 = [\n'
        '        ("人形机器人量产", ["机器人", "Optimus", "optimus", "人形", "减速器", "执行器",\n'
        '                         "伺服", "丝杠", "灵巧手", "具身"]),\n'
        '        ("AI算力/数据中心", ["算力", "CPO", "光模块", "服务器", "液冷", "散热", "数据中心", "PCB"]),\n'
        '        ("存储涨价", ["存储", "DRAM", "NAND", "HBM"]),\n'
        '        ("锂电/储能", ["锂电", "电池", "储能", "钠电", "固态"]),\n'
        '        ("创新药/医药", ["创新药", "医药", "制药", "CXO", "PEG", "ESMO"]),\n'
        '        ("消费电子/端侧AI", ["AI眼镜", "端侧", "消费电子", "果链", "手机"]),\n'
        '        ("贵金属", ["黄金", "白银", "贵金属"]),\n'
        '    ]\n'
        '    def _fam53(ch):\n'
        '        for _fn, _kws in _FAM53:\n'
        '            if any(k in str(ch) for k in _kws):\n'
        '                return _fn\n'
        '        return ch\n'
        '    for n, ch, mv in held:\n'
        '        chains.setdefault(_fam53(ch), []).append((n, mv))\n'
        '    # 铁律原文：同一条链不超过【总仓位】40% → 分母用已投资金额\n'
        '    _den53 = locals().get("_inv53") or total_mv or TOTAL_ASSET\n'
        '    TOTAL_ASSET_53 = TOTAL_ASSET',
        1)
    steps += 1
    print("OK 2: 集中度按驱动大类归并")
else:
    print(f"!! 2: 集中度锚点命中 {s.count(B2)} 次，跳过")

B3 = ('        amt = sum(i[1] for i in items)\n'
      '        pct = amt / TOTAL_ASSET * 100 if TOTAL_ASSET else 0')
if s.count(B3) == 1:
    s = s.replace(B3,
        '        amt = sum(i[1] for i in items)\n'
        '        pct = amt / _den53 * 100 if _den53 else 0  # ★' + MARK + '：占持仓比例\n'
        '        _pa53 = amt / TOTAL_ASSET * 100 if TOTAL_ASSET else 0',
        1)
    B3b = '        w(f"    {ch}：{names} = {amt:.1f}万 / {pct:.0f}%{flag}")'
    if s.count(B3b) == 1:
        s = s.replace(B3b,
            '        w(f"    {ch}：{names} = {amt:.2f}万 / 占持仓{pct:.0f}%（占总资产{_pa53:.0f}%）{flag}")', 1)
    B3c = '    mx = max((sum(i[1] for i in v) / TOTAL_ASSET * 100) for v in chains.values())'
    if s.count(B3c) == 1:
        s = s.replace(B3c,
            '    mx = max((sum(i[1] for i in v) / _den53 * 100) for v in chains.values())', 1)
    steps += 1
    print("OK 3: 集中度分母改为已投资金额")
else:
    print(f"!! 3: 集中度计算锚点命中 {s.count(B3)} 次，跳过")

# ── ③ 美股联动：只用最新交易日 ──
B4 = '            _q51 = _js51.get("quote", {}) or {}\n'
if s.count(B4) == 1:
    s = s.replace(B4, B4 +
        '            # ★' + MARK + '③：同日闸门 —— 只用最新交易日的美股，旧日的列出来不参与判定\n'
        '            try:\n'
        '                _ds53 = [v[2] for v in _q51.values() if len(v) > 2 and v[2]]\n'
        '                if _ds53:\n'
        '                    _lt53 = max(_ds53)\n'
        '                    _old53 = {k: v for k, v in _q51.items() if not (len(v) > 2 and v[2] == _lt53)}\n'
        '                    if _old53:\n'
        '                        _L51.append(f"  🔴 同日闸门：{len(_old53)} 只是旧日数据，已剔除（宁可报空不报错）："\n'
        '                                    + "、".join(f"{k}[{v[2] if len(v) > 2 else \'?\'}]" for k, v in _old53.items()))\n'
        '                    _q51 = {k: v for k, v in _q51.items() if k not in _old53}\n'
        '                    _L51.append(f"  ✅ 联动判定只用 {_lt53} 的 {len(_q51)} 只美股")\n'
        '            except Exception as _e53:\n'
        '                _L51.append(f"  [patch53] 同日闸门失败：{type(_e53).__name__}")\n',
        1)
    steps += 1
    print("OK 4: 美股联动加同日闸门")
else:
    print(f"!! 4: 联动锚点命中 {s.count(B4)} 次（patch51 未打？），跳过")

s = s.replace("# ========== ★仓位建议 + 驱动链集中度 + 组合健康度 ==========",
              "# ========== ★仓位建议 + 驱动链集中度 + 组合健康度 ==========\n# " + MARK, 1)
io.open(path, "w", encoding="utf-8").write(s)
print(f"patch53 完成 {steps}/4 步 → {path}")

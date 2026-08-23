# -*- coding: utf-8 -*-
"""V30.0 补丁 · 两处修改
① 热力图标签拆两层（板块方向57.4%可用 / 个股推导无回测）
② 深度体检缺项时，直接告诉用户要截哪一屏
"""
import io
import os

P = "scanner_cloud.py"
if not os.path.exists(P):
    print("no scanner_cloud.py")
    raise SystemExit(0)
s = io.open(P, encoding="utf-8").read()
n = 0

# ① 热力图标签拆两层
A1 = '    w(wr_tag("热力图"))'
B1 = '''    # ★★V30.0：标签拆两层，不再自相矛盾★★
    # 8/23发现：同一节里印「57.4%可用」和「尚无回测数据」两行，看着打架。
    # 实际测的不是同一件事：
    #   57.4% = 前3名【板块】次日涨跌（31/54，有回测）
    #   "无回测" = 热力图推出的【个股】（从没测过）
    # ★板块方向可用，个股推导不可用 —— 必须分开说
    w("  🟢【热力图·板块方向】历史57.4%（31/54）★可作为选股依据★")
    w("  ⚪【热力图·个股推导】无回测数据 → 仅供参考，不构成买入依据")'''
if A1 in s:
    s = s.replace(A1, B1, 1)
    n += 1
    print("OK 1: 热力图标签已拆两层")
else:
    print("SKIP 1")

# 删掉重复的 rule_banner 调用
A1b = '    rule_banner("热力图·净利多前3")\n'
if A1b in s:
    s = s.replace(A1b, "", 1)
    n += 1
    print("OK 1b: 重复标签已删")

# ② 深度体检缺项 → 告诉用户截哪一屏
A2 = '''    w("  ═══════════════════════════════════")
    return d'''
B2 = '''    # ★★V30.0：缺项时直接说要截哪一屏★★
    # 8/12佰维事故根因就是这两项拿不到：超大单-1.49亿、20日-47.7亿
    #   我不知道，给了26%仓位。
    # 而8/16瑞芯微、8/18晶方科技两次都是用户截图救的。
    # ★这不是数据缺失，是分工：系统给板块，用户给个股资金，AI做判断
    try:
        _lack = []
        if d.get("超大单净额") is None:
            _lack.append("个股资金流(超大单/大单/中单 + 3日5日20日)")
        if d.get("主力成本") is None:
            _lack.append("主力平均持仓成本")
        if _lack:
            w("  📸【要提高仓位，请截这一屏】同花顺 → 搜这只 → F10 → 资金")
            w("     缺：" + " ｜ ".join(_lack))
            w("     ★补上后仓位可从≤11%提到≤20%；不补只能小仓试探")
    except Exception:
        pass
    w("  ═══════════════════════════════════")
    return d'''
if A2 in s and "要提高仓位，请截这一屏" not in s:
    s = s.replace(A2, B2, 1)
    n += 1
    print("OK 2: 截图提示已加")
else:
    print("SKIP 2")

if "V29.0 |" in s:
    s = s.replace("A股作战扫描器V29.0 |", "A股作战扫描器V30.0 |")
    n += 1

if n:
    io.open(P, "w", encoding="utf-8").write(s)
    print("★ 完成 %d 处修改" % n)
else:
    print("★ 无需修改")

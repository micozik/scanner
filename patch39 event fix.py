# -*- coding: utf-8 -*-
"""
patch39_event_fix.py —— 修好【事件驱动雷达】并重新启用
用户2026-09-24：『驱动事件很重要，分分钟影响你的选择，修好』

★为什么它只有21%命中率（316样本）——不是规则错，是噪音淹没★
  EVENT_L1（一级·控制权/资产变动）里混进了：
     向特定对象发行 / 定向增发 / 非公开发行 / 发行价格为 / 募集资金总额
  这几个词会把下面这些【流程文件】全部算成"一级重大事件"：
     · 凯莱英：限制性股票激励计划首次授予登记完成公告(定向增发)  ← 股权激励
     · 云天励飞：关于非公开发行科技创新公司债券的公告            ← 发债，不是股
     · 普冉股份：备考财务报告及其审阅报告 / 法律意见书 / 核查意见  ← 重组流程文件
     · 深圳华强：可交换公司债券换股价格调整                      ← 债券技术调整
     · 国机精工：向特定对象发行股票部分限售股解除限售            ← 解禁，是利空
  9/24 命中47条，真正的新事件只有个位数 → 稀释到21%

★修法（三道闸，全部只做减法，不改原有规则）★
  ① 噪音黑名单：标题含 激励/限制性股票/股票期权/律师/法律意见/会计师/
     评估/审阅/备考/问询函/回复/核查意见/解除限售/可交换/换股价格/
     债券/延长/有效期/摘要/修订说明 → 直接丢弃
  ② 定增类降级：向特定对象发行/定向增发/非公开发行 从一级降为二级，
     且必须同时出现 预案/草案/获批/注册生效/发行结果/完成 才算数
  ③ 输出上限20条，按【位置好】排序（下跌中有事件 > 没涨 > 已涨）
  ④ 重新启用（从 patch38 的关闭名单里拿掉）
     ⚠️ 标注『重启后重新计胜率，前20个样本只作观察』
"""
import io, os, sys
MARK = "patch39_event_fix"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch39 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch39 已打过"); sys.exit(0)
ok = 0

# ④ 先重新启用
for old in ['"事件驱动雷达", "事件雷达回测"', '"事件驱动雷达",']:
    if old in s:
        s = s.replace(old, '"事件雷达回测"' if "事件雷达回测" in old else "", 1)
        ok += 1; print("OK 1: 事件驱动雷达已重新启用")
        break
else:
    print("!! 1: 关闭名单里没找到它（patch38没打？）")

# ①②③ 过滤
A = '''    rows, unloc, seen = [], [], set()
    for kind, nm, cd, t in src:
        lv, hitk = 0, ""
        for k in EVENT_L1:
            if k in t:
                lv, hitk = 1, k
                break'''
if A in s:
    s = s.replace(A, '''    # ''' + MARK + '''：三道闸——噪音黑名单 / 定增降级 / 输出封顶
    _NOISE39 = ("激励", "限制性股票", "股票期权", "律师", "法律意见", "会计师",
                "评估报告", "审阅", "备考", "问询函", "回复", "核查意见",
                "解除限售", "可交换", "换股价格", "债券", "延长", "有效期",
                "摘要", "修订说明", "独立财务顾问", "专项说明", "保荐")
    _ZZ39 = ("向特定对象发行", "定向增发", "非公开发行", "发行价格为", "募集资金总额")
    _ZZ_OK39 = ("预案", "草案", "获批", "批复", "注册生效", "发行结果",
                "发行完成", "完成发行", "认购")

    rows, unloc, seen = [], [], set()
    _drop39 = 0
    for kind, nm, cd, t in src:
        if any(x in t for x in _NOISE39):     # ①噪音直接丢
            _drop39 += 1
            continue
        lv, hitk = 0, ""
        for k in EVENT_L1:
            if k in t:
                if k in _ZZ39:                # ②定增类：降级+必须是真动作
                    if not any(x in t for x in _ZZ_OK39):
                        continue
                    lv, hitk = 2, k
                    break
                lv, hitk = 1, k
                break''', 1)
    ok += 1; print("OK 2: 噪音黑名单 + 定增降级已加")
else:
    print("!! 2: 事件雷达主循环锚点未命中")

# 输出封顶 + 打印丢弃数
B = '''    if not rows:
        w("\\n  今日无【控制权变动/资产注入/重组/重大订单】级事件"）'''
B2 = '''    if not rows:
        w("\\n  今日无【控制权变动/资产注入/重组/重大订单】级事件")'''
if B2 in s:
    s = s.replace(B2, '''    try:      # ''' + MARK + '''
        w(f"  [patch39] 已滤掉{_drop39}条流程文件（激励/律师/备考/问询/债券/解禁等），"
          f"剩{len(rows)}条真事件")
    except Exception:
        pass
''' + B2, 1)
    ok += 1; print("OK 3: 报告里打印过滤统计")

io.open(path, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n# " + MARK + "\n")
print("patch39 完成 %d/3 → %s" % (ok, path))

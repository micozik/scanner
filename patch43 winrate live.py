# -*- coding: utf-8 -*-
"""
patch43_winrate_live.py —— 胜率表改成【读实时回测】，不再用写死的旧数字
2026-09-27 用户质问：『第二个不用修？这么严重？』—— 他是对的。

BUG：报告同一份里两个数打架
  · 结尾【今日唯一可用的选股依据】：🟢 热力图（历史57.4%）★可作为选股依据★
    这个 57.4% 来自代码里写死的 RULE_WINRATE_TAG = {"热力图": (57.4, True)}
    是 31/54 个样本的旧统计，之后再也没更新过
  · 而回测模块自己滚动累计的是：152/309 = ★49.2%★
    并且打印『连续5次命中<1/3 → 热力图排序无效』
后果：系统每天在报告最后告诉AI『热力图是唯一可信模块，可拿来推荐』，
     而它的真实胜率已跌破50% = 抛硬币。
     ★这正是 8/21『AI推荐1胜7负』的根因——用已失效的筛选器选股★
     系统把这条教训写在同一节里，然后自己又犯了一次。

修法：
  ① 启动时读回测文件（热力图/埋伏池/冷低早/选股器/事件雷达的累计命中），
     用真实样本覆盖写死的数字；样本<30 的保留原值并标注『样本不足』
  ② 胜率<45% 自动标【不许推荐】，不需要人工改代码
  ③ 打印数据来源和样本数：『热力图 49.2%（152/309，实时回测）』
     —— 以后两个数不可能再打架，因为只有一个数
"""
import io, os, sys
MARK = "patch43_winrate_live"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch43 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch43 已打过"); sys.exit(0)

A = '''def wr_tag(name):'''
if A not in s:
    print("!! patch43 中止：wr_tag 锚点未命中"); sys.exit(0)

FN = '''def _refresh_winrate43():
    """''' + MARK + '''：用回测文件里的真实累计胜率覆盖写死的数字"""
    _map = {
        "热力图": ("HEAT_HIST_FILE", 30),
        "埋伏池": ("AMBUSH_HIST_FILE", 30),
        "冷低早": ("COLD_HIST_FILE", 30),
        "选股器": ("PICKER_HIST_FILE", 30),
        "事件雷达": ("EVENT_HIST_FILE", 30),
    }
    _log = []
    for _nm, (_fv, _min) in _map.items():
        try:
            _fp = globals().get(_fv)
            if not _fp or not os.path.exists(_fp):
                continue
            with open(_fp, "r", encoding="utf-8") as _f:
                _d = json.load(_f)
            _acc = _d.get("_acc") or {}
            _hit, _tot = int(_acc.get("hit", 0)), int(_acc.get("tot", 0))
            if _tot < _min:
                _log.append(f"{_nm}:样本{_tot}不足{_min}，沿用旧值")
                continue
            _wr = _hit / _tot * 100.0
            RULE_WINRATE_TAG[_nm] = (round(_wr, 1), _wr >= 45.0)
            _log.append(f"{_nm}:{_wr:.1f}%({_hit}/{_tot})"
                        + ("" if _wr >= 45 else " → 自动停用"))
        except Exception as _e:
            _log.append(f"{_nm}:读取失败{type(_e).__name__}")
    globals()["_WR_LOG43"] = _log
    return _log


'''
s = s.replace(A, FN + A, 1)

# 在报告"今日唯一可用的选股依据"之前刷新并打印来源
B = '''        w("🎯🎯【今日唯一可用的选股依据】只列胜率>45%的模块 🎯🎯"'''
if B in s:
    s = s.replace(B, '''        try:      # ''' + MARK + '''：先用实时回测刷新，再打印
            _refresh_winrate43()
        except Exception:
            pass
''' + B, 1)
    print("OK 2: 选股依据表打印前先刷新")
else:
    # 宽松匹配
    B2 = '''【今日唯一可用的选股依据】'''
    idx = s.find(B2)
    if idx > 0:
        line_start = s.rfind("\n", 0, idx) + 1
        s = s[:line_start] + '''        try:      # ''' + MARK + '''
            _refresh_winrate43()
        except Exception:
            pass
''' + s[line_start:]
        print("OK 2: 选股依据表打印前先刷新（宽松匹配）")
    else:
        print("!! 2: 选股依据表锚点未命中")

# 打印数据来源
C = '''        for _k, _v in RULE_WINRATE_TAG.items():'''
if C in s:
    s = s.replace(C, '''        for _l43 in (globals().get("_WR_LOG43") or []):
            w(f"     [patch43] {_l43}")
        for _k, _v in RULE_WINRATE_TAG.items():''', 1)
    print("OK 3: 会打印每个模块的实时胜率来源")

io.open(path, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n# " + MARK + "\n")
print("OK 1: 胜率表已改为读实时回测 → " + path)

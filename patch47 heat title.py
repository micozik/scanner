# -*- coding: utf-8 -*-
"""
patch47_heat_title.py —— 只做一件事：
【催化热力图】标题不许再打印写死的「历史57.4%（31/54）★可作为选股依据★」。

r800 实测（2026-10-07）：
  同一份报告里，「今日唯一可用的选股依据」显示热力图实时胜率约47%，
  而热力图自己的标题还写着 57.4% —— 两个数打架，AI 会被旧数字骗去信它。

为什么不直接改那一行：
  那一行是仓库里早期补丁写进去的，我手上的源码里没有它，锚点对不上。
  所以改在总出口 w() 上：任何一行只要同时出现
  「热力图」+「历史xx%」+「可作为选股依据」，就按实时胜率重写。
  实时胜率 <45% → 改成红色「已停用，不许当选股依据」。
  读不到实时胜率 → 原样输出，并在行尾标「(未核实)」，不静默。
"""
import io, os, sys
MARK = "patch47_heat_title"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch47 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch47 已打过，跳过（幂等）"); sys.exit(0)

A = '''def w(line=""):
    print(line)
    REPORT.append(str(line))
'''
if s.count(A) != 1:
    print("!! patch47 中止：w() 锚点命中 %d 次（需恰好1次）" % s.count(A)); sys.exit(0)

NEW = '''def _fix47(line):
    """@@MARK@@：热力图标题按实时胜率重写"""
    try:
        t = str(line)
        if not ("热力图" in t and "可作为选股依据" in t and "历史" in t):
            return line
        import re as _re47
        v = globals().get("RULE_WINRATE_TAG", {}).get("热力图")
        if not v or v[0] is None:
            return t + "  (未核实：读不到实时胜率)"
        rate, ok = v
        if ok:
            return _re47.sub(r"历史(胜率)?\\s*[\\d.]+%(（[^）]*）|\\([^)]*\\))?",
                             "实时胜率%.1f%%" % rate, t, count=1) + (
                                 "（接近抛硬币，只作参考）" if rate < 55 else "")
        return ("  \\U0001f534\\U0001f534【热力图·板块方向 · 实时胜率%.1f%% · 低于45%% · 已停用】"
                "仅作记录，★AI不许拿它当选股依据★" % rate)
    except Exception:
        return line


def w(line=""):
    line = _fix47(line)
    print(line)
    REPORT.append(str(line))
'''.replace("@@MARK@@", MARK)

s = s.replace(A, NEW, 1)
io.open(path, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n# " + MARK + "\n")
print("OK 1: 热力图标题已改为读实时胜率 → " + path)

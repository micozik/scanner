# -*- coding: utf-8 -*-
"""V28.0 补丁 · 给选股模块打【历史胜率】标签

2026-08-21：AI推荐 1胜7负。根因不是运气，是一直在用
【已经被自己的回测证明无效】的筛选器选股。
实测：热力图57.4%(唯一>45%) | 事件雷达19% | 选股器0% | 冷低早-2.85%
规则记分卡明写"胜率<45%立即停用"，但这些模块照样每天输出候选，
AI也照样从里面挑 → 规则形同虚设。
本补丁让每个模块输出时强制带标签，AI看到🔴就不许拿它推荐。
"""
import io
import os

P = "scanner_cloud.py"
if not os.path.exists(P):
    print("找不到 scanner_cloud.py")
    raise SystemExit(0)
s = io.open(P, encoding="utf-8").read()
n = 0

INJ = '''
RULE_WINRATE_TAG = {
    "热力图": (57.4, True),
    "事件雷达": (19.0, False),
    "选股器": (0.0, False),
    "冷低早": (-2.85, False),
    "埋伏池": (None, None),
    "预启动雷达": (None, None),
    "隐形主线": (None, None),
}


def wr_tag(name):
    """★V28.0 模块胜率标签。<45%的强制标【不许推荐】"""
    v = RULE_WINRATE_TAG.get(name)
    if not v or v[0] is None:
        return "  \\u26aa\\u3010%s \\u00b7 \\u6837\\u672c\\u4e0d\\u8db3\\u3011\\u4ec5\\u4f9b\\u53c2\\u8003" % name
    rate, ok = v
    if ok:
        return "  \\U0001f7e2\\u3010%s \\u00b7 \\u5386\\u53f2\\u80dc\\u7387%.1f%%\\u3011\\u2605\\u53ef\\u4f5c\\u4e3a\\u9009\\u80a1\\u4f9d\\u636e\\u2605" % (name, rate)
    return ("  \\U0001f534\\U0001f534\\u3010%s \\u00b7 %.1f%% \\u00b7 \\u5df2\\u505c\\u7528\\u3011"
            "\\u4ec5\\u4f5c\\u8bb0\\u5f55\\uff0c\\u2605AI\\u4e0d\\u8bb8\\u62ff\\u5b83\\u63a8\\u8350\\u4efb\\u4f55\\u6807\\u7684\\u2605" % (name, rate))


'''

if "RULE_WINRATE_TAG" not in s:
    s = s.replace("def safe_run(title, func):", INJ + "def safe_run(title, func):", 1)
    n += 1
    print("OK 1: winrate table injected")
else:
    print("SKIP 1: already patched")

PAIRS = [
    ("\u5085\u5085", "", ""),
]

# 热力图
a1 = 'w("\U0001f525\U0001f525\u3010\u50ac\u5316\u70ed\u529b\u56fe\u00b7\u591a\u7a7a\u7248\u3011'
i1 = s.find(a1)
if i1 > 0 and 'wr_tag("\u70ed\u529b\u56fe")' not in s:
    j1 = s.find("\n", i1)
    s = s[:j1 + 1] + '    w(wr_tag("\u70ed\u529b\u56fe"))\n' + s[j1 + 1:]
    n += 1
    print("OK 2a: heatmap tag")

# 事件雷达
a2 = 'w("\U0001f4a5\U0001f4a5\u3010\u4e8b\u4ef6\u9a71\u52a8\u96f7\u8fbe\u3011'
i2 = s.find(a2)
if i2 > 0 and 'wr_tag("\u4e8b\u4ef6\u96f7\u8fbe")' not in s:
    j2 = s.find("\n", i2)
    s = s[:j2 + 1] + '    w(wr_tag("\u4e8b\u4ef6\u96f7\u8fbe"))\n' + s[j2 + 1:]
    n += 1
    print("OK 2b: event radar tag")

# 选股器
a3 = 'w("\U0001f3af\U0001f3af\u3010\u4e2a\u80a1\u7ea7\u9009\u80a1\u5668\u3011'
i3 = s.find(a3)
if i3 > 0 and 'wr_tag("\u9009\u80a1\u5668")' not in s:
    j3 = s.find("\n", i3)
    s = s[:j3 + 1] + '    w(wr_tag("\u9009\u80a1\u5668"))\n' + s[j3 + 1:]
    n += 1
    print("OK 2c: picker tag")

TAIL = '''    try:
        w("")
        w("=" * 60)
        w("\\U0001f3af\\U0001f3af\\u3010\\u4eca\\u65e5\\u552f\\u4e00\\u53ef\\u7528\\u7684\\u9009\\u80a1\\u4f9d\\u636e\\u3011\\u53ea\\u5217\\u80dc\\u7387>45%%\\u7684\\u6a21\\u5757 \\U0001f3af\\U0001f3af")
        w("=" * 60)
        w("  \\u26052026-08-21\\uff1aAI\\u63a8\\u8350 1\\u80dc7\\u8d1f\\uff0c\\u6839\\u56e0\\u662f\\u7528\\u5df2\\u5224\\u6b7b\\u7684\\u7b5b\\u9009\\u5668\\u9009\\u80a1\\u3002")
        w("  \\u2605\\u4ece\\u4eca\\u5929\\u8d77\\uff0c\\u53ea\\u6709\\u4e0b\\u9762\\u8fd9\\u4e9b\\u6a21\\u5757\\u7684\\u8f93\\u51fa\\u53ef\\u4ee5\\u62ff\\u6765\\u63a8\\u8350\\uff1a")
        w("")
        _any = False
        for _k, _v in RULE_WINRATE_TAG.items():
            if _v and _v[0] is not None and _v[1]:
                w("  \\U0001f7e2 %s\\uff08\\u5386\\u53f2%.1f%%\\uff09" % (_k, _v[0]))
                _any = True
        if not _any:
            w("  \\U0001f534 \\u4eca\\u5929\\u6ca1\\u6709\\u4efb\\u4f55\\u6a21\\u5757\\u7684\\u80dc\\u7387>45%%")
            w("     \\u2192 \\u2605\\u4e0d\\u8bb8\\u63a8\\u8350\\u4efb\\u4f55\\u6807\\u7684\\u2605\\uff08\\u94c1\\u5f8bD\\uff09")
        w("")
        w("  \\U0001f534 \\u5df2\\u505c\\u7528\\uff08\\u4ec5\\u4f5c\\u8bb0\\u5f55\\uff0c\\u4e0d\\u8bb8\\u63a8\\u8350\\uff09\\uff1a")
        for _k, _v in RULE_WINRATE_TAG.items():
            if _v and _v[0] is not None and not _v[1]:
                w("     %s\\uff08%.1f%%\\uff09" % (_k, _v[0]))
        w("=" * 60)
    except Exception:
        pass

'''

ANCHOR = '    os.makedirs("reports", exist_ok=True)\n    text = "\\n".join(REPORT)'
if "\u4eca\u65e5\u552f\u4e00\u53ef\u7528\u7684\u9009\u80a1\u4f9d\u636e" not in s and ANCHOR in s:
    s = s.replace(ANCHOR, TAIL + ANCHOR, 1)
    n += 1
    print("OK 3: tail section added")
else:
    print("SKIP 3")

if "V27.0 |" in s:
    s = s.replace("A\u80a1\u4f5c\u6218\u626b\u63cf\u5668V27.0 |", "A\u80a1\u4f5c\u6218\u626b\u63cf\u5668V28.0 |")
    n += 1

if n:
    io.open(P, "w", encoding="utf-8").write(s)
    print("DONE: %d changes" % n)
else:
    print("DONE: nothing to change")

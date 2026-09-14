# -*- coding: utf-8 -*-
"""
patch14_heat_dedup.py —— 只做一件事：
热力图不许把同一条新闻数成多条。

2026-09-14 实例：同一件事（上海医保个账9/15起可付非免疫规划疫苗）
被三家媒体写成三个标题，全部计入【创新药/医药】利多，
把它顶成净+4全场第1名。实际只有2条催化。
  ①上海职工医保个人账户可支付非免疫规划疫苗费用 9月15日起实施
  ②上海职工医保个账9月15日起可支付非免疫规划疫苗费用
  ③9月15日起上海职工医保个人账户历年结余资金可支付非免疫规划疫苗费用

根因：V8.1 的 _news_key 只认【书名号】和【冒号前主体】。
  这三条都没有书名号、也没有冒号 → 退化成"取前12字"，
  而三条的前12字各不相同 → 指纹全不同 → 去重完全失效。
  和 8/10 煤炭被拆成18条那次是同一个洞。

修法：在原有指纹之外，加一层【字面相似度】判定。
  用2-gram集合的Jaccard相似度，≥0.5 视为同源，只算第一条。
  ★热力图是唯一胜率>45%的选股模块(57.4%)，它的排序被污染
    = 选股直接被污染，所以这个洞必须堵。
"""
import io
import os
import sys

MARK = "★patch14：热力图同源相似度去重★"
CANDIDATES = ["scanner_cloud.py", "scanner_cloud__1_.py"]

path = None
for c in CANDIDATES:
    if os.path.exists(c):
        path = c
        break
if path is None:
    print("跳过 patch14：找不到 scanner_cloud.py")
    sys.exit(0)

with io.open(path, "r", encoding="utf-8") as f:
    s = f.read()

if MARK in s:
    print("OK 0: patch14 已打过，跳过（幂等）")
    sys.exit(0)

# ── 步骤1：注入相似度函数，挂在 _news_key 之后（结构定位） ──
A1 = '    return "RAW:" + t[:12]'
if A1 not in s:
    print("!! 1: 锚点 _news_key 收尾未命中，patch14 中止")
    sys.exit(0)

HELPER = A1 + '''


# ''' + MARK + '''
def _news_grams(t):
    """取中文/字母数字的2-gram集合，忽略标点空格"""
    t = "".join(ch for ch in str(t) if ch.isalnum())
    if len(t) < 4:
        return set()
    return set(t[i:i + 2] for i in range(len(t) - 1))


def _near_dup(t, kept, thr=0.50):
    """和已收下的标题比字面相似度，≥thr 判为同源
    ★只在同一板块内比，不跨板块，避免误杀"""
    g = _news_grams(t)
    if not g:
        return False
    for g2 in kept:
        if not g2:
            continue
        inter = len(g & g2)
        if not inter:
            continue
        if inter / float(len(g | g2)) >= thr:
            return True
    return False'''

s = s.replace(A1, HELPER, 1)
print("OK 1: 已注入 _news_grams / _near_dup")

# ── 步骤2：热力图循环里启用它 ──
A2 = '''        bull, bear, neu, seen = [], [], [], set()'''
if A2 not in s:
    print("!! 2: 锚点 热力图循环初始化 未命中，patch14 中止")
    sys.exit(0)
s = s.replace(A2, A2 + "\n        _kept = []  # " + MARK, 1)

A3 = '''            for k in kws:
                if k in t and t[:26] not in seen:
                    seen.add(t[:26])
                    seen.add(_k2)'''
if A3 not in s:
    print("!! 3: 锚点 热力图计数分支 未命中，patch14 中止")
    sys.exit(0)

NEW3 = '''            for k in kws:
                if k in t and t[:26] not in seen:
                    # ''' + MARK + '''
                    if _near_dup(t, _kept):
                        seen.add(t[:26])
                        seen.add(_k2)
                        break
                    _kept.append(_news_grams(t))
                    seen.add(t[:26])
                    seen.add(_k2)'''

s = s.replace(A3, NEW3, 1)
print("OK 2: 热力图计数已接入相似度去重")

with io.open(path, "w", encoding="utf-8") as f:
    f.write(s)

print("patch14 完成 → %s" % path)

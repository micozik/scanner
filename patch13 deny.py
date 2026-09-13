# -*- coding: utf-8 -*-
"""
patch13_deny.py —— 只做一件事：
让 _news_polarity() 认识【否定/辟谣句式】。

根因：BULL_WORDS 只数关键词，不看否定。
  「公司没有算力中心…的在手订单」→ 命中"订单" → 判 +1 利多
  「通过英伟达认证情况不属实」    → 判 0 中性，对板块净利多一分不扣
  2026-09-13 一晚出现4条：超声电子、金安国纪、智度股份、浙江交科

修法：数词之前先查否定标记。
  有否定标记 + 文本里有利多词 = 【在否认一个利好】 → 强制 -1
  有否定标记 + 没有利多词     = 否认的是坏事/纯澄清 → 判 0，不冤枉
  （所以「天风证券回应被罚8亿：不属实」不会被错判成利空）
"""
import io
import os
import sys

MARK = "★patch13：否定句式识别★"
CANDIDATES = ["scanner_cloud.py", "scanner_cloud__1_.py"]

path = None
for c in CANDIDATES:
    if os.path.exists(c):
        path = c
        break
if path is None:
    print("跳过 patch13：找不到 scanner_cloud.py")
    sys.exit(0)

with io.open(path, "r", encoding="utf-8") as f:
    s = f.read()

if MARK in s:
    print("OK 0: patch13 已打过，跳过（幂等）")
    sys.exit(0)

# ── 步骤1：注入否定词表（放在 POLARITY_TRAPS 之后，结构定位） ──
A1 = '    "不及预期": -1, "低于预期": -1, "冲高回落": -1,\n}'
if A1 not in s:
    print("!! 1: 锚点 POLARITY_TRAPS 收尾未命中，patch13 中止")
    sys.exit(0)

DENY_BLOCK = A1 + '''

# ''' + MARK + '''
# 公司/官方出面否认某个利好传闻。高精度词，只收几乎不会误伤的。
DENY_MARKERS = [
    "不属实", "不实信息", "均为不实", "纯属虚构", "系谣言", "为谣言",
    "谣言", "辟谣", "予以否认", "否认相关", "否认上述", "特此澄清",
    "澄清公告", "无产品供货", "未向", "未供货", "尚未供货",
    "不存在应披露", "不存在相关", "没有在手订单", "无在手订单",
    "未获得", "未通过认证", "不涉及相关业务", "未与", "非公司",
    "情况不属实", "并非事实", "与事实不符",
]
# 「没有/不存在 + 利多词」这类拆开写的否认，单独兜一层
DENY_PREFIX = ["没有", "不存在", "未有", "尚未", "无", "未"]
# 被否认的那个东西是不是好事。BULL_WORDS 里没有"认证/供应链"，
# 导致「通过英伟达认证不属实」判不出利空，这里补上（只在否定分支用）
DENY_CTX = ["认证", "供应链", "定点", "入选", "中标", "订单", "供货",
            "配套", "导入", "送样", "客户", "合作", "量产", "涨价",
            "产能", "扩产", "布局"]'''

s = s.replace(A1, DENY_BLOCK, 1)
print("OK 1: 已注入 DENY_MARKERS / DENY_PREFIX 词表")

# ── 步骤2：在 _news_polarity 里数词之前先判否定 ──
A2 = '''    txt = str(text)
    b = r = 0
    for ph, pol in POLARITY_TRAPS.items():'''
if A2 not in s:
    print("!! 2: 锚点 _news_polarity 函数体未命中，patch13 中止")
    sys.exit(0)

NEW2 = '''    txt = str(text)
    # ''' + MARK + '''
    _bull_hit = any(_w in txt for _w in BULL_WORDS) or \\
        any(_w in txt for _w in DENY_CTX)
    _deny = any(_d in txt for _d in DENY_MARKERS)
    if not _deny:
        # 「没有…订单」这类：否定词与利多词分开出现
        for _p in DENY_PREFIX:
            _i = txt.find(_p)
            if _i >= 0 and any(_w in txt[_i:_i + 30] for _w in BULL_WORDS):
                _deny = True
                break
    if _deny:
        # 否认的是一个利好 → 利空；否认的是坏事/纯澄清 → 中性
        return -1 if _bull_hit else 0
    b = r = 0
    for ph, pol in POLARITY_TRAPS.items():'''

s = s.replace(A2, NEW2, 1)
print("OK 2: _news_polarity 已加否定前置判定")

with io.open(path, "w", encoding="utf-8") as f:
    f.write(s)

print("patch13 完成 → %s" % path)

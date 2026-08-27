# -*- coding: utf-8 -*-
"""V35.0 补丁 · 两处

① 5个【选股模块】加进永不跳过
   2026-08-27：预算1020秒又用尽，被跳的是：
     今日隐形主线 / 板块轮动器 / 预启动雷达 / 每日选股 / 跳升榜回测
   ★这5个全是"帮用户选股"的，而用户2026-08-25明确说：
     『你必须帮我完成选股任务，这是你唯一的重点任务』
   ★而且它们都是纯计算（用已抓好的数据聚类），几秒就完 ——
     被"抓网络的慢模块"挤掉是排序错误。

② 美股交叉校验的误报
   2026-08-27：「新闻说【纳指收跌】，但META价格+1.07%」
   —— 纳指整体-0.08%而个股分化是完全正常的，不是矛盾。
   ★"纳指收跌"这类【指数级】新闻，不该用来判定【个股】价格错误。
   只保留个股级和板块级的关键词。
"""
import io
import os

n_total = 0

# ═══ ① scanner_cloud.py ═══
P = "scanner_cloud.py"
if os.path.exists(P):
    s = io.open(P, encoding="utf-8").read()
    n = 0
    A = '"埋伏池回测", "热力图回测", "选股器回测", "事件雷达回测",\n               "买入后复核")'
    B = ('"埋伏池回测", "热力图回测", "选股器回测", "事件雷达回测",\n'
         '               "买入后复核",\n'
         '               # ★★V35.0：这5个是【选股模块】，用户唯一的重点任务★★\n'
         '               # 2026-08-27预算又用尽，被跳的全是它们。\n'
         '               # 它们是纯计算(用已抓好的数据聚类)，几秒就完，\n'
         '               # 被"抓网络的慢模块"挤掉是排序错误。\n'
         '               "隐形主线", "板块轮动器", "预启动雷达",\n'
         '               "每日选股", "跳升榜回测")')
    if A in s and '"跳升榜回测")' not in s:
        s = s.replace(A, B, 1)
        n += 1
        print("OK 1: 5个选股模块已加入永不跳过")
    else:
        print("SKIP 1")

    if "V33.0 |" in s:
        s = s.replace("A股作战扫描器V33.0 |", "A股作战扫描器V35.0 |")
        n += 1
    if "V34.0 |" in s:
        s = s.replace("A股作战扫描器V34.0 |", "A股作战扫描器V35.0 |")
        n += 1

    if n:
        io.open(P, "w", encoding="utf-8").write(s)
        n_total += n
else:
    print("no scanner_cloud.py")

# ═══ ② scanner_usa.py ═══
Q = "scanner_usa.py"
if os.path.exists(Q):
    u = io.open(Q, encoding="utf-8").read()
    m = 0
    # 删掉指数级关键词——它们不该用来判个股价格对错
    import re as _re
    for _line in _re.findall(r'^\s*"纳指[^"]*":[^\n]*\n', u, _re.M):
        u = u.replace(_line, "")
        m += 1
    if m:
        print("OK 2: 指数级关键词已移除(%d条)" % m)
        # 加注释说明
        u = u.replace(
            "NEWS_PRICE_CHECK = {",
            "# ★★V35.0：移除【指数级】关键词（纳指收跌/收涨）★★\n"
            "# 2026-08-27误报：新闻『纳指收跌0.08%』，但META+1.07%被判为矛盾。\n"
            "# 指数整体微跌而个股分化是完全正常的市场状态，不是数据错误。\n"
            "# ★只保留【个股级】和【板块级】关键词 ——\n"
            "#   『闪迪跌超10%』这种才是能用来校验价格的硬事实。\n"
            "NEWS_PRICE_CHECK = {", 1)
        m += 1
    else:
        print("SKIP 2")

    if "V4.1 |" in u:
        u = u.replace("美股夜盘扫描器V4.1 |", "美股夜盘扫描器V4.2 |")
        m += 1

    if m:
        io.open(Q, "w", encoding="utf-8").write(u)
        n_total += m
else:
    print("no scanner_usa.py")

print("DONE: %d changes" % n_total)

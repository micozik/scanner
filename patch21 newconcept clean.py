# -*- coding: utf-8 -*-
"""
patch21_newconcept_clean.py —— 只做一件事：
把【新概念雷达】捞出来的垃圾清掉。

★2026-09-17 实测，它捞出的18个词里大部分是废的★
  ◆【公司机器人相】3次  ◆【司机器人相关】3次
  ◆【机器人相关业】3次  ◆【器人相关业务】3次  ← 同一句话的碎片
  ◆【电机】5次 ◆【客户】4次 ◆【欧盟】4次 ◆【能力】4次 ← 通用词

根因二：
  ① 恒帅股份那条新闻在全量流里【重复出现3次】，
     导致它的每一个子串频次都是3，全部过了≥3的门槛。
     patch19b 的去冗余规则是「短词被同频长词包含就丢」，
     但这些碎片【长度相同、频次相同、互不包含】，全漏了过去。
  ② 停用词表没收"电机/客户/能力/服务/技术"这类通用词。

修法三条：
  ① ★新闻先去重★ —— 同一条新闻只算一次（按前40字指纹）
  ② ★要求出现在≥2条【不同】新闻里★ —— 单条新闻里刷出来的
     碎片，去重后频次掉到1，直接被门槛拦掉；
     而真概念（金刚石在9/16出现在培育钻石概念股、金刚石导热技术、
     英伟达Rubin金刚石复合材料等多条不同新闻里）会留下来
  ③ 扩充停用词
"""
import io
import os
import sys

MARK = "patch21_newconcept_clean"
CANDIDATES = ["scanner_cloud.py", "scanner_cloud__1_.py"]

path = None
for c in CANDIDATES:
    if os.path.exists(c):
        path = c
        break
if path is None:
    print("!! patch21 中止：找不到 scanner_cloud.py")
    sys.exit(0)

with io.open(path, "r", encoding="utf-8") as f:
    s = f.read()

if MARK in s:
    print("OK 0: patch21 已打过，跳过（幂等）")
    sys.exit(0)

if "patch19b_newconcept" not in s:
    print("!! patch21 中止：请先打 patch19b_newconcept.py")
    sys.exit(0)

# ── 步骤1：新闻去重 + 记录每个词出现在几条不同新闻里 ──
A1 = """        _cnt19 = _co19.Counter()
        _eg19 = {}
        for _t19 in _raw19:
            if not any(_c19 in _t19 for _c19 in _CTX19):
                continue"""

if A1 not in s:
    print("!! 步骤1 锚点未命中，patch21 中止")
    sys.exit(0)

N1 = """        _cnt19 = _co19.Counter()
        _doc19 = _co19.defaultdict(set)   # patch21：词 -> 出现在哪些新闻
        _eg19 = {}
        _seen19 = set()                   # patch21：新闻去重
        for _i19x, _t19 in enumerate(_raw19):
            if not any(_c19 in _t19 for _c19 in _CTX19):
                continue
            _fp19 = "".join(_t19.split())[:40]   # patch21：前40字当指纹
            if _fp19 in _seen19:
                continue
            _seen19.add(_fp19)"""

s = s.replace(A1, N1, 1)
print("OK 1: 新闻已按前40字指纹去重")

# ── 步骤2：统计时记录所属新闻 ──
A2 = """                        _cnt19[_w19] += 1
                        if _w19 not in _eg19:
                            _eg19[_w19] = _t19[:70]"""
if A2 not in s:
    print("!! 步骤2 锚点未命中，patch21 中止")
    sys.exit(0)

N2 = """                        _cnt19[_w19] += 1
                        _doc19[_w19].add(_fp19)   # patch21
                        if _w19 not in _eg19:
                            _eg19[_w19] = _t19[:70]"""
s = s.replace(A2, N2, 1)
print("OK 2: 已记录每个词所属新闻")

# ── 步骤3：过滤，要求≥2条不同新闻 + 扩充停用词 ──
A3 = """        for _w19, _c19 in _items19:
            if _c19 < 3 or _w19 in _STOP19:
                continue"""
if A3 not in s:
    print("!! 步骤3 锚点未命中，patch21 中止")
    sys.exit(0)

N3 = """        # patch21：扩充停用词（2026-09-17 实测捞出的通用词）
        _STOP19 |= set([
            "电机", "客户", "能力", "欧盟", "服务", "系统", "设备", "业务",
            "订单", "合作", "平台", "项目", "产业", "企业", "集团", "国家",
            "全球", "国内", "海外", "美国", "日本", "韩国", "中国", "印度",
            "公司", "子公司", "控股", "股东", "董事", "总经理", "董事长",
            "规模", "水平", "水平", "情况", "问题", "影响", "作用", "地位",
            "未来", "目前", "近期", "日前", "昨日", "今日", "明日", "本周",
            "亿元", "万元", "美元", "港元", "同比", "环比", "增长", "下降",
            "上涨", "下跌", "涨幅", "跌幅", "股价", "市值", "估值", "业绩",
            "机构", "分析", "研报", "预计", "表示", "介绍", "认为", "指出",
        ])
        for _w19, _c19 in _items19:
            if _c19 < 3 or _w19 in _STOP19:
                continue
            # ★patch21 核心：必须出现在≥2条【不同】新闻里★
            #   单条新闻里刷出来的碎片（如"公司机器人相""司机器人相关"）
            #   去重后只剩1条来源 → 直接丢
            if len(_doc19.get(_w19, ())) < 2:
                continue"""
s = s.replace(A3, N3, 1)
print("OK 3: 已加【≥2条不同新闻】门槛 + 扩充停用词")

s = s.rstrip("\n") + "\n\n# " + MARK + "：新概念雷达降噪\n"
with io.open(path, "w", encoding="utf-8") as f:
    f.write(s)
print("patch21 完成 → %s" % path)

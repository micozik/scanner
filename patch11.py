# -*- coding: utf-8 -*-
"""V37.1 补丁 · 只做一件事：把【今日必答清单】加进永不跳过

2026-08-28：patch10 装上了必答清单，但它被全局预算挤掉了：
  ⏱️【📋今日必答清单】全局预算(1020秒)已用尽，跳过。本节缺失
★根因：patch10 的第3步（加入 _NEVER_SKIP）锚点没匹配上，静默失败了。
★这个模块是防止AI漏看的最后一道闸，被跳过等于没装。
"""
import io
import os

P = "scanner_cloud.py"
if not os.path.exists(P):
    print("no scanner_cloud.py")
    raise SystemExit(0)
s = io.open(P, encoding="utf-8").read()
n = 0

if "_NEVER_SKIP" not in s:
    print("ERROR: 找不到 _NEVER_SKIP")
    raise SystemExit(0)

# 定位 _NEVER_SKIP = ( ... ) 整个元组，在收尾的 ")" 前插入
i = s.find("_NEVER_SKIP = (")
if i < 0:
    print("ERROR: 定位失败")
    raise SystemExit(0)
j = s.find(")", i)
seg = s[i:j + 1]

if "必答清单" in seg:
    print("SKIP: 已在名单里")
else:
    new_seg = seg[:-1].rstrip()
    if not new_seg.endswith(","):
        new_seg += ","
    new_seg += ('\n               # ★★V37.1：必答清单是防止AI漏看的最后一道闸★★\n'
                '               # 8/28它被预算挤掉 → 等于没装。\n'
                '               "必答清单", "今日必答清单")')
    s = s[:i] + new_seg + s[j + 1:]
    n += 1
    print("OK: 必答清单已加入永不跳过")

if "V36.0 |" in s:
    s = s.replace("A股作战扫描器V36.0 |", "A股作战扫描器V37.1 |")
    n += 1
if "V37.0 |" in s:
    s = s.replace("A股作战扫描器V37.0 |", "A股作战扫描器V37.1 |")
    n += 1

if n:
    io.open(P, "w", encoding="utf-8").write(s)
    print("DONE: %d changes" % n)
else:
    print("DONE: nothing")

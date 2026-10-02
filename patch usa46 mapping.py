# -*- coding: utf-8 -*-
"""
patch_usa46_mapping.py —— 美股扫描器：补齐持仓→美股对标映射（只改 scanner_usa.py）
2026-10-02 用户：『你最好抓一下我的数据，不然我不知道我的系统有什么用』
美股报告 10/02 08:06 写着：
  凯盛科技 ← 玻璃基板/先进封装链：今夜美股无对应标的
  而同一份报告里 ★康宁(GLW) +4.33%★ —— 康宁正是凯盛逻辑的源头（Q4玻璃基板涨价15%）
同样漏掉：创新药→礼来/Moderna，机器人→特斯拉，燃机→GE Vernova，风电→GE Vernova
根因：CHAIN_TO_US 的键是旧链名，清单里的新链名对不上；
      模糊匹配只比"前两个字"，"玻璃""创新""机器""核电""海上"全部落空。
修：
  ① 新增5条链的映射（键名用清单里的关键词，模糊匹配能命中）
  ② 抓取名单加 GE Vernova(GEV)、Moderna(MRNA)
"""
import io, os, sys
MARK = "patch_usa46_mapping"
path = next((c for c in ["scanner_usa.py", "scanner_usa__1_.py"] if os.path.exists(c)), None)
if not path:
    print("跳过 patch_usa46：找不到 scanner_usa.py（A股扫描不需要它）"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch_usa46 已打过"); sys.exit(0)
ok = 0

A = '''    "农业(独立)": [],
    "用户自定": [],
}'''
if A in s:
    s = s.replace(A, '''    # ''' + MARK + '''：清单新链名的对标
    "玻璃基板": [("GLW", 1.0), ("INTC", 0.5), ("AMAT", 0.3)],
    "创新药": [("LLY", 0.8), ("MRNA", 0.5)],
    "机器人": [("TSLA", 1.0)],
    "核电": [("GEV", 0.8)],
    "海上风电": [("GEV", 0.8)],
    "农业(独立)": [],
    "用户自定": [],
}''', 1); ok += 1
    print("OK 1: 新增 玻璃基板/创新药/机器人/核电/海上风电 五条映射")
else:
    print("!! 1: CHAIN_TO_US 结尾锚点未命中")

# 模糊匹配从"前两个字"改为"键里任一关键词出现在链名里"
B = '''                    for k, v in CHAIN_TO_US.items():
                        if k[:2] and k[:2] in chain:
                            refs = v
                            break'''
if B in s:
    s = s.replace(B, '''                    for k, v in CHAIN_TO_US.items():   # ''' + MARK + '''
                        _kk = k.replace("链", "").split("/")
                        if any(x and x in chain for x in _kk) or (k[:2] and k[:2] in chain):
                            refs = v
                            break''', 1); ok += 1
    print("OK 2: 模糊匹配改为关键词包含")

C = '''    ("伯克希尔B", "BRK.B"), ("伯克希尔A", "BRK.A"),'''
if C in s:
    s = s.replace(C, '''    ("GE Vernova", "GEV"), ("Moderna", "MRNA"),   # ''' + MARK + '''
''' + C, 1); ok += 1
    print("OK 3: 抓取名单加 GEV、MRNA")

D = '''    "Coherent": "COHR", "礼来": "LLY", "纽蒙特": "NEM",
}'''
if D in s:
    s = s.replace(D, '''    "Coherent": "COHR", "礼来": "LLY", "纽蒙特": "NEM",
    "GE Vernova": "GEV", "Moderna": "MRNA", "莫德纳": "MRNA",
}''', 1); ok += 1
    print("OK 4: 新闻名称映射加 GEV、MRNA")

io.open(path, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n# " + MARK + "\n")
print("patch_usa46 完成 %d/4 → %s" % (ok, path))

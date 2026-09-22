# -*- coding: utf-8 -*-
"""
patch30_fixall.py —— 修 r682 核对出来的问题，每一步都打印结果，不再静默
① 领涨挖掘：不管仓库里是哪一版 patch28，都补齐【模糊匹配+诊断】，
   并在报告里打印版本号和对照表大小 —— 以后看报告就知道生效没有
② 新概念雷达去重：旧法用"前40字符"当指纹，同一条新闻因时间戳前缀不同
   （"2026-09-22 15:06" / "[15:06]" / "【"）被当成3条 → 切出一堆碎片。
   改为：只取汉字、取前20个汉字当指纹
③ 关掉已停用的【个股级选股器】：标着0.0%已停用，却每次跑295秒
"""
import io, os, sys
MARK = "patch30_fixall"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch30 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch30 已打过"); sys.exit(0)

# ① 模糊匹配（仓库若是旧版 patch28 则补上）
OLD_EXACT = '''                cons = [(c, "") for c, ind in (_im28 or {}).items()
                        if str(ind).strip() == str(nm).strip()]
                _src28 = "行业对照表"'''
FUZZY = '''                def _nm28(x):
                    return str(x).replace("Ⅱ", "").replace("Ⅲ", "").replace(" ", "").strip()
                _SYN28 = {"文化传媒": ["广告营销", "出版", "影视院线", "数字媒体", "电视广播", "文化传媒"],
                          "IT服务": ["IT服务"], "软件开发": ["软件开发", "软件"],
                          "通信服务": ["通信服务", "电信服务"], "计算机设备": ["计算机设备"],
                          "消费电子": ["消费电子", "消费电子零部件及组装"], "元件": ["元件", "印制电路板", "被动元件"],
                          "医疗服务": ["医疗服务", "医疗研发外包"], "生物制品": ["生物制品", "疫苗", "血液制品"]}
                _n0 = _nm28(nm)
                _syn = [_nm28(x) for x in _SYN28.get(_n0, [])]
                cons = []
                for c, ind in (_im28 or {}).items():
                    _i = _nm28(ind)
                    if _i == _n0 or _i in _syn or (len(_i) >= 3 and (_i in _n0 or _n0 in _i)):
                        cons.append((c, ""))
                _src28 = "行业对照表(模糊)"
                if not cons:
                    _near = sorted({str(v) for v in (_im28 or {}).values()
                                    if any(ch in str(v) for ch in _n0[:2])})[:8]
                    w(f"    [诊断] {nm} 在对照表无匹配；对照表里相近的行业名：{_near or '无'}（共{len(set((_im28 or {}).values()))}个行业）")'''
if "_SYN28" in s:
    print("OK 1a: 模糊匹配已在（仓库是新版patch28）")
elif OLD_EXACT in s:
    s = s.replace(OLD_EXACT, FUZZY, 1); print("OK 1a: 仓库是旧版patch28 → 已补上模糊匹配+诊断")
else:
    print("!! 1a: 找不到patch28的匹配代码（patch27/28没打？）")

# 把吞错误的 except 改成打印原因
OLD_EXC = '''            except Exception:
                cons = []
'''
if OLD_EXC in s:
    s = s.replace(OLD_EXC, '''            except Exception as _e30:
                w(f"    [诊断] {nm} 对照表查询出错：{type(_e30).__name__}: {str(_e30)[:60]}")
                cons = []
''', 1); print("OK 1b: 对照表查询出错不再静默，会打印原因")

# 版本号+对照表大小打印
ANC = '''    w("    旧流程停在板块层→ETF填空。本模块补上【板块→个股】这一步。")'''
if ANC in s:
    s = s.replace(ANC, ANC + '''
    try:
        _m30, _a30 = _load_ind_cache()
        w(f"  [版本] patch27+28+30 ｜ 行业对照表{len(_m30 or {})}只（缓存{_a30}天）｜ 模糊匹配：已启用")
    except Exception as _e30b:
        w(f"  [版本] 行业对照表读取失败：{type(_e30b).__name__}")''', 1)
    print("OK 1c: 报告里会打印版本号和对照表大小")

# ② 新概念雷达指纹：只取汉字前20个
OLD_FP = '''            _fp19 = "".join(_t19.split())[:40]   # patch21：前40字当指纹'''
if OLD_FP in s:
    s = s.replace(OLD_FP, '''            _fp19 = "".join(_re19.findall(r"[\\u4e00-\\u9fa5]", _t19))[:20]   # patch30：只取汉字，去掉时间戳/括号前缀''', 1)
    print("OK 2: 新概念雷达去重改为汉字指纹")
else:
    print("!! 2: 没找到patch21的指纹行（patch21没打？）")

# ③ 关掉已停用的个股级选股器
OLD_SK = '''_SKIP29 = ("持仓/候选 深度体检", "定增破发雷达")'''
if OLD_SK in s:
    s = s.replace(OLD_SK, '''_SKIP29 = ("持仓/候选 深度体检", "定增破发雷达", "个股级选股器")  # patch30''', 1)
    print("OK 3: 已关闭停用的个股级选股器（省约5分钟）")
else:
    print("!! 3: 没找到patch29的关闭名单（patch29没打？）")

io.open(path, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n# " + MARK + "\n")
print("patch30 完成 → " + path)

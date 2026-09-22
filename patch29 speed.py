# -*- coding: utf-8 -*-
"""
patch29_speed.py —— 跑一次要半小时，先量清楚时间花在哪，再砍确定没用的
（2026-09-22 用户：『跑一次都要半个小时了，越来越夸张』）

① 每个模块计时，报告末尾加【模块耗时榜】—— 以后砍谁看数据，不靠猜
② 关掉两个已确认白跑的模块：
   · 持仓/候选 深度体检：13只全部【无数据】（海外IP拿不到），每次白跑约36秒
   · 定增破发雷达：主接口 stock_qbzf_em 每次 CallTimeout，只剩公告兜底，和公告雷达重复
③ 新的【强板块·领涨挖掘】加进"永不跳过"——它是选股主力，不能被全局预算砍掉
其余模块一个不动（用户9/17：信息源都要保留），等耗时榜出来再一起决定。
配合 scan.yml：HARD_LIMIT 建议从 2700 改回 1200。
"""
import io, os, sys
MARK = "patch29_speed"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch29 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch29 已打过"); sys.exit(0)
ok = 0

A = '''_NEVER_SKIP = ("止盈体系",'''
if A in s:
    s = s.replace(A, '''MOD_TIMES29 = []   # ''' + MARK + '''
_SKIP29 = ("持仓/候选 深度体检", "定增破发雷达")
_NEVER_SKIP = ("强板块", "止盈体系",''', 1); ok += 1
    print("OK 1: 计时表/关闭名单已建，领涨挖掘设为永不跳过")

B = '''        w(f"  ⏱️【{title}】全局预算({_budget}秒)已用尽，跳过。本节缺失")
        return
'''
if B in s:
    s = s.replace(B, B + '''    if any(k in title for k in _SKIP29):
        w(f"  ⏭️【{title}】已关闭（patch29：数据源已死或全【无数据】，省时间）")
        return
    _t29 = time.time()
''', 1); ok += 1
    print("OK 2: 关闭名单生效 + 计时起点")

C = '''    finally:
        if _armed:
            try:
                signal.alarm(0)
            except Exception:
                pass
    time.sleep(0.3)
'''
if C in s:
    s = s.replace(C, C.replace("    time.sleep(0.3)\n", '''    try:
        MOD_TIMES29.append((title, time.time() - _t29))
    except Exception:
        pass
    time.sleep(0.3)
'''), 1); ok += 1
    print("OK 3: 每个模块结束记耗时")

D = '''    os.makedirs("reports", exist_ok=True)
    text = "\\n".join(REPORT)'''
if D in s:
    s = s.replace(D, '''    try:
        _tot29 = sum(t for _, t in MOD_TIMES29)
        w("\\n" + "=" * 60)
        w("⏱️【模块耗时榜】这次时间花在哪（patch29，砍谁看这里）")
        w("=" * 60)
        w(f"  模块合计 {_tot29/60:.1f} 分钟（不含装依赖、打补丁、提交）")
        for _n29, _t29x in sorted(MOD_TIMES29, key=lambda x: -x[1])[:15]:
            w(f"    {_t29x:6.0f}秒  {_n29}")
        w("=" * 60)
    except Exception:
        pass
''' + D, 1); ok += 1
    print("OK 4: 报告末尾加【模块耗时榜】")

io.open(path, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n# " + MARK + "\n")
print("patch29 完成 %d/4 → %s" % (ok, path))

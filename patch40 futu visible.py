# -*- coding: utf-8 -*-
"""
patch40_futu_visible.py —— 让富途兜底的结果【看得见】
2026-09-24 用户问：patch36传了为什么没跑出东西？
真相：patch36 注入成功了，但诊断行写的是 _why32[:6]，
      而今天的失败原因正好6条（同花顺函数不存在/东财超时/同花顺名单缺失/
      东财名单超时/新浪概念/新浪行业），★富途是第7条，被截断了★
      → 我们既看不到它成功，也看不到它为什么失败。
修：
  ① 诊断行 6条 → 12条，富途的原因一定能显示
  ② 富途分支无论成败都单独打印一行 [patch36富途]，一眼可见
  ③ 顺带修掉同一个毛病：patch32 的诊断截断也放开
"""
import io, os, sys
MARK = "patch40_futu_visible"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch40 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch40 已打过"); sys.exit(0)
ok = 0

# ① 放开截断
n = s.count("_why32[:6]")
if n:
    s = s.replace("_why32[:6]", "_why32[:12]")
    ok += 1; print(f"OK 1: 诊断截断 6→12 条（改了{n}处）")
else:
    print("!! 1: 没找到 _why32[:6]")

# ② 富途分支无论成败都打印
A = '''        if _ft36 is None:
            _why32.append("富途:stock_concept_cons_futu不存在")'''
if A in s:
    s = s.replace(A, '''        if _ft36 is None:
            _why32.append("富途:stock_concept_cons_futu不存在")
            w(f"    [patch36富途] {board_name}：本版akshare无此函数")   # ''' + MARK, 1)
    ok += 1; print("OK 2: 富途函数缺失会打印")

B = '''                except Exception as e:
                    _why32.append(f"富途({_nm36}):{type(e).__name__}")'''
if B in s:
    s = s.replace(B, '''                except Exception as e:
                    _why32.append(f"富途({_nm36}):{type(e).__name__}")
                    w(f"    [patch36富途] {board_name} 用名『{_nm36}』失败："
                      f"{type(e).__name__}: {str(e)[:50]}")   # ''' + MARK, 1)
    ok += 1; print("OK 3: 富途每次失败都打印原因")
else:
    print("!! 3: 富途异常分支未命中（patch36没打？）")

io.open(path, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n# " + MARK + "\n")
print("patch40 完成 %d/3 → %s" % (ok, path))

# -*- coding: utf-8 -*-
"""
patch41_registry.py —— 补丁登记表：报告里直接列出【代码里真正存在哪些补丁】
2026-09-25：patch36/40 文件明明在仓库里(19小时前传的)，
  但 r709 报告里一行富途都没有，诊断仍只有6条原因。
  我三次靠猜锚点，猜不出来。★不再猜，改成登记★
做法：扫描 scanner_cloud.py 自身源码，把所有 "patchNN_xxx" 标记列出来，
      报告末尾打印【补丁登记表】。哪个没打上，一眼可见。
"""
import io, os, re, sys
MARK = "patch41_registry"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch41 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch41 已打过"); sys.exit(0)

A = '''    os.makedirs("reports", exist_ok=True)
    text = "\\n".join(REPORT)'''
if A not in s:
    print("!! patch41 中止：报告写出锚点未命中"); sys.exit(0)

NEW = '''    # ''' + MARK + '''：补丁登记表——代码里到底有哪些补丁生效
    try:
        import re as _re41
        _src41 = ""
        for _f41 in ("scanner_cloud.py", "scanner_cloud__1_.py", __file__):
            try:
                if os.path.exists(_f41):
                    _src41 = open(_f41, "r", encoding="utf-8").read()
                    break
            except Exception:
                continue
        _ids41 = sorted(set(_re41.findall(r"patch(\\d+[a-z]?)_[a-z0-9_]+", _src41)),
                        key=lambda x: (int(_re41.sub(r"[a-z]", "", x)), x))
        w("\\n" + "=" * 60)
        w("🧾【补丁登记表】代码里真正生效的补丁（patch41，不用再猜）")
        w("=" * 60)
        if _ids41:
            for _i41 in range(0, len(_ids41), 10):
                w("    " + " ｜ ".join("patch" + x for x in _ids41[_i41:_i41 + 10]))
            w(f"    合计 {len(_ids41)} 个")
        else:
            w("    ⚠️ 一个都没扫到（读不到源码？）")
        for _need41 in ("36", "38", "39", "40"):
            if _need41 not in _ids41:
                w(f"    🔴 patch{_need41} 不在代码里 → 文件没传 / 锚点没命中 / 被前面的补丁改掉了")
        w("=" * 60)
    except Exception as _e41:
        w(f"  [patch41] 登记表失败：{type(_e41).__name__}: {str(_e41)[:60]}")
''' + A
s = s.replace(A, NEW, 1)
io.open(path, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n# " + MARK + "\n")
print("OK 1: 补丁登记表已加（报告末尾）→ " + path)

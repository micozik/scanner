# -*- coding: utf-8 -*-
"""
patch90_usa53_rerun.py —— 让 patch_usa53（美股实时报价·同日闸门）真正生效
2026-10-28 查出：手机上传把文件名的下划线变成空格后，工作流按文件名排序执行，
  "patch usa53 fresh.py" 排在 "patch12 usa date.py" 前面（空格 < 数字）。
  usa53 依赖 patch12 先打，于是每次都『锚点命中0次』中止 →
  10/21 修的『美股旧数据』补丁从没生效过，us145 里12只美股仍是10/26旧价、费半仍显示旧值。
做法：本文件名以 patch90 开头，一定排在 patch12/patch23 之后，再执行一次 usa53。
  usa53 自带『已打过就跳过』，重复执行无副作用。
"""
import os, subprocess, sys
src = next((f for f in ("patch usa53 fresh.py", "patch_usa53_fresh.py") if os.path.exists(f)), None)
if not src:
    print("!! patch90 中止：找不到 patch usa53 fresh.py"); sys.exit(0)
r = subprocess.run([sys.executable, src], capture_output=True, text=True)
print("patch90 → 重跑", src, "：", (r.stdout + r.stderr).strip()[-300:])

# -*- coding: utf-8 -*-
"""
patch_usa00_rename.py —— 手机上传会把文件名里的下划线变成空格：
  仓库里是『serenity feed.py』，而补丁和程序要找『serenity_feed.py』
  → patch_usa54 一直报『缺 serenity_feed.py』中止，白毛股神全量推文从没进过报告。
本补丁排在所有 usa 补丁最前面，运行时复制出一份带下划线的同名文件。
"""
import os, shutil
pairs = [("serenity feed.py", "serenity_feed.py")]
for src, dst in pairs:
    if os.path.exists(src) and not os.path.exists(dst):
        shutil.copyfile(src, dst)
        print(f"OK: 已复制 {src} → {dst}")
    elif os.path.exists(dst):
        print(f"OK: {dst} 已存在")
    else:
        print(f"!! 找不到 {src}")

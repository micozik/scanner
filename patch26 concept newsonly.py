# -*- coding: utf-8 -*-
"""
patch26_concept_newsonly.py —— 只做一件事：新概念雷达只扫【新闻】，不扫【公告】
原因（2026-09-22）：patch25修好公告后，公告从7条涨到1301条，
  公告标题全是"XX股份有限公司关于XX的公告"，新概念雷达被淹没：
  捞出【有限公司】【关于】【公告】【股票】【激励】【预留】…
  "有限公司"一个词撞出101只股票，全是噪音。
修法：n-gram 只用新闻源；另补公告套话停用词作双保险。
"""
import io, os, sys
MARK = "patch26_concept_newsonly"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch26 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch26 已打过"); sys.exit(0)
A = "        _raw19 = [_txt19(x) for x in (list(news) + list(ann))]"
if A not in s:
    print("!! patch26 中止：锚点未命中（patch19b没打？）"); sys.exit(0)
s = s.replace(A, "        _raw19 = [_txt19(x) for x in list(news)]  # " + MARK + "：公告标题套话太多，只用新闻", 1)
B = "        for _w19, _c19 in _items19:"
if s.count(B) == 1:
    s = s.replace(B, '''        _STOP19 |= set(["有限公司", "股份有限公司", "关于", "公告", "股票", "激励",
                         "预留", "股票期权", "议案", "董事会", "会议", "决议", "新材",
                         "法律意见书", "律师事务所", "证券股份", "保荐", "修订稿"])  # ''' + MARK + "\n" + B, 1)
    print("OK 2: 补公告套话停用词")
io.open(path, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n# " + MARK + "\n")
print("OK 1: 新概念雷达改为只扫新闻 → " + path)

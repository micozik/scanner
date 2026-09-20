# -*- coding: utf-8 -*-
"""
patch24_ann_merge.py —— 只做一件事：
公告条数不足时，把东财公告【按分类分别抓再合并】，把条数拉上来。

★为什么必须修（2026-09-18/20 实测）★
  [跳过] 巨潮-沪深京公告：JSONDecodeError
  [跳过] 巨潮-昨日公告：JSONDecodeError
  → 最终只有 87 条（正常≥900条）

  ★直接后果：报告里那句
    「今日全量新闻与公告中，未出现任何持仓股的个股级消息」
    ★现在是不可信的★ —— 只扫了87条，持仓出了问询/减持/
    诉讼/业绩预警，系统都可能看不见。

  ★而【卖出前五问】的第①问「基本面坏了吗」，
    唯一的信息源就是它。这一问现在等于是瞎的。
    这不是功能缺失，是风控地基塌了一块。

修法：
  东财 stock_notice_report_em 的 symbol 参数支持分类：
    全部/重大事项/财务报告/融资公告/风险提示/
    资产重组/信息变更/持股变动
  一次"全部"可能被服务端限流截断，★分8次抓再合并去重★，
  条数通常能拉到几百条。
  只在 best_n < 300 时才触发，不浪费正常情况下的时间。
"""
import io
import os
import sys

MARK = "patch24_ann_merge"
CANDIDATES = ["scanner_cloud.py", "scanner_cloud__1_.py"]

path = None
for c in CANDIDATES:
    if os.path.exists(c):
        path = c
        break
if path is None:
    print("!! patch24 中止：找不到 scanner_cloud.py")
    sys.exit(0)

with io.open(path, "r", encoding="utf-8") as f:
    s = f.read()

if MARK in s:
    print("OK 0: patch24 已打过，跳过（幂等）")
    sys.exit(0)

A = '''        if best_tag:
            w(f"  ★最终采用：{best_tag}（{best_n}条，{'带代码' if best_hascode else '★无代码★'}）")'''

if A not in s:
    print("!! patch24 中止：公告择优锚点未命中")
    sys.exit(0)

NEW = '''        # ''' + MARK + '''：条数不足时，东财按分类分别抓再合并
        # 巨潮挂掉时只剩87条，而卖出五问第①问全靠它 → 必须补
        if best_n < 300 and hasattr(ak, "stock_notice_report_em"):
            try:
                _cats24 = ["全部", "重大事项", "财务报告", "融资公告",
                           "风险提示", "资产重组", "信息变更", "持股变动"]
                _frames24 = []
                for _c24 in _cats24:
                    try:
                        _r24 = with_retry(
                            lambda c=_c24: ak.stock_notice_report_em(
                                symbol=c, date=d),
                            tries=1, wait=1, timeout=25)
                        if _r24 is not None and len(_r24):
                            _frames24.append(_r24)
                    except Exception:
                        continue
                if _frames24:
                    _m24 = pd.concat(_frames24, ignore_index=True)
                    _cc24 = pick_col(_m24, ["代码", "股票代码", "证券代码"])
                    _tt24 = pick_col(_m24, ["公告标题", "名称", "标题"])
                    if _cc24 and _tt24:
                        _m24 = _m24.drop_duplicates(subset=[_cc24, _tt24])
                    w(f"  [patch24] 东财按{len(_frames24)}个分类合并 → "
                      f"{len(_m24)}条（原最优{best_n}条）")
                    if len(_m24) > best_n:
                        df = _m24
                        best_n = len(_m24)
                        best_tag = "东财-公告大全(多分类合并)"
                        best_hascode = bool(_cc24)
                        w(f"  ★改用合并结果：{best_n}条 "
                          f"{'✅带代码' if best_hascode else '⚠️无代码'}")
                else:
                    w("  [patch24] 8个分类全部失败 → 东财公告源整体不可用")
            except Exception as _e24:
                w(f"  [patch24] 多分类合并失败：{type(_e24).__name__}: "
                  f"{str(_e24)[:50]}")

        if best_tag:
            w(f"  ★最终采用：{best_tag}（{best_n}条，{'带代码' if best_hascode else '★无代码★'}）")'''

s = s.replace(A, NEW, 1)
print("OK 1: 已加东财公告多分类合并（仅在<300条时触发）")

s = s.rstrip("\n") + "\n\n# " + MARK + "：公告多分类合并\n"
with io.open(path, "w", encoding="utf-8") as f:
    f.write(s)
print("patch24 完成 → %s" % path)

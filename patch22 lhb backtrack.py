# -*- coding: utf-8 -*-
"""
patch22_lhb_backtrack.py —— 只做一件事：
让 scanner_cloud 的龙虎榜【往前回溯】，别只查当天。

★根因（2026-09-17 定位）★
  scanner_lhb.py 和 scanner_cloud.py 用的是【完全相同的三个接口】：
      ak.stock_lhb_detail_em / stock_lhb_jgmmtj_em / stock_lhb_detail_daily_sina
  唯一区别：
      scanner_lhb.py  → for d in 最近7个交易日: 试d，有数据就停 ← 会回溯
      scanner_cloud.py→ start_date=today, end_date=today       ← 只试当天

  ★龙虎榜18:35才发布。盘中/盘后15:49跑，查当天必然返回空★
  → multi_source 把"返回空"判成【接口失败】
  → 三个源全判失败 → 连挂≥3次 → 写进【失败接口记忆】
  → 此后【永久跳过】，就算18:35之后再跑也不再尝试
  → 决策卡⑤『游资埋伏型/追高型』一周填不出，铁律I/H结构性失效

  ★证据：9/16那份完整龙虎榜（58只、机构成绩单5570样本）
    就是 scanner_lhb.py 跑出来的 —— 同样的接口，它能拿到。

修法两条：
  ① 龙虎榜改为【往前回溯最多7个交易日】，拿到就停，
     并★明确标注这是哪一天的数据★（铁律Y③：缓存必须标日期）
  ② 开跑前把【失败接口记忆】里龙虎榜相关的条目清掉，
     否则永久跳过的状态不会自己解除
"""
import io
import os
import sys

MARK = "patch22_lhb_backtrack"
CANDIDATES = ["scanner_cloud.py", "scanner_cloud__1_.py"]

path = None
for c in CANDIDATES:
    if os.path.exists(c):
        path = c
        break
if path is None:
    print("!! patch22 中止：找不到 scanner_cloud.py")
    sys.exit(0)

with io.open(path, "r", encoding="utf-8") as f:
    s = f.read()

if MARK in s:
    print("OK 0: patch22 已打过，跳过（幂等）")
    sys.exit(0)

A = '''    def _do():
        today = now_beijing().strftime("%Y%m%d")
        src, df = multi_source("龙虎榜", [
            ("东财", lambda: ak.stock_lhb_detail_em(start_date=today, end_date=today)),
            ("新浪", lambda: ak.stock_lhb_detail_daily_sina(
                date=today, symbol="涨幅偏离值达7%的证券")),
            ("东财机构", lambda: ak.stock_lhb_jgmmtj_em(
                start_date=today, end_date=today)),
        ])
        if df is None or len(df) == 0:
            w("  今日龙虎榜暂未发布（18:35后再看）")
            return'''

if A not in s:
    print("!! patch22 中止：龙虎榜锚点未命中")
    sys.exit(0)

NEW = '''    def _do():
        # ''' + MARK + '''：先清掉失败记忆里的龙虎榜条目，
        # 否则"连挂3次→永久跳过"的状态永远不会自己解除
        try:
            for _k22 in list(globals().get("FAIL_MEMO", {}) or {}):
                if "龙虎榜" in str(_k22) or "游资" in str(_k22):
                    globals()["FAIL_MEMO"].pop(_k22, None)
                    w(f"  [patch22] 已解除失败记忆：{_k22}")
        except Exception:
            pass

        # ''' + MARK + '''：往前回溯最多7个交易日（龙虎榜18:35才发布，
        # 只查当天必然为空，而"空"会被判成接口失败）
        _bj22 = now_beijing()
        _days22 = []
        _d22 = _bj22
        while len(_days22) < 7:
            if _d22.weekday() < 5:
                _days22.append(_d22.strftime("%Y%m%d"))
            _d22 = _d22 - datetime.timedelta(days=1)

        src, df, use_date = None, None, None
        for _dd22 in _days22:
            src, df = multi_source(f"龙虎榜({_dd22})", [
                ("东财", lambda x=_dd22: ak.stock_lhb_detail_em(
                    start_date=x, end_date=x)),
                ("东财机构", lambda x=_dd22: ak.stock_lhb_jgmmtj_em(
                    start_date=x, end_date=x)),
                ("新浪", lambda x=_dd22: ak.stock_lhb_detail_daily_sina(
                    date=x, symbol="涨幅偏离值达7%的证券")),
            ])
            if df is not None and len(df) > 0:
                use_date = _dd22
                break
            w(f"  {_dd22} 无数据，往前回溯...")

        if df is None or len(df) == 0:
            w("  [报空] 近7个交易日均无龙虎榜数据")
            w("     → 三个接口都拿不到，不是日期问题，需换源")
            return

        # 铁律Y③：缓存数据必须标日期，绝不假装是实时的
        _today22 = _bj22.strftime("%Y%m%d")
        if use_date != _today22:
            w(f"  ⚠️ 这是【{use_date}】的龙虎榜，不是今天({_today22})的。")
            w(f"     龙虎榜18:35后发布，届时重跑可得当日数据。")
        else:
            w(f"  ✅ 当日龙虎榜（{use_date}）")'''

s = s.replace(A, NEW, 1)
print("OK 1: 龙虎榜已改为往前回溯7个交易日 + 清失败记忆 + 标注数据日期")

# 确保 datetime 已导入（原文件通常有，保险起见检查）
if "import datetime" not in s.split("\n\n")[0] and "\nimport datetime" not in s:
    s = "import datetime\n" + s
    print("OK 2: 已补 import datetime")

s = s.rstrip("\n") + "\n\n# " + MARK + "：龙虎榜回溯修复\n"
with io.open(path, "w", encoding="utf-8") as f:
    f.write(s)
print("patch22 完成 → %s" % path)

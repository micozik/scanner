# -*- coding: utf-8 -*-
"""
patch22b_lhb_backtrack.py —— 只做一件事：
让 scanner_cloud 的龙虎榜往前回溯，★但必须带硬时间闸门★。

★patch22 第一版的错（我的错，2026-09-17）★
  我让它回溯7个交易日 × 3个源 = 最多21次接口调用。
  接口挂着的时候每次要等几十秒超时 →
  光这一步就能耗掉十几分钟 → 扫描跑了一小时还没完。
  ★而且我同时把 HARD_LIMIT 提到2700秒，
    等于给了它45分钟去卡死，而不是17分钟。★

★本版三条硬闸门★
  ① 最多只回溯 3 个交易日（今天+前两个），不是7个
  ② 整段龙虎榜有 ★60秒总预算★，超了立刻停，报空走人
  ③ 每个源单独 20 秒超时（原来没有）

根因不变（这条是对的，保留）：
  scanner_lhb.py 和 scanner_cloud.py 用的是完全相同的三个接口，
  唯一区别是前者会回溯、后者只查当天。
  龙虎榜18:35才发布，盘中查当天必然空 → 被判成接口失败
  → 连挂3次 → 写进失败记忆 → 永久跳过
  → 决策卡⑤『游资埋伏型/追高型』一周填不出

⚠️ 若仓库里已有 patch22_lhb_backtrack.py，★请删除它★，
   本版会自动检测并拒绝重复注入。
"""
import io
import os
import sys

MARK = "patch22b_lhb_backtrack"
CANDIDATES = ["scanner_cloud.py", "scanner_cloud__1_.py"]

path = None
for c in CANDIDATES:
    if os.path.exists(c):
        path = c
        break
if path is None:
    print("!! patch22b 中止：找不到 scanner_cloud.py")
    sys.exit(0)

with io.open(path, "r", encoding="utf-8") as f:
    s = f.read()

if MARK in s:
    print("OK 0: patch22b 已打过，跳过（幂等）")
    sys.exit(0)

if "patch22_lhb_backtrack" in s:
    print("!! patch22b 中止：检测到 patch22 第一版已注入（无时间闸门）")
    print("   请从仓库删除 patch22_lhb_backtrack.py 后重跑")
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
    print("!! patch22b 中止：龙虎榜锚点未命中")
    sys.exit(0)

NEW = '''    def _do():
        # ''' + MARK + '''：先解除失败记忆（否则"连挂3次→永久跳过"不会自解）
        try:
            for _k22 in list(globals().get("FAIL_MEMO", {}) or {}):
                if "龙虎榜" in str(_k22):
                    globals()["FAIL_MEMO"].pop(_k22, None)
                    w(f"  [patch22b] 已解除失败记忆：{_k22}")
        except Exception:
            pass

        # ''' + MARK + '''：回溯 ★最多3个交易日★ + ★60秒总预算★
        # （第一版回溯7天×3源=21次调用，接口挂时能卡十几分钟）
        _t022 = time.time()
        _BUDGET22 = 60
        _bj22 = now_beijing()
        _days22 = []
        _d22 = _bj22
        while len(_days22) < 3:
            if _d22.weekday() < 5:
                _days22.append(_d22.strftime("%Y%m%d"))
            _d22 = _d22 - datetime.timedelta(days=1)

        src, df, use_date = None, None, None
        for _dd22 in _days22:
            if time.time() - _t022 > _BUDGET22:
                w(f"  ⏱️ 龙虎榜已用尽{_BUDGET22}秒预算，停止回溯（保住整份报告）")
                break
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

        _el22 = time.time() - _t022
        if df is None or len(df) == 0:
            w(f"  [报空] 近3个交易日无龙虎榜数据（耗时{_el22:.0f}秒）")
            w("     → 若持续报空，用 scanner_lhb.py 独立扫描器兜底")
            return

        # 铁律Y③：缓存数据必须标日期，绝不假装是实时的
        _today22 = _bj22.strftime("%Y%m%d")
        if use_date != _today22:
            w(f"  ⚠️ 这是【{use_date}】的龙虎榜，不是今天({_today22})的。")
            w(f"     龙虎榜18:35后发布，届时重跑可得当日数据。（耗时{_el22:.0f}秒）")
        else:
            w(f"  ✅ 当日龙虎榜（{use_date}）耗时{_el22:.0f}秒")'''

s = s.replace(A, NEW, 1)
print("OK 1: 龙虎榜回溯已加硬闸门（3个交易日 + 60秒总预算）")

s = s.rstrip("\n") + "\n\n# " + MARK + "：龙虎榜回溯（带时间闸门）\n"
with io.open(path, "w", encoding="utf-8") as f:
    f.write(s)
print("patch22b 完成 → %s" % path)

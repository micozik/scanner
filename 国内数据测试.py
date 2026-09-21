# -*- coding: utf-8 -*-
"""
国内数据测试.py —— 在你家里的电脑上跑一次，5分钟，决定整个系统下一步怎么走。

为什么要测：
  扫描器跑在 GitHub 的美国服务器上，东财/巨潮/新浪的个股接口对海外IP封锁，
  所以报告里这些全是【无数据】或报错：
    个股资金流、主力成本、F10、龙虎榜、巨潮公告、北向资金、个股K线位置
  这就是为什么每次选个股都要你截图、为什么我只敢推ETF、为什么赚不到10%。
  如果这些接口在你国内的电脑上能通，就把"取数据"这一步搬到你电脑上，
  一次性救活 5 个死掉的模块。

用法：双击同目录的「运行测试.bat」，或在命令行运行：python 国内数据测试.py
跑完把屏幕截图发给我（或把生成的 测试结果.txt 发我）。
"""
import time
import datetime
import traceback

try:
    import akshare as ak
    import pandas as pd
except ImportError:
    print("还没装库。请先运行：pip install akshare pandas")
    raise SystemExit

today = datetime.date.today()
# 找最近一个工作日（周末跑也能测）
d = today
while d.weekday() >= 5:
    d -= datetime.timedelta(days=1)
D = d.strftime("%Y%m%d")
D_prev = (d - datetime.timedelta(days=1 if d.weekday() > 0 else 3)).strftime("%Y%m%d")

TESTS = [
    # (名称, 函数名, 参数, 这个接口救活哪个模块)
    ("个股资金流(香农芯创)", "stock_individual_fund_flow",
     {"stock": "300475", "market": "sz"}, "卖出五问③资金 / 选股器主力进"),
    ("个股K线(凯盛科技)", "stock_zh_a_hist",
     {"symbol": "600552", "period": "daily", "start_date": "20260601",
      "end_date": D, "adjust": "qfq"}, "位置(60日高低点/缩量)"),
    ("个股基本信息F10(博杰股份)", "stock_individual_info_em",
     {"symbol": "002975"}, "主营/市值/行业"),
    ("龙虎榜-东财", "stock_lhb_detail_em",
     {"start_date": D_prev, "end_date": D_prev}, "埋伏型/追高型识别"),
    ("龙虎榜-机构", "stock_lhb_jgmmtj_em",
     {"start_date": D_prev, "end_date": D_prev}, "机构买卖"),
    ("巨潮公告", "stock_zh_a_disclosure_report_cninfo",
     {"symbol": "", "market": "沪深京", "start_date": D_prev, "end_date": D},
     "持仓公告核对(卖出五问①)"),
    ("东财公告大全(新名)", "stock_notice_report",
     {"symbol": "全部", "date": D_prev}, "持仓公告核对"),
    ("北向资金汇总", "stock_hsgt_fund_flow_summary_em", {}, "北向资金"),
    ("个股资金流排名", "stock_individual_fund_flow_rank",
     {"indicator": "今日"}, "全市场主力净流入排行"),
    ("全市场快照", "stock_zh_a_spot_em", {}, "现价/涨跌幅/换手/市盈率"),
]

lines = []
def out(s=""):
    print(s)
    lines.append(s)

out("=" * 60)
out(f"国内数据测试 | {datetime.datetime.now():%Y-%m-%d %H:%M} | 测试日期 {D}")
out(f"akshare 版本：{getattr(ak, '__version__', '未知')}")
out("=" * 60)

ok_n = 0
for name, fn, kw, use in TESTS:
    t0 = time.time()
    f = getattr(ak, fn, None)
    if f is None:
        out(f"⚪ {name:<22} 函数不存在（{fn}）｜用途：{use}")
        continue
    try:
        df = f(**kw)
        n = 0 if df is None else len(df)
        sec = time.time() - t0
        if n > 0:
            ok_n += 1
            cols = "、".join(list(df.columns)[:6])
            out(f"✅ {name:<22} {n}行 {sec:.1f}秒｜字段：{cols}")
        else:
            out(f"🟡 {name:<22} 返回空 {sec:.1f}秒｜用途：{use}")
    except Exception as e:
        sec = time.time() - t0
        out(f"🔴 {name:<22} {type(e).__name__}: {str(e)[:60]} {sec:.1f}秒")

out("=" * 60)
out(f"结果：{ok_n}/{len(TESTS)} 个接口在你电脑上能用")
out("→ 截图或把 测试结果.txt 发给 AI")
out("=" * 60)

with open("测试结果.txt", "w", encoding="utf-8") as fp:
    fp.write("\n".join(lines))

try:
    import sys
    if sys.stdin and sys.stdin.isatty():
        input("\n按回车关闭")
except Exception:
    pass

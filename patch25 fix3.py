# -*- coding: utf-8 -*-
"""
patch25_fix3.py —— 一次修三个已确认的BUG（2026-09-21 盘中报告暴露）
每一步独立、带OK/!!输出、幂等；某一步锚点不中只跳过那一步，不影响其他两步。

① 公告只有7条 —— patch24 是废的（我的错）
   报告里连「东财-公告大全」这一行都没打印 → hasattr(ak,"stock_notice_report_em")=False
   原因：新版 akshare 把函数改名为 stock_notice_report（去掉了 _em）。
   修法：在 import akshare 之后加别名 —— 旧名不存在而新名存在时，
         ak.stock_notice_report_em = ak.stock_notice_report
         这样原有候选源和 patch24 的多分类合并一起复活。
         另外把【昨天】的公告大全也加进候选（盘中当天公告少）。

② 跳升榜盘中报空 —— patch17c 取到的是空盒子
   [patch17c] 板块快照已存内存：行业0个 / 概念0个
   根因：_rank() 里 `if can_save:` 把【填 store】也锁在15点后了，
         盘中 saved_ind/saved_con 永远是 {}。
   修法：store 永远填；写盘仍由 _save() 里的 can_save 把关（不污染历史库）。

③ 新概念雷达捞出「其中」「发展」「芯片」「亿美元」
   「其中」一词撞出哈药/中际旭创/新易盛等9只，全是噪音。
   修法：扩充停用词（虚词 + 已被热力图覆盖的大类词）。
"""
import io, os, sys

CANDIDATES = ["scanner_cloud.py", "scanner_cloud__1_.py"]
path = next((c for c in CANDIDATES if os.path.exists(c)), None)
if path is None:
    print("!! patch25 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, "r", encoding="utf-8").read()

# ── ① 公告函数改名别名 ──
M1 = "patch25_step1_notice_alias"
if M1 in s:
    print("OK 1: 已打过（公告别名）")
else:
    A = "import akshare as ak\n"
    if A in s:
        s = s.replace(A, A + '''# ''' + M1 + '''：新版akshare改名 stock_notice_report_em → stock_notice_report
try:
    if not hasattr(ak, "stock_notice_report_em") and hasattr(ak, "stock_notice_report"):
        ak.stock_notice_report_em = ak.stock_notice_report
        print("[patch25] 公告大全：已用新名 stock_notice_report 挂到旧名上")
    elif not hasattr(ak, "stock_notice_report_em"):
        print("[patch25] ⚠️ 两个公告大全函数名都不存在 —— 需要换源")
except Exception:
    pass
''', 1)
        B = '            ("东财-公告大全", "stock_notice_report_em", {"symbol": "全部", "date": d}),'
        if B in s:
            s = s.replace(B, B + '\n            ("东财-公告大全-昨日", "stock_notice_report_em", {"symbol": "全部", "date": d2}),', 1)
            print("OK 1: 公告大全别名已加 + 昨日公告已加入候选")
        else:
            print("OK 1: 公告大全别名已加（昨日候选锚点未命中，跳过）")
    else:
        print("!! 1: 锚点 import akshare 未命中，跳过")

# ── ② 盘中也填 store ──
M2 = "patch25_step2_store_always"
if M2 in s:
    print("OK 2: 已打过（store常填）")
else:
    A = '''        if can_save:
            for i, (_, r) in enumerate(df.iterrows(), 1):
                store[str(r[c_name])] = {"pct": round(float(r[c_pct]), 2), "rank": i}'''
    n = s.count(A)
    if n >= 1:
        s = s.replace(A, '''        # ''' + M2 + '''：store 永远填（盘中给雷达用）；写盘仍由 _save 的 can_save 把关
        for i, (_, r) in enumerate(df.iterrows(), 1):
            store[str(r[c_name])] = {"pct": round(float(r[c_pct]), 2), "rank": i}''', 1)
        print("OK 2: _rank 盘中也填 store（写盘规则不变）")
    else:
        print("!! 2: 锚点 if can_save/store 未命中，跳过")

# ── ③ 新概念雷达停用词 ──
M3 = "patch25_step3_stopwords"
if M3 in s:
    print("OK 3: 已打过（停用词）")
else:
    A = "        for _w19, _c19 in _items19:"
    if s.count(A) == 1:
        s = s.replace(A, '''        # ''' + M3 + '''：虚词 + 热力图已覆盖的大类词，不算"新概念"
        _STOP19 |= set([
            "其中", "发展", "进行", "通过", "加快", "推进", "推动", "重点",
            "我国", "全国", "今年", "明年", "以上", "以下", "超过", "达到",
            "同时", "此外", "以来", "近日", "日前", "消息", "透露", "预期",
            "市场", "行业", "产业", "企业", "公司", "板块", "概念", "指数",
            "基金", "亿美元", "万亿", "亿元", "芯片", "半导体", "人工智能",
            "科技", "技术", "硬件", "软件", "电子", "国产", "科创", "电池",
            "封装", "设备", "材料", "能源", "医药", "创新", "新药", "数据",
        ])
''' + A, 1)
        print("OK 3: 新概念雷达停用词已扩充")
    else:
        print("!! 3: 锚点未命中（patch19b 没打？），跳过")

io.open(path, "w", encoding="utf-8").write(s)
print("patch25 完成 → %s" % path)

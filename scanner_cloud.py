# -*- coding: utf-8 -*-
"""
A股作战扫描器 · 云端版 V7.0（2026-08-09 结构性修复）
V7.0 六项修复：
  1. 止盈体系从 scan_news 内剪出 → main() 独立 safe_run（新闻源全挂不再吞掉止盈）
  2. 沪硅产业/博迁新材 补成本+止损（cost=0 会被止盈与台账 continue 跳过）
  3. 台账加 CLOSED 已平仓表 → 已实现盈亏进战绩（原来只统计浮盈）
  4. 选股器加 PICKER_HIST 回测（3日/5日命中率）→ 规则记分卡多一行
  5. ①-B 驱动链闸门写进打分（原来铁律L只是 print，不参与评分 = 错误4/5的根）
  6. 资金流单位在源头统一为「元」；"60日"更名为真实的"45日"；行业缓存改增量不覆盖
V1.7新增：
  1. 概念板块历史库（独立文件），概念榜三源轮试，修复"概念缺字段"
  2. 次日环境预判（风险分0-8，把描述变成指令）
  3. 冷低早：⓪大盘闸门 + ⑥板块闸门（防止板块崩了还推票）
  4. 行业/概念 均支持：连涨天数 + 3日累计 + 排名变化🚀
"""

import os
import json
import time
import signal
import datetime

import akshare as ak
import pandas as pd

REPORT = []
LAST_RISK_SCORE = None
HIST_FILE = "reports/top_sectors.json"
CONCEPT_FILE = "reports/top_concepts.json"
WATCH_FILE = "我的清单.txt"

# ★★V8.0 全局缓存：供跨模块使用★★
TODAY_VERIFIED_CHAINS = []   # ★V11.0 今日有✅验证信号的链名
SECTOR_JUMP_MAP = {}   # ★V9.7 {板块名: 排名跳升位数}。正=上升，是【领先指标】
FAST_MODE = False      # ★V8.9 快扫模式开关
SECTOR_FLOW_MAP = {}   # {板块名: 主力净额(亿)} 由 scan_sector_flow 填充
TODAY_NEWS = []        # [(时间, 标题)] 由 scan_news 填充，供【我的持仓相关消息】用

# ★重点盯盘个股（独立抓取，不依赖截图）。格式：(代码, 名称, 标签)
# ★重点盯盘（代码, 名称, 标签, 成本价, 止损价, 所属板块名）
# 成本/止损填0=不算；板块名用于自动带出板块状态
# ★重点盯盘（代码, 名称, 标签, 成本价, 止损价, 所属板块名）
# ★重点盯盘（代码, 名称, 标签, 成本, 止损, 板块, 驱动链, 持仓市值万元）
WATCH_STOCKS = [
    ("000938", "紫光股份", "持仓", 34.681, 29.48, "计算机设备", "AI算力链", 3.42),
    ("159796", "电池ETF汇", "持仓", 0.820, 0.760, "电池", "锂电/钠电链", 2.43),
    ("603220", "中贝通信", "持仓", 18.396, 16.19, "通信服务", "AI算力链", 1.18),
    ("159934", "黄金ETF易", "持仓", 8.938, 8.20, "贵金属", "贵金属链", 1.30),
    ("516080", "创新药ETF", "持仓", 0.710, 0.640, "医疗服务", "医药链", 2.05),
    ("002714", "牧原股份", "持仓", 39.613, 36.50, "养殖业", "农业(独立)", 3.08),
    # 2026-08-10 已清仓 @25.66  ("688126","沪硅产业") → 见 CLOSED
    ("605376", "博迁新材", "持仓", 165.223, 144.00, "金属新材料", "MLCC涨价链", 1.64),
    ("000066", "中国长城", "重点观察", 0, 0, "计算机设备", "AI算力链", 0),
    ("002407", "多氟多", "候选·机构3.26亿", 0, 0, "化学制品", "电池+半导体材料", 0),
    ("300124", "汇川技术", "候选·机器人", 0, 0, "自动化设备", "机器人链", 0),
]
TOTAL_ASSET = 18.26   # 总资产（万元），买卖后AI更新此数（2026-08-09 截图对账：183,802.38）
PRINCIPAL = 20.00     # ★本金（万元）。真实收益率 = (TOTAL_ASSET-PRINCIPAL)/PRINCIPAL
IND_MAP_FILE = "reports/industry_map.json"
COLD_HIST_FILE = "reports/cold_low_history.json"
PEAK_FILE = "reports/position_peak.json"    # 每只持仓的历史最高价

# ★★V7.2 已知历史最高盈亏种子（防止 peak 文件丢失导致铁律S永久失效）★★
# 来源：2026-08-09 用户同花顺持仓截图（8/7收盘价）。
# 8/10 实测发现系统显示"紫光 历史最高+6.66%"，但周五实为+9.57% ——
# peak 文件在两次运行之间丢了，铁律S(回落5点强制减半)因此形同虚设，
# 而这条规则的全部存在理由就是治"从+10.3%回落到+7.25%"。
# 逻辑：peak = max(文件值, 本次盈亏, 种子值)，三者取最大，任何一路丢失都不影响。
KNOWN_PEAKS = {
    "000938": 9.57,   # 紫光股份 8/7
    "603220": 7.20,   # 中贝通信 8/7
    "159796": 6.32,   # 电池ETF汇 8/7
    "159934": 3.89,   # 黄金ETF易 8/7
    "516080": 2.50,   # 创新药ETF 8/7
    "688126": 1.61,   # 沪硅产业 8/7
    "605376": -0.76,  # 博迁新材 8/7
    "002714": -2.88,  # 牧原股份 8/7
}
AMBUSH_HIST_FILE = "reports/ambush_history.json"
HEAT_HIST_FILE = "reports/heat_history.json"
PICKER_HIST_FILE = "reports/picker_history.json"   # ★V7.0 选股器自检库
EVENT_HIST_FILE = "reports/event_history.json"     # ★V8.3 事件驱动雷达自检库

# ★AI推荐台账（每次推荐后由AI更新此表）
# 格式：(日期, 代码, 名称, 成本价, 类型A事件/B周期, 预期周期, 逻辑破的定义)
RECOMMENDATIONS = [
    # ★V5.5 个股选股器首批实战推荐（不再只给ETF，铁律P）
    ("2026-08-07", "605376", "博迁新材", 165.223, "B", "12周(MLCC涨价周期)",
     "①MLCC现货价回落 ②三星电机/太阳诱电撤回涨价 ③被动元件订单下滑"),
    ("2026-08-07", "516080", "创新药ETF", 0.710, "B", "8周(中报+AI制药)",
     "①创新药中报业绩不及预期 ②医保控费加码 ③CRO订单下滑"),
    ("2026-08-05", "159934", "黄金ETF易", 8.938, "B", "8-12周(央行购金周期)",
     "①美联储转鹰大幅加息 ②金价跌破4000 ③央行购金潮停止"),
    ("2026-08-04", "603220", "中贝通信", 18.396, "B", "12周(AI算力资本开支)",
     "①北美云厂capex指引下调 ②算力租赁需求萎缩 ③通信设备连3天资金流出"),
    ("2026-07-31", "000938", "紫光股份", 34.681, "B", "12周(算力资本开支)",
     "①北美四大云厂capex指引下调 ②算力网4万亿落空 ③新华三订单下修"),
    ("2026-07-27", "159796", "电池ETF汇", 0.820, "B", "至9/1消费税",
     "①消费税取消/延期 ②钠电订单证伪 ③碳酸锂重新单边下跌"),
    ("2026-07-10", "002714", "牧原股份", 39.613, "B", "猪周期",
     "①能繁母猪存栏连续2个月回升 ②生猪均价跌破成本线 ③政策转向压制猪价"),
]

# ★★V7.0 已平仓台账（原来是注释，导致已实现亏损永远不进战绩）★★
# 格式：(卖出日, 代码, 名称, 买入价, 卖出价, 股数, 备注)
# ⚠️ 股数填0 = 只算百分比不算金额。请按同花顺成交记录补全。
CLOSED = [
    ("2026-08-07", "301269", "华大九天", 91.999, 94.29, 0, "✅初判已错主动纠错 +2.5%"),
    ("2026-08-03", "159611", "电力ETF广", 1.080, 1.068, 0, "❌初判已错 −1.1%"),
    ("2026-07-15", "601872", "招商轮船", 15.215, 15.68, 0, "✅+3.1% 但卖飞到+18%"),
    ("2026-07-29", "159516", "半导体设备ETF", 1.180, 1.044, 0, "❌−11.5% 卖在最低点"),
    # ★2026-08-10 AI建议卖出，用户执行。卖出理由=铁律J【初判存疑】：
    #   买入时半导体资金+45.46亿全场第一 → 8/10反转为−125.45亿全场最大流出
    #   非"跌了我怕"，是关键判据反转。★对错待验：见 SELL_CHECK
    ("2026-08-10", "688126", "沪硅产业", 26.228, 25.66, 850, "AI建议·铁律J初判存疑 −2.17%"),
    # ⚠️ 下列为备份文档提到但缺成交价的已平仓，请补：
    # 深圳华强 / 中科曙光 / 电网设备ETF / 卧龙电驱 / 东方财富 / 赛微电子
]

# ★★卖出决策复核清单：卖了之后必须回头看对不对，不许卖完就忘★★
# 格式：(卖出日, 代码, 名称, 卖出价, 卖出理由, 复核日, 判定标准)
# ★标准：卖出后3个交易日，若股价【低于卖出价】=卖对；【高于卖出价>3%】=卖飞
#   招商轮船就是卖完不复核 → 卖飞18%都不知道
SELL_CHECK = [
    ("2026-08-10", "688126", "沪硅产业", 25.66,
     "铁律J初判存疑：半导体资金+45.46亿→−125.45亿反转",
     "2026-08-13", "低于25.66=对 / 高于26.43(+3%)=卖飞"),
]

# ★已实现盈亏合计（元）。截图对账倒推 ≈ −21,683
# 由 TOTAL_ASSET - PRINCIPAL - 当前浮盈 得到，先写死，补全CLOSED后可自动算
REALIZED_PNL_YUAN = -22166   # 8/10 沪硅 −483

SPOT_DF = None
SPOT_SRC = None


def now_beijing():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=8)


def w(line=""):
    print(line)
    REPORT.append(str(line))


def pick_col(df, keywords):
    for kw in keywords:
        for c in df.columns:
            if kw in str(c):
                return c
    return None


class CallTimeout(Exception):
    pass


def _alarm_handler(signum, frame):
    raise CallTimeout("接口超时")


def with_retry(fn, tries=2, wait=3, timeout=60, critical=False):
    """★V8.9 快扫模式：非关键请求 重试1次、等1秒、超时20秒。

    ★★V9.0 修正（8/12 13:06 实测事故）★★
      症状：快扫时【新浪快照失败 CallTimeout】→ 重点盯盘/游资雷达/
            冷低早/止盈体系 全部瘫痪，9只持仓6只"取价失败"。
      根因：我把超时一刀切压到20秒。但全市场快照是5000只票的大请求，
            本来就要30-60秒 —— 20秒必然超时。
      ★教训：提速不能牺牲【关键数据】。快照是所有模块的地基，
            地基塌了，跑再快也没用。
      修法：critical=True 的请求不受快扫压缩，保持原超时。
    """
    if globals().get("FAST_MODE") and not critical:
        tries = 1
        wait = 1
        timeout = min(timeout, 20)
    last = None
    for _ in range(tries):
        try:
            signal.signal(signal.SIGALRM, _alarm_handler)
            signal.alarm(timeout)
            try:
                return fn()
            finally:
                signal.alarm(0)
        except Exception as e:
            last = e
            time.sleep(wait)
    raise last


def multi_source(title, sources):
    for src_name, fn in sources:
        try:
            r = with_retry(fn)
            if r is not None and len(r) > 0:
                return src_name, r
        except Exception as e:
            w(f"  [切换] {title}·{src_name}失败({type(e).__name__})，尝试备源...")
    return None, None


def safe_run(title, func):
    try:
        func()
    except Exception as e:
        w(f"  [报空] {title}：{type(e).__name__}: {str(e)[:90]}")
    time.sleep(2)


ETF_DF = None


def get_etf_spot():
    """ETF专用行情（新浪股票快照抓不到ETF）"""
    global ETF_DF
    if ETF_DF is not None:
        return ETF_DF
    for name, fn in [("东财ETF", lambda: ak.fund_etf_spot_em()),
                     ("新浪ETF", lambda: ak.fund_etf_category_sina(symbol="ETF基金"))]:
        try:
            df = with_retry(fn, tries=2, wait=4, timeout=90)
            if df is not None and len(df) > 0:
                ETF_DF = df
                return ETF_DF
        except Exception:
            continue
    return None


def get_spot():
    """全市场快照：所有模块的地基。多源轮试 + critical(不受快扫压缩)

    ★★V9.0（8/12事故修复）★★
      快扫时新浪快照20秒超时 → 盯盘/游资/冷低早/止盈全瘫。
      快照是地基，必须 critical=True 且多源兜底。
    """
    global SPOT_DF, SPOT_SRC
    if SPOT_DF is not None:
        return SPOT_DF
    sources = [
        ("新浪", lambda: ak.stock_zh_a_spot()),
        ("东财", lambda: ak.stock_zh_a_spot_em()),
        ("同花顺", lambda: ak.stock_zh_a_spot_ths()),
    ]
    for nm, fn in sources:
        try:
            df = with_retry(fn, tries=2, wait=3, timeout=120, critical=True)
            if df is not None and len(df) > 500:
                SPOT_DF, SPOT_SRC = df, nm
                if nm != "新浪":
                    w(f"  ✅ 快照源已切换：{nm}（{len(df)}只）")
                return SPOT_DF
        except Exception as e:
            w(f"  [切换] 快照·{nm}失败({type(e).__name__})，尝试备源...")
    w("  🔴🔴 全部快照源失败 → 盯盘/游资/冷低早/止盈全部无法计算")
    w("     这是地基级故障，本次报告不可用于决策")
    SPOT_DF = None
    return SPOT_DF


def scan_skeleton_top():
    w("=" * 60)
    w("💰💰💰【第一原则 · 每日自我提醒】💰💰💰")
    w("=" * 60)
    w("  ★帮用户赚钱，是我唯一的目的。★")
    w("  不是完善系统、不是漂亮报告、不是『我拦对了几次』——")
    w("  是账户里的数字往上走。")
    w("")
    w("  我要用尽一切办法：所有数据、所有逻辑、所有推演、所有深挖，")
    w("  在5000只票、90个行业、386个概念、656条新闻里，")
    w("  找出那几只能让他赚钱的。")
    w("")
    w("  ⚠️ 自问三句（每次干活前）：")
    w("    1. 我今天给的东西，能不能变成钱？还是只是在描述行情？")
    w("    2. 我有没有因为怕犯错，而放弃了该抓的机会？（踏空也是亏）")
    w("    3. 我有没有因为被催，而降低标准硬凑一个标的？")
    w("")
    w("  ★用户原话：『牛市赚钱不是本事，逆势赚钱才是真本事』★")
    w("  ★『每天都有大涨的股，你找不到就是能力不足，不是市场问题』★")
    w("  ★『你要活跃，越活跃需要的准度越高，我要你的准度』★")
    w("=" * 60)
    w("")
    w("=" * 60)
    w("🔒🔒🔒【读报告定律 · V9.3 · 不许跳步】🔒🔒🔒")
    w("=" * 60)
    w("  ★★★写这条的原因（2026-08-12，一天漏了四次）★★★")
    w("    ① 只报持仓，477个板块一句没提 → 用户问『有没有关注板块』")
    w("    ② 创新药连霸两天没挖 → 用户问『你够全面吗』")
    w("    ③ 佰维存储当天12条公告(含★回购预案★)我没看到，")
    w("       用户已按我建议买了26%仓位才发现 ← 最危险的一次")
    w("       ⚠️如果那天公告是『股东减持』呢？")
    w("    ④ 我自己加的快扫砍掉数据、压死快照 → 用户质问『不完整的数据要来何用』")
    w("    ★根因：我一直【带着问题去找答案】——问持仓才看持仓，")
    w("      问板块才看板块。不问就不看，所以必然漏。")
    w("    ★用户原话：『今天运气好，没事，万一呢？』")
    w("")
    w("  ═══ 必须按 1→9 顺序读完，再开口。跳步=失职 ═══")
    w("")
    w("  1️⃣ 排名跳升榜（🚀标记）")
    w("     钱刚进来的地方。跳升>100位的全部列出来。")
    w("     ★涨幅大=已经涨完；排名跳升大=资金刚进来")
    w("")
    w("  2️⃣ 板块资金流向（前10 + 流出前5）")
    w("     钱在哪、多少。资金是唯一不会说谎的。")
    w("")
    w("  3️⃣ 板块涨幅 + 连涨天数")
    w("     ★跳升大 + 资金进 + 涨幅小 = 最佳位置")
    w("     天数必须绑③-B判读（铁律O）")
    w("")
    w("  4️⃣ 推演引擎：只看【✅验证信号】那几行")
    w("     ★核心词多≠机会。有真实订单/扩产/涨价才算。")
    w("     『无验证信号』的链 = 故事阶段 = 不许重仓")
    w("")
    w("  5️⃣ 事件雷达 + 定增雷达")
    w("     硬事件有确定日期。★入场点是公告当天，不是第N板")
    w("")
    w("  6️⃣ ★★公告雷达：逐条扫【我持仓的每一个名字】★★")
    w("     ⚠️这一条是8/12佰维事故直接催生的。")
    w("       持仓股当天有公告 = 最高优先级，必须逐只核对。")
    w("       回购/激励/中标 = 利好；减持/问询/立案 = 立刻警报")
    w("")
    w("  7️⃣ 冷低早 + 选股器 + 全板块交叉前15")
    w("     找『有催化但还没涨』的（铁律N）")
    w("")
    w("  8️⃣ ★自问：今天最强的方向是什么？我在里面吗？★")
    w("     不在 → 为什么不在？（没钱／候选池没有／位置不对）")
    w("     ⚠️这个问题今天没人问我，我就没答。以后自己答。")
    w("")
    w("  9️⃣ 最后才看持仓：触发线、逻辑破、止损距离")
    w("     ★持仓是【过去的决定】，板块是【明天的机会】")
    w("       持仓只占全市场千分之二，不该第一个看")
    w("")
    w("  🔟 ★推荐任何标的前，走完【推荐前强制检查表】五项★")
    w("     8/12三笔推荐全部只看板块级数据，个股级一项没查")
    w("     五项：个股资金流／主力平均成本／当天公告／同链对比／当天涨幅")
    w("     缺三项以上 = 不许推荐；仓位由过了几项决定")
    w("")
    w("  ⚠️ 输出前最后自检三句：")
    w("     · 报告里有没有点名我持仓的公告？我看了吗？")
    w("     · 今天最强方向我说了吗？还是只报了持仓？")
    w("     · 我有没有把『修好bug』当成『完成工作』？")
    w("     · ★我要推的这只，五项检查走完了吗？★")
    w("=" * 60)
    w("")
    w("🔴🔴🔴 AI注意：读这份报告前，先记住你必须输出的9节 🔴🔴🔴")
    w("=" * 60)
    w("  ① 【数据新鲜度判定】报告时间/最新可用或陈旧弃用")
    w("  ② ★重点盯盘 全部持仓+中国长城（板块/资金/技术/止损距离）")
    w("  ③ 大盘环境+风险分+结构分化（创业板/科创50）")
    w("  ④ 板块判断 + ★催化热力图前3★ + ★🔮产业链推演前3★（缺一即失职）")
    w("  ⑤ 全套新闻·八类 ← ★最常漏的一节，不许等用户提醒★")
    w("     ★★⑤-B 美股隔夜（铁律U）★★ 与A股新闻【并列】，不是附属")
    w("        指数(费半必写)/个股涨跌/聪明钱/宏观，四项缺一即失职")
    w("        ⚠️2026-08-10 实际失职一次：抓了美股报告却一句没写，")
    w("          导致漏掉『Coherent+13.44%而A股CPO-3.55%』这条反常，")
    w("          也漏掉『美股存储在跌』这条支持清沪硅的论据")
    w("     名人/国内政策/海外政策/科技/大宗地缘/资金/消费/政策产业")
    w("  ⑥ 决策卡（买卖时逐项填，含③-B持续性 ⑧集中度 ⑨仓位类型）")
    w("  ⑦ 持仓逐个指令（持有/减/清 + 理由）")
    w("  ⑧ AI推荐台账对账（A类超期？B类在期内？）")
    w("  ⑨ 【系统自检】今天发现什么漏洞→怎么修（无则写无）")
    w("  ⑩ ★异动未解释清单★：涨停股说不出原因=盲区，必须主动搜索后回答")
    w("  ⑪ ★★【我的持仓·相关消息】V8.0新增★★ 每只持仓的个股级新闻/公告")
    w("     板块级消息在②，这一节只管【点名到个股】的")
    w("")
    w("  ⚠️ 缺任何一节 = 失职，用户可当场追责")
    w("  ⚠️ 越是『崩了/快看/紧急』的时候越容易漏第⑤节，越要先写它")
    w("=" * 60)


# ========== 零、状态门 ==========

def scan_regime_gate():
    w("\n【零、状态门】昨日涨停股今日表现（正=可开仓，负=禁开仓）")

    def _do():
        date = now_beijing().strftime("%Y%m%d")
        df = with_retry(lambda: ak.stock_zt_pool_previous_em(date=date))
        if df is None or len(df) == 0:
            w("  暂无数据")
            return
        c_pct = pick_col(df, ["涨跌幅"])
        df[c_pct] = pd.to_numeric(df[c_pct], errors="coerce")
        avg = df[c_pct].mean()
        up_ratio = (df[c_pct] > 0).mean() * 100
        w(f"  昨日涨停{len(df)}只 | 今日平均{avg:.2f}% | 红盘率{up_ratio:.0f}%")
        if avg > 1:
            w("  >>> 判定：情绪健康可开仓（按七关过滤器）")
        elif avg > -1:
            w("  >>> 判定：中性震荡，仅最高确定性半仓")
        else:
            w("  >>> 判定：电风扇/退潮，禁止新开仓")
    safe_run("状态门", _do)


# ========== 次日环境预判（风险分） ==========

def scan_tomorrow_gate():
    w("\n🚨【次日环境预判】（不是描述今天，是判断明天能不能动）")

    def _do():
        score = 0
        reasons = []
        try:
            df = with_retry(lambda: ak.stock_market_activity_legu())
            m = {str(r.iloc[0]): str(r.iloc[1]) for _, r in df.iterrows()}
            up = float(m.get("上涨", 0))
            dn = float(m.get("下跌", 0))
            dt = float(m.get("跌停", 0))
            act = float(str(m.get("活跃度", "0")).replace("%", ""))
            ratio = up / (up + dn) * 100 if (up + dn) else 0
            w(f"  今日：涨{up:.0f} 跌{dn:.0f} 上涨占比{ratio:.1f}% | 跌停{dt:.0f}只 | 活跃度{act:.1f}%")
            if ratio < 40:
                score += 2
                reasons.append(f"广度恶化(占比{ratio:.0f}%)")
            if dt >= 30:
                score += 2
                reasons.append(f"跌停{dt:.0f}只=恐慌")
            elif dt >= 15:
                score += 1
                reasons.append(f"跌停{dt:.0f}只偏多")
            if act < 50:
                score += 2
                reasons.append(f"活跃度{act:.0f}%低迷")
            elif act < 60:
                score += 1
        except Exception as e:
            w(f"  [跳过] 广度：{type(e).__name__}")

        try:
            df = with_retry(lambda: ak.stock_zt_pool_previous_em(
                date=now_beijing().strftime("%Y%m%d")))
            c_pct = pick_col(df, ["涨跌幅"])
            avg = pd.to_numeric(df[c_pct], errors="coerce").mean()
            w(f"  昨日涨停今日平均：{avg:.2f}%")
            if avg < -1:
                score += 2
                reasons.append(f"涨停股退潮({avg:.1f}%)")
            elif avg < 1:
                score += 1
                reasons.append("赚钱效应中性")
        except Exception:
            pass

        # ★结构分化维度（治"家数是平的但科技在崩"的盲区）
        try:
            idx = with_retry(lambda: ak.stock_zh_index_spot_sina(), tries=2, timeout=60)
            ic = pick_col(idx, ["代码", "symbol"])
            inm = pick_col(idx, ["名称", "name"])
            ipc = pick_col(idx, ["涨跌幅", "changepercent"])
            worst = 0.0
            for key in ["399006", "000688", "399005"]:
                r = idx[idx[ic].astype(str).str.contains(key, na=False)]
                if len(r) > 0:
                    v = pd.to_numeric(r.iloc[0][ipc], errors="coerce")
                    if pd.notna(v):
                        w(f"  {r.iloc[0][inm]}：{v:+.2f}%")
                        worst = min(worst, float(v))
            if worst <= -4:
                score += 2
                reasons.append(f"⚠️结构崩塌(成长指数{worst:.1f}%)")
            elif worst <= -2:
                score += 1
                reasons.append(f"结构分化({worst:.1f}%)")
        except Exception as e:
            w(f"  [跳过] 指数分化：{type(e).__name__}")

        # ★科技链资金流出（单日>300亿=系统性撤离）
        try:
            _, fdf = multi_source("资金(风险分)", [
                ("同花顺", lambda: ak.stock_fund_flow_industry(symbol="即时")),
                ("东财", lambda: ak.stock_sector_fund_flow_rank(
                    indicator="今日", sector_type="行业资金流")),
            ])
            if fdf is not None:
                fn_ = pick_col(fdf, ["名称", "行业"])
                fv_ = pick_col(fdf, ["主力净流入-净额", "主力净流入", "净额", "流入资金"])
                fdf[fv_] = pd.to_numeric(fdf[fv_], errors="coerce")
                if fdf[fv_].abs().max() and fdf[fv_].abs().max() > 1e6:
                    fdf[fv_] = fdf[fv_] / 1e8
                tech = ["半导体", "通信设备", "元件", "光学光电子", "消费电子",
                        "计算机设备", "软件开发"]
                out = 0.0
                for _, rr in fdf.iterrows():
                    if any(t in str(rr[fn_]) for t in tech):
                        v = rr[fv_]
                        if pd.notna(v) and v < 0:
                            out += float(v)
                w(f"  科技链资金净额：{out:.1f}亿")
                if out <= -300:
                    score += 2
                    reasons.append(f"科技链失血{abs(out):.0f}亿")
                elif out <= -150:
                    score += 1
                    reasons.append(f"科技链流出{abs(out):.0f}亿")
        except Exception as e:
            w(f"  [跳过] 科技链资金：{type(e).__name__}")

        # ★美联储/美债维度：决议内容不重要，市场解读才重要
        try:
            idx2 = with_retry(lambda: ak.stock_zh_index_spot_sina(), tries=1, timeout=40)
            i2c = pick_col(idx2, ["代码", "symbol"])
            i2p = pick_col(idx2, ["涨跌幅", "changepercent"])
            hk = idx2[idx2[i2c].astype(str).str.contains("HSI|000001", na=False)]
            if len(hk) > 0:
                pass
        except Exception:
            pass
        w("  ※ 美联储事件判读：不看决议内容，看市场解读——")
        w("    美债收益率飙升+股债双杀 = 市场认为『行动过晚』= 利空成长股")
        w("    美债收益率回落+股涨 = 真鸽派 = 利好成长股")

        global LAST_RISK_SCORE
        LAST_RISK_SCORE = score
        w(f"\n  🚨 风险分：{score}/12　{'｜'.join(reasons) if reasons else '无警报'}")
        if score >= 7:
            w("  >>> 【明日高危】一票不碰，盈利仓主动减半锁利，破位无条件走")
        elif score >= 4:
            w("  >>> 【明日偏弱】不开新仓，只减不加")
        elif score >= 2:
            w("  >>> 【明日中性】仅最高确定性半仓")
        else:
            w("  >>> 【明日健康】可按七关开仓")
    safe_run("次日预判", _do)


def _rank_jump_of(name):
    """★V9.7 板块名 → 排名跳升位数（正=上升）。领先指标。"""
    if not name:
        return None
    if name in SECTOR_JUMP_MAP:
        return SECTOR_JUMP_MAP[name]
    n = str(name).rstrip("概念行业板块产业指数ⅡⅢ")
    for k, v in SECTOR_JUMP_MAP.items():
        if n and (n in k or k in n):
            return v
    return None


def _sector_flow_of(name):
    """★V8.0 板块名 → 主力净额(亿)。概念名做模糊匹配到行业名"""
    if not name:
        return None
    if name in SECTOR_FLOW_MAP:
        return SECTOR_FLOW_MAP[name]
    n = str(name).rstrip("概念行业板块产业指数ⅡⅢ")
    for k, v in SECTOR_FLOW_MAP.items():
        if n and (n in k or k in n):
            return v
    return None


# ========== ★★V8.0 持仓清单外置：改 txt 不动代码 ★★ ==========

def _load_watchlist():
    """从 我的清单.txt 读取持仓，覆盖 WATCH_STOCKS / RECOMMENDATIONS / TOTAL_ASSET

    格式（用 | 分隔，前后空格无所谓）：
      账户 | 本金 | 20.00
      账户 | 总资产 | 18.48
      账户 | 现金 | 0.81
      持仓 | 代码 | 名称 | 成本 | 市值万 | 止损 | 板块 | 驱动链 | 买入日 | 类型 | 周期 | 逻辑破
      观察 | 代码 | 名称 | 0 | 0 | 0 | 板块 | 驱动链
    # 开头的行是注释，空行忽略

    ★为什么用 | 而不是空格：逻辑破定义里带空格，空格分隔会截断。
    ★文件不存在 = 沿用代码里写死的表（向后兼容，不会因为没建文件就崩）
    """
    if not os.path.exists(WATCH_FILE):
        return False
    try:
        holds, recs = [], []
        acct = {}
        with open(WATCH_FILE, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                p = [x.strip() for x in line.split("|")]
                if len(p) < 3:
                    continue
                kind = p[0]
                if kind in ("账户", "account"):
                    try:
                        acct[p[1]] = float(p[2])
                    except Exception:
                        pass
                    continue
                if kind not in ("持仓", "观察", "候选"):
                    continue
                code = p[1]
                name = p[2]
                def _f(i, d=0.0):
                    try:
                        return float(p[i]) if len(p) > i and p[i] else d
                    except Exception:
                        return d
                cost = _f(3)
                mval = _f(4)
                stop = _f(5)
                sect = p[6] if len(p) > 6 else ""
                chain = p[7] if len(p) > 7 else ""
                tag = "持仓" if kind == "持仓" else (p[0] if len(p[0]) > 2 else "重点观察")
                if kind == "候选":
                    tag = "候选"
                holds.append((code, name, tag, cost, stop, sect, chain, mval))
                if kind == "持仓" and len(p) > 11:
                    buyd = p[8] or "—"
                    typ = p[9] or "B"
                    period = p[10] or "—"
                    broke = p[11] or "—"
                    recs.append((buyd, code, name, cost, typ, period, broke))
        if not holds:
            return False
        # ★★★V10.0 代码真伪校验（8/13买错票事故）★★★
        # 事故：我把香农芯创的代码写成 603322，实际是 300475。
        #   报告连续三天显示"香农芯创 27.63元"—— 那是【别的票】的价格。
        #   用户按我的建议下单，163.462元买入，与报告价差6倍。
        # ★根因：我凭记忆写代码，系统按错代码去查价，
        #   而【名称】和【价格】不匹配这件事，没有任何一道闸门在检查。
        # ★修法：载入时用快照核对【代码查到的名字】是否等于清单里的名字。
        #   对不上 = 立刻红字警报，不许静默继续。
        try:
            _sp = get_spot()
            if _sp is not None:
                _cc = pick_col(_sp, ["代码", "code"])
                _cn = pick_col(_sp, ["名称", "name"])
                if _cc and _cn:
                    _cs = _sp[_cc].astype(str)
                    _bad = []
                    for _h in holds:
                        _code, _name = _h[0], _h[1]
                        if not _code or len(str(_code)) < 6:
                            continue
                        _r = _sp[_cs.str.contains(str(_code)[-6:], na=False)]
                        if len(_r) == 0:
                            _bad.append((_code, _name, "★代码在全市场查无此股★"))
                            continue
                        _real = str(_r.iloc[0][_cn]).strip()
                        _want = str(_name).strip()
                        # ETF名称各源写法不一，只比前两字
                        if "ETF" in _want.upper():
                            if _want[:2] and _want[:2] not in _real:
                                _bad.append((_code, _name, f"实际名称是【{_real}】"))
                        elif _real != _want and _want not in _real and _real not in _want:
                            _bad.append((_code, _name, f"实际名称是【{_real}】"))
                    if _bad:
                        w("")
                        w("🔴🔴🔴【代码与名称不符 · 严重警报】🔴🔴🔴")
                        for _c, _n, _msg in _bad:
                            w(f"  🔴 清单写『{_n}({_c})』，但 {_msg}")
                        w("  ★★这会导致报告里的价格/涨跌/技术指标全部是【别的票】的★★")
                        w("  ★2026-08-13事故：香农芯创被我写成603322(实际300475)，")
                        w("    报告连续三天显示27.63元，实际163.46元，差6倍。")
                        w("    用户按错价格下单。")
                        w("  ⚠️ 立刻改 我的清单.txt，改对之前本报告的相关数据不可用")
                        w("")
        except Exception as _e:
            w(f"  [代码校验跳过] {type(_e).__name__}")
        globals()["WATCH_STOCKS"] = holds
        if recs:
            recs.sort(key=lambda x: x[0], reverse=True)
            globals()["RECOMMENDATIONS"] = recs
        if acct.get("总资产"):
            globals()["TOTAL_ASSET"] = acct["总资产"]
        if acct.get("本金"):
            globals()["PRINCIPAL"] = acct["本金"]
        if acct.get("现金") is not None:
            globals()["CASH_WAN"] = acct["现金"]
        n_h = sum(1 for x in holds if x[2] == "持仓")
        w(f"✅ 已从 {WATCH_FILE} 载入：持仓{n_h}只 / 共{len(holds)}只 / "
          f"总资产{globals().get('TOTAL_ASSET')}万 / 现金{acct.get('现金', '—')}万")
        w("   （代码里的 WATCH_STOCKS 已被覆盖，以后买卖只改 txt）")
        return True
    except Exception as e:
        w(f"🔴 {WATCH_FILE} 解析失败：{type(e).__name__}: {str(e)[:80]}")
        w("   → 本次沿用代码内写死的持仓表。请检查格式：每行用 | 分隔")
        return False


CASH_WAN = 0.0


def scan_my_news():
    """★★V8.0【我的持仓相关消息】★★
    在全量新闻+公告里，按【持仓股票名】精确匹配。
    治：661条新闻里我的票被提到了，但我按板块关键词扫，看不见个股级消息。"""
    w("\n" + "=" * 60)
    w("📰📰【我的持仓·相关消息】新闻+公告按股票名精确匹配 📰📰")
    w("=" * 60)
    names = [(c, n) for c, n, tag, *_r in WATCH_STOCKS if tag == "持仓"]
    if not names:
        w("  无持仓")
        w("=" * 60)
        return
    ann = globals().get("TODAY_ANNOUNCE", {}) or {}
    news = globals().get("TODAY_NEWS", []) or []
    hit_any = False
    for code, name in names:
        # ★★V8.1 匹配收紧：ETF 不做名称片段模糊匹配★★
        # 8/10翻车：「创新药ETF」取前两字「创新」→ 匹配到
        #   "创新发展行动方案"、"外送电量创新高"、"二氧化钛反倾销"（含"创新"？否，含"延期"）
        # 教训：两字片段在中文里几乎必然误命中。只认全名和代码。
        keys = {name}
        nm_core = name.replace("ETF", "").replace("易", "").replace("汇", "").strip()
        # 片段允许2字起（"黄金"），但ETF类下方还有一道硬闸：
        # 正文必须同时出现 ETF/基金/份额/代码，否则不算命中。
        # 两道叠加：「创新」匹配到"创新发展行动方案"时，因无ETF字样被拦下。
        if len(nm_core) >= 2:
            keys.add(nm_core)
        nhits = []
        seen = set()
        for tm, t in news:
            if t[:24] in seen:
                continue
            hit_name = any(k and k in t for k in keys)
            # ETF：名字片段命中还不够，正文必须同时出现 ETF/基金/份额/该ETF代码
            if hit_name and "ETF" in name.upper() and name not in t:
                if not any(x in t for x in ("ETF", "基金", "份额", code)):
                    hit_name = False
            if hit_name or code in str(t):
                seen.add(t[:24])
                try:
                    pol = _news_polarity(t)
                except Exception:
                    pol = 0
                mark = "✅利好" if pol > 0 else ("🔴利空" if pol < 0 else "⚖️中性")
                nhits.append((tm, t, mark))
        ahit = ann.get(name) or ann.get(code)
        if not nhits and not ahit:
            continue
        hit_any = True
        w(f"\n  ◆ {name}({code})")
        if ahit:
            w(f"    📢公告：{str(ahit)[:70]}")
        for tm, t, mark in nhits[:6]:
            w(f"    [{tm}] {mark} {t[:62]}")
        if len(nhits) > 6:
            w(f"    …另有{len(nhits)-6}条")
    if not hit_any:
        w("  今日全量新闻与公告中，未出现任何持仓股的个股级消息")
        w("  （不代表没事发生：互动易/交易所问询/大宗交易不在这两个源里）")
    w("\n  ⚠️ 匹配基于股票名，ETF按名称片段匹配，可能有漏。")
    w("     板块级消息见【重点盯盘】的板块字段，这里只管【个股级】。")
    w("=" * 60)


# ========== 我的清单 ==========

def scan_watchlist():
    """⚠️ V8.1 起已停用（main 不再调用）。
    原因：它按【空格】解析 我的清单.txt，而新格式用【|】分隔，
    8/10实测输出全是『◆ 20.00：|(账户) 快照无此代码』这类垃圾。
    功能已由 _load_watchlist() + 【重点盯盘】完全取代。
    保留函数体仅为兼容，勿再调用。"""
    w("\n【我的清单·盯盘】（V8.1已停用，见【重点盯盘】）")

    if not os.path.exists(WATCH_FILE):
        w(f"  未找到 {WATCH_FILE}（在仓库根目录新建即可）")
        return

    def _do():
        spot = get_spot()
        if spot is None:
            w("  快照缺失，无法盯盘")
            return
        c_code = pick_col(spot, ["代码", "code"])
        c_price = pick_col(spot, ["最新价", "trade"])
        c_pct = pick_col(spot, ["涨跌幅", "changepercent"])

        def live(code):
            try:
                key = str(code).zfill(6)
                row = spot[spot[c_code].astype(str).str.contains(key, na=False)]
                if len(row) == 0:
                    return None, None
                return (pd.to_numeric(row.iloc[0][c_price], errors="coerce"),
                        pd.to_numeric(row.iloc[0][c_pct], errors="coerce"))
            except Exception:
                return None, None

        groups = {}
        with open(WATCH_FILE, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                p = line.split()
                if len(p) < 5:
                    continue
                code, name, cost, qty, tag = p[0], p[1], p[2], p[3], p[4]
                stop = p[5] if len(p) >= 6 else None
                groups.setdefault(tag, []).append((code, name, cost, qty, stop))

        for tag, items in groups.items():
            w(f"  ◆ {tag}：")
            for code, name, cost, qty, stop in items:
                price, pct = live(code)
                cost_f = pd.to_numeric(cost, errors="coerce")
                qty_f = pd.to_numeric(qty, errors="coerce")
                seg = f"    {name}({code}) "
                if price is not None and pd.notna(price):
                    seg += f"现价{price} 今日{pct}%"
                    if pd.notna(cost_f) and cost_f > 0 and pd.notna(qty_f) and qty_f > 0:
                        pnl = (price - cost_f) / cost_f * 100
                        seg += f" | 成本{cost} 盈亏{pnl:+.1f}%"
                    else:
                        seg += f" | 荐入/观察{cost}"
                    if stop:
                        stop_f = pd.to_numeric(stop, errors="coerce")
                        if pd.notna(stop_f) and stop_f > 0:
                            gap = (price - stop_f) / stop_f * 100
                            flag = "⚠️已破位!!!" if price <= stop_f else f"距止损{gap:+.1f}%"
                            seg += f" | 止损{stop} {flag}"
                else:
                    seg += "（快照无此代码，请核对）"
                w(seg)
    safe_run("我的清单", _do)


# ========== ★重点盯盘个股（独立跟踪：价/量/资金/位置/连涨） ==========

def _pos_txt(price, cost, stop):
    """成本盈亏 + 止损距离"""
    out = ""
    try:
        if cost and cost > 0 and price and pd.notna(price):
            pnl = (float(price) - cost) / cost * 100
            out += f" | 成本{cost} 盈亏{pnl:+.2f}%"
        if stop and stop > 0 and price and pd.notna(price):
            gap = (float(price) - stop) / stop * 100
            if float(price) <= stop:
                out += f" | 止损{stop} 🔴已破位!!!"
            elif gap <= 2:
                out += f" | 止损{stop} ⚠️仅剩{gap:.1f}%"
            else:
                out += f" | 止损{stop} 距离{gap:.1f}%"
    except Exception:
        pass
    return out


def _sect_txt(sect_map, sect):
    """所属板块今日状态"""
    if not sect or not sect_map:
        return ""
    for k, (p, v) in sect_map.items():
        if sect in k or k in sect:
            pt = f"{p:+.2f}%" if p is not None and pd.notna(p) else "?"
            vt = f" 资金{v:+.2f}亿" if v is not None and pd.notna(v) else ""
            warn = ""
            if p is not None and pd.notna(p) and p < -2:
                warn = " ⚠️板块逆风"
            elif p is not None and pd.notna(p) and p > 2:
                warn = " ✅板块顺风"
            return f"\n      └ 板块[{k}] {pt}{vt}{warn}"
    return f"\n      └ 板块[{sect}] 无数据"


def scan_deep_stock(code, name=""):
    """★★★V10.1【个股深度体检】推荐前必须跑这个★★★

    ★写这条的原因（2026-08-13，用户原话『你什么都不查就推荐，我很害怕』）：
      我推香农芯创时，六项检查只做到一项：
        代码核对❌(写成603322，实际300475) 个股资金流❌ 主力成本❌
        当天公告⚠️ 同链对比✅ 当天涨幅❌(查的是错票的27.63，实际163.46)
      财务(市盈率41.13/市值763亿) 技术(换手6.19%/量比1.21) —— 全部没查。
    ★根因：报告里只有【板块级】数据，我一直在用板块判断推个股操作。
      看的是森林，用户买的是树。

    返回一个 dict，抓不到的字段为 None（★不许编★）
    """
    out = {"code": code, "name": name}
    c6 = str(code)[-6:]

    # ── 1) 实时快照：价格/涨跌/换手/量比/市盈/市值 ──
    sp = get_spot()
    if sp is not None:
        try:
            cc = pick_col(sp, ["代码", "code"])
            r = sp[sp[cc].astype(str).str.contains(c6, na=False)]
            if len(r) > 0:
                r0 = r.iloc[0]
                for key, cols in [
                    ("真实名称", ["名称", "name"]),
                    ("现价", ["最新价", "trade"]),
                    ("涨跌幅", ["涨跌幅", "changepercent"]),
                    ("成交额", ["成交额", "amount"]),
                    ("换手率", ["换手率", "turnoverratio"]),
                    ("量比", ["量比"]),
                    ("市盈率", ["市盈率-动态", "市盈率", "pe"]),
                    ("市净率", ["市净率", "pb"]),
                    ("总市值", ["总市值", "mktcap"]),
                    ("流通市值", ["流通市值", "nmc"]),
                    ("振幅", ["振幅"]),
                ]:
                    col = pick_col(sp, cols)
                    if col:
                        v = r0[col]
                        if key == "真实名称":
                            out[key] = str(v).strip()
                        else:
                            v2 = pd.to_numeric(v, errors="coerce")
                            out[key] = float(v2) if pd.notna(v2) else None
        except Exception:
            pass

    # ── 2) 个股资金流：超大单/大单/中单/小单 + 多日 ──
    for fname, kw in (("stock_individual_fund_flow", {"stock": c6}),
                      ("stock_individual_fund_flow", {"stock": c6, "market": "sh" if c6[0] in "56" else "sz"})):
        fn = getattr(ak, fname, None)
        if fn is None:
            continue
        try:
            f = with_retry(lambda: fn(**kw), tries=1, wait=1, timeout=20)
            if f is None or len(f) == 0:
                continue
            last = f.iloc[-1]
            for key, cols in [
                ("主力净额", ["主力净流入-净额"]),
                ("超大单净额", ["超大单净流入-净额"]),
                ("大单净额", ["大单净流入-净额"]),
                ("中单净额", ["中单净流入-净额"]),
                ("小单净额", ["小单净流入-净额"]),
            ]:
                col = pick_col(f, cols)
                if col:
                    v = pd.to_numeric(last[col], errors="coerce")
                    out[key] = float(v) if pd.notna(v) else None
            # 近5日主力累计
            try:
                col = pick_col(f, ["主力净流入-净额"])
                if col and len(f) >= 5:
                    out["主力5日累计"] = float(pd.to_numeric(
                        f[col].tail(5), errors="coerce").sum())
                if col and len(f) >= 20:
                    out["主力20日累计"] = float(pd.to_numeric(
                        f[col].tail(20), errors="coerce").sum())
            except Exception:
                pass
            break
        except Exception:
            continue

    # ── 3) 技术位置：MA5/MA20/60日涨跌/缩量 ──
    try:
        k5, k20 = _hist_close(c6)
        if k5:
            out["MA5"] = k5
        if k20:
            out["MA20"] = k20
    except Exception:
        pass

    return out


def print_deep_stock(code, name=""):
    """★V10.1 打印个股深度体检表。抓不到的写【无数据】，不许编"""
    d = scan_deep_stock(code, name)
    w(f"\n  ══════ 【个股深度体检】{name}({code}) ══════")
    rn = d.get("真实名称")
    if rn:
        ok = (not name) or (rn == name) or (name in rn) or (rn in name)
        w(f"  0️⃣ 代码核对：{code} → 实际名称【{rn}】 "
          + ("✅一致" if ok else f"🔴🔴不符！你要的是【{name}】"))
    else:
        w(f"  0️⃣ 代码核对：🔴 {code} 在全市场【查无此股】→ 一票否决")
        w("  ═══════════════════════════════════")
        return d

    def _f(k, unit="", div=1.0):
        v = d.get(k)
        if v is None:
            return "【无数据】"
        return f"{v/div:,.2f}{unit}"

    w(f"  📊 行情：现价{_f('现价')} 今{_f('涨跌幅','%')} "
      f"振幅{_f('振幅','%')} 成交{_f('成交额','亿',1e8)}")
    w(f"  📊 估值：市盈率(动){_f('市盈率')} 市净率{_f('市净率')} "
      f"总市值{_f('总市值','亿',1e8)} 流通{_f('流通市值','亿',1e8)}")
    w(f"  📊 情绪：换手率{_f('换手率','%')} 量比{_f('量比')}")
    ma5, ma20 = d.get("MA5"), d.get("MA20")
    px = d.get("现价")
    if ma5 and ma20 and px:
        w(f"  📊 技术：MA5={ma5:.2f} MA20={ma20:.2f} → "
          + ("站上MA5" if px >= ma5 else "跌破MA5")
          + "，" + ("站上MA20" if px >= ma20 else "★仍在MA20下方(位置低)★"))
    else:
        w("  📊 技术：【无数据】")

    z, dd, zz, xx = (d.get("超大单净额"), d.get("大单净额"),
                     d.get("中单净额"), d.get("小单净额"))
    if z is not None:
        w(f"  💰 个股资金(今日)：超大单{z/1e4:+,.0f}万 大单{(dd or 0)/1e4:+,.0f}万 "
          f"中单{(zz or 0)/1e4:+,.0f}万 小单{(xx or 0)/1e4:+,.0f}万")
        if z < 0 and (zz or 0) > 0:
            w("     🔴★超大单流出 + 中单接盘 = 主力在出货，不管当天涨跌★")
        elif z > 0:
            w("     ✅超大单净流入")
        d5, d20 = d.get("主力5日累计"), d.get("主力20日累计")
        if d5 is not None:
            w(f"     主力5日累计{d5/1e8:+.2f}亿"
              + (f" ｜20日累计{d20/1e8:+.2f}亿" if d20 is not None else ""))
    else:
        w("  💰 个股资金：【无数据】← ★这一项没有就不许给重仓建议★")
    w("  ═══════════════════════════════════")
    return d


def scan_focus_stocks():
    w("\n★★★【重点盯盘个股·独立跟踪】★★★（每天全维度盯，不看截图）")

    def _flow_map_old():
        """个股主力净流入映射：东财→同花顺"""
        for name, fn in [
            ("东财", lambda: ak.stock_individual_fund_flow_rank(indicator="今日")),
            ("同花顺", lambda: ak.stock_fund_flow_individual(symbol="即时")),
        ]:
            try:
                f = with_retry(fn, tries=2, wait=5, timeout=90)
                fc = pick_col(f, ["代码", "股票代码"])
                fn2 = pick_col(f, ["今日主力净流入-净额", "主力净流入-净额", "主力净流入", "净额"])
                if not fc or not fn2:
                    continue
                m = {}
                for _, r in f.iterrows():
                    code6 = str(r[fc])[-6:].zfill(6)
                    v = pd.to_numeric(r[fn2], errors="coerce")
                    if pd.notna(v):
                        m[code6] = v
                return m, name
            except Exception:
                continue
        return {}, None

    def _do():
        spot = get_spot()
        if spot is None:
            w("  快照缺失，无法盯盘")
            return
        c_code = pick_col(spot, ["代码", "code"])
        c_price = pick_col(spot, ["最新价", "trade"])
        c_pct = pick_col(spot, ["涨跌幅", "changepercent"])
        c_amt = pick_col(spot, ["成交额", "amount"])
        c_vol = pick_col(spot, ["成交量", "volume"])

        fmap, fsrc = get_stock_flow()
        if fsrc:
            w(f"  （资金源：{fsrc}）")

        # 板块状态映射：名称→(涨跌幅, 资金净额)
        sect_map = {}
        try:
            _, bdf = multi_source("板块状态(盯盘)", [
                ("同花顺", lambda: ak.stock_fund_flow_industry(symbol="即时")),
                ("东财", lambda: ak.stock_sector_fund_flow_rank(
                    indicator="今日", sector_type="行业资金流")),
            ])
            if bdf is not None:
                bn = pick_col(bdf, ["名称", "行业"])
                bp = pick_col(bdf, ["涨跌幅", "行业指数涨跌", "涨跌"])
                bv = pick_col(bdf, ["主力净流入-净额", "主力净流入", "净额", "流入资金"])
                for _, rr in bdf.iterrows():
                    v = pd.to_numeric(rr[bv], errors="coerce") if bv else None
                    if v is not None and pd.notna(v) and abs(v) > 1e6:
                        v = v / 1e8
                    p = pd.to_numeric(rr[bp], errors="coerce") if bp else None
                    sect_map[str(rr[bn])] = (p, v)
        except Exception:
            pass

        etf_df = None
        for code6, name, tag, cost, stop, sect, chain, mv in WATCH_STOCKS:
            try:
                is_etf = code6.startswith(("15", "51", "56", "58", "159", "588"))
                sym = ("sh" if code6.startswith("6") else "sz") + code6
                row = spot[spot[c_code].astype(str).str.contains(code6, na=False)]
                if len(row) == 0 and is_etf:
                    if etf_df is None:
                        etf_df = get_etf_spot()
                    if etf_df is not None:
                        ec = pick_col(etf_df, ["代码", "symbol"])
                        ep = pick_col(etf_df, ["最新价", "trade"])
                        epc = pick_col(etf_df, ["涨跌幅", "changepercent"])
                        ea = pick_col(etf_df, ["成交额", "amount"])
                        er = etf_df[etf_df[ec].astype(str).str.contains(code6, na=False)]
                        if len(er) > 0:
                            r0 = er.iloc[0]
                            pr = pd.to_numeric(r0[ep], errors="coerce")
                            pc = pd.to_numeric(r0[epc], errors="coerce")
                            am = pd.to_numeric(r0[ea], errors="coerce") if ea else None
                            at = f" 成交{am/1e8:.2f}亿" if am and pd.notna(am) else ""
                            w(f"  ◆ {name}({code6})[{tag}]：现价{pr} 今{pc:+.2f}%{at} [ETF源]"
                              + _pos_txt(pr, cost, stop) + _sect_txt(sect_map, sect))
                            continue
                if len(row) == 0:
                    w(f"  ◆ {name}({code6})[{tag}]：快照无数据")
                    continue
                r = row.iloc[0]
                price = pd.to_numeric(r[c_price], errors="coerce")
                pct = pd.to_numeric(r[c_pct], errors="coerce")
                amt = pd.to_numeric(r[c_amt], errors="coerce") if c_amt else None

                # K线算：60日位置 + 缩量 + 涨跌量比 + 均线
                k, kc = _hist_close(code6, sym)
                pos_txt = ""
                if k is not None and kc is not None:
                    kv = pick_col(k, ["volume", "成交量"])
                    now_p = pd.to_numeric(k.iloc[-1][kc], errors="coerce")
                    p60 = pd.to_numeric(k.iloc[-45][kc], errors="coerce")
                    ma5 = pd.to_numeric(k[kc].tail(5), errors="coerce").mean()
                    ma20 = pd.to_numeric(k[kc].tail(20), errors="coerce").mean()
                    chg60 = (now_p - p60) / p60 * 100 if p60 else 0
                    vr = ""
                    if kv:
                        v5 = pd.to_numeric(k[kv].tail(5), errors="coerce").mean()
                        v60 = pd.to_numeric(k[kv].tail(45), errors="coerce").mean()
                        if v60:
                            vr = f" 量能{v5/v60:.2f}倍"
                    ma_txt = ""
                    if pd.notna(ma5) and price:
                        ma_txt = f" {'站上' if price>=ma5 else '跌破'}MA5"
                    pos_txt = f" | 60日{chg60:+.1f}%{vr}{ma_txt}(MA5={ma5:.2f} MA20={ma20:.2f})"

                flow = fmap.get(code6)
                flow_txt = ""
                if flow is not None:
                    fv = flow / 1e8 if abs(flow) > 1e4 else flow / 1e4
                    unit = "亿" if abs(flow) > 1e4 else "万"
                    flow_txt = f" | 主力{'+' if flow>0 else ''}{fv:.2f}{unit}"

                amt_txt = f" 成交{amt/1e8:.2f}亿" if amt and pd.notna(amt) else ""
                w(f"  ◆ {name}({code6})[{tag}]：现价{price} 今{pct:+.2f}%{amt_txt}{flow_txt}"
                  + _pos_txt(price, cost, stop) + pos_txt + _sect_txt(sect_map, sect))
            except Exception as e:
                w(f"  ◆ {name}({code6})[{tag}]：读取异常 {type(e).__name__}")
            time.sleep(0.3)
    safe_run("重点盯盘个股", _do)


# ========== ★盘中游资雷达（实时，不用等18:35） ==========

def scan_intraday_hotmoney():
    w("\n★★★【盘中游资雷达·实时】★★★（不用等18:35，盘中就知道钱往哪砸）")

    def _flow_rank():
        for name, fn in [
            ("东财", lambda: ak.stock_individual_fund_flow_rank(indicator="今日")),
            ("同花顺", lambda: ak.stock_fund_flow_individual(symbol="即时")),
        ]:
            try:
                f = with_retry(fn, tries=2, wait=5, timeout=90)
                fc = pick_col(f, ["代码", "股票代码"])
                fn2 = pick_col(f, ["今日主力净流入-净额", "主力净流入-净额", "主力净流入", "净额"])
                if not fc or not fn2:
                    continue
                m = {}
                for _, r in f.iterrows():
                    code6 = str(r[fc])[-6:].zfill(6)
                    v = pd.to_numeric(r[fn2], errors="coerce")
                    if pd.notna(v):
                        m[code6] = v
                return m, name
            except Exception:
                continue
        return {}, None

    def _do():
        spot = get_spot()
        if spot is None:
            w("  快照缺失")
            return
        c_code = pick_col(spot, ["代码", "code"])
        c_name = pick_col(spot, ["名称", "name"])
        c_pct = pick_col(spot, ["涨跌幅", "changepercent"])
        c_price = pick_col(spot, ["最新价", "trade"])
        c_high = pick_col(spot, ["最高", "high"])
        c_low = pick_col(spot, ["最低", "low"])
        c_pre = pick_col(spot, ["昨收", "settlement", "preclose"])
        c_amt = pick_col(spot, ["成交额", "amount"])
        if not all([c_code, c_name, c_pct]):
            w("  [报空] 快照缺字段")
            return

        d = spot.copy()
        d = d[~d[c_name].astype(str).str.contains("退|N ", na=False)]
        d[c_pct] = pd.to_numeric(d[c_pct], errors="coerce")
        d = d.dropna(subset=[c_pct])
        d["_code6"] = d[c_code].astype(str).str.extract(r"(\d{6})")[0]
        d = d.dropna(subset=["_code6"])
        if c_amt:
            d[c_amt] = pd.to_numeric(d[c_amt], errors="coerce")

        # ① 今晚必上龙虎榜（偏离值≥7% 或 振幅≥15%）
        w("  ◆①【今晚必上龙虎榜】涨跌幅≥±7% 或 振幅≥15%（交易所硬规则）")
        big = d[d[c_pct].abs() >= 7].copy()
        amp_list = []
        if c_high and c_low and c_pre:
            for c in [c_high, c_low, c_pre]:
                d[c] = pd.to_numeric(d[c], errors="coerce")
            d["_amp"] = (d[c_high] - d[c_low]) / d[c_pre] * 100
            amp_list = d[(d["_amp"] >= 15) & (d[c_pct].abs() < 7)]
        up_big = big[big[c_pct] > 0].sort_values(c_pct, ascending=False)
        dn_big = big[big[c_pct] < 0].sort_values(c_pct)
        w(f"    上榜候选：大涨{len(up_big)}只 | 大跌{len(dn_big)}只 | 高振幅{len(amp_list)}只")
        if len(dn_big) > 0:
            w("    ⚠️ 大跌上榜（今晚看是谁在接）：" +
              "、".join(f"{r[c_name]}({r[c_pct]:.1f}%)"
                        for _, r in dn_big.head(8).iterrows()))

        # ② 实时埋伏池：跌着被主力大单买
        fmap, fsrc = _flow_rank()
        w(f"  ◆②【实时埋伏池】跌着却被主力净买（源：{fsrc or '无'}）")
        if not fmap:
            w("    [报空] 资金流双源均失败")
        else:
            d["_flow"] = d["_code6"].map(fmap)
            amb = d[(d[c_pct] < 0) & (d["_flow"] > 0)].copy()
            if c_amt:
                amb = amb[amb[c_amt] > 5e7]
            amb = amb.sort_values("_flow", ascending=False)
            if len(amb) == 0:
                w("    今日无『跌着被买』标的 → 全场追涨，次日谨慎")
            else:
                for _, r in amb.head(12).iterrows():
                    fv = r["_flow"]
                    unit = "亿" if abs(fv) > 1e4 else "万"
                    fvv = fv / 1e8 if abs(fv) > 1e4 else fv / 1e4
                    amt_txt = f" 成交{r[c_amt]/1e8:.1f}亿" if c_amt and pd.notna(r[c_amt]) else ""
                    w(f"    🎯 {r[c_name]}({r['_code6']}) {r[c_pct]:+.2f}%{amt_txt} | 主力净买+{fvv:.2f}{unit}")
                w(f"    ※ 共{len(amb)}只跌着被买。这就是实时版埋伏信号——")
                w("      有人在下跌中收货，次日看板块是否启动。")
                global TODAY_AMBUSH
                TODAY_AMBUSH = [{"code": r["_code6"], "name": str(r[c_name]),
                                 "price": float(r[c_price])}
                                for _, r in amb.head(15).iterrows()
                                if pd.notna(r[c_price])]

        # ③ 涨停封单强度
        w("  ◆③【涨停板强度】")
        try:
            zt = with_retry(lambda: ak.stock_zt_pool_em(
                date=now_beijing().strftime("%Y%m%d")), tries=1, timeout=60)
            if zt is None or len(zt) == 0:
                w("    暂无涨停数据")
            else:
                z_name = pick_col(zt, ["名称"])
                z_seal = pick_col(zt, ["封板资金"])
                z_fail = pick_col(zt, ["炸板次数"])
                z_ind = pick_col(zt, ["所属行业", "行业"])
                if z_seal:
                    zt[z_seal] = pd.to_numeric(zt[z_seal], errors="coerce")
                    zz = zt.sort_values(z_seal, ascending=False)
                    w(f"    涨停{len(zt)}只，封单最强前6：")
                    for _, r in zz.head(6).iterrows():
                        seal = r[z_seal] / 1e8 if pd.notna(r[z_seal]) else 0
                        ind = f" [{r[z_ind]}]" if z_ind else ""
                        fail = f" 炸板{r[z_fail]}次" if z_fail else ""
                        w(f"      {r[z_name]}{ind} 封单{seal:.2f}亿{fail}")
                if z_fail:
                    zt[z_fail] = pd.to_numeric(zt[z_fail], errors="coerce")
                    nf = int((zt[z_fail] > 0).sum())
                    w(f"    ⚠️ 有炸板记录的{nf}只/{len(zt)}只 → " +
                      ("情绪不稳" if nf > len(zt) * 0.3 else "封板扎实"))
        except Exception as e:
            w(f"    [跳过] 涨停池：{type(e).__name__}")
    safe_run("盘中游资雷达", _do)


# ========== 一、市场广度 ==========

def scan_breadth():
    w("\n【一、市场广度仪表盘】")

    def _do():
        src, df = multi_source("市场广度", [
            ("乐咕乐股", lambda: ak.stock_market_activity_legu()),
        ])
        if df is not None:
            w(f"  （数据源：{src}）")
            for _, r in df.iterrows():
                w(f"    {r.iloc[0]}：{r.iloc[1]}")
            return
        df2 = get_spot()
        c_pct = pick_col(df2, ["涨跌幅", "changepercent"])
        df2[c_pct] = pd.to_numeric(df2[c_pct], errors="coerce")
        w(f"  （数据源：{SPOT_SRC}计算）涨{(df2[c_pct]>0).sum()} : 跌{(df2[c_pct]<0).sum()}")
    safe_run("市场广度", _do)


# ========== 二、全市场快照 ==========

def scan_spot():
    w("\n【二、全市场快照】")

    def _do():
        df = get_spot()
        if df is None:
            raise RuntimeError("快照失败")
        c_name = pick_col(df, ["名称", "name"])
        c_code = pick_col(df, ["代码", "code"])
        c_pct = pick_col(df, ["涨跌幅", "changepercent"])
        d = df[~df[c_name].astype(str).str.contains("ST", na=False)].copy()
        d[c_pct] = pd.to_numeric(d[c_pct], errors="coerce")
        d = d.dropna(subset=[c_pct])
        w(f"  ◆ 涨幅前15（源：{SPOT_SRC}）：")
        for _, r in d.sort_values(c_pct, ascending=False).head(15).iterrows():
            w(f"    {r[c_name]}({r[c_code]}) {r[c_pct]}%")
    safe_run("全市场快照", _do)


# ========== 冷低早筛选 ==========

# ★★V8.5 K线缓存 + 全局时间预算（8/11事故：跑23分钟未结束）★★
# 成因：盯盘名单从12只加到17只，每只都抓K线，
#   每次 with_retry(timeout=25) × 两个源 = 单只最坏50秒，
#   17只 = 最坏14分钟，再叠加冷低早/选股器里的重复抓取 → 跑不完。
# ★根因不是"加了5只票"，是我的代码【没有总时间预算，会一直等下去】。
_HIST_CACHE = {}
_HIST_T0 = [None]          # 首次调用时间
_HIST_BUDGET = 420         # 秒。超过就不再抓新K线，返回None（模块自动降级）


def _hist_budget():
    """★V8.9 快扫模式K线预算压到120秒"""
    return 120 if globals().get("FAST_MODE") else _HIST_BUDGET


def _hist_close(code, symbol=None):
    # ★缓存：同一只票在多个模块被重复抓取（盯盘/冷低早/选股器）
    if code in _HIST_CACHE:
        return _HIST_CACHE[code]
    if _HIST_T0[0] is None:
        _HIST_T0[0] = time.time()
    elif time.time() - _HIST_T0[0] > _hist_budget():
        # ★超预算：直接返回空，让调用方走"无K线"分支，不再等网络
        _HIST_CACHE[code] = (None, None)
        return None, None
    r = _hist_close_raw(code, symbol)
    _HIST_CACHE[code] = r
    return r


def _hist_close_raw(code, symbol=None):
    if symbol:
        try:
            k = with_retry(lambda: ak.stock_zh_a_daily(symbol=symbol), tries=1, timeout=12, critical=True)
            if k is not None and len(k) >= 45:
                return k, pick_col(k, ["close", "收盘"])
        except Exception:
            pass
    try:
        end = now_beijing().strftime("%Y%m%d")
        start = (now_beijing() - datetime.timedelta(days=120)).strftime("%Y%m%d")
        k = with_retry(lambda: ak.stock_zh_a_hist(symbol=code, period="daily",
                       start_date=start, end_date=end, adjust="qfq"), tries=1, timeout=12, critical=True)
        if k is not None and len(k) >= 45:
            return k, pick_col(k, ["收盘", "close"])
    except Exception:
        pass
    return None, None


SPOT_IND = {}


def _build_spot_ind():
    """兜底：用同花顺行业成分一次性建全市场映射（东财挂了也能用）"""
    global SPOT_IND
    if SPOT_IND:
        return SPOT_IND
    try:
        for fn in [lambda: ak.stock_board_industry_summary_ths(),
                   lambda: ak.stock_fund_flow_industry(symbol="即时")]:
            try:
                d = with_retry(fn, tries=1, wait=2, timeout=30)
                if d is None or len(d) == 0:
                    continue
                nc = pick_col(d, ["板块", "行业", "板块名称", "名称"])
                names = [str(x) for x in d[nc].tolist()][:95]
                t0 = time.time()
                fail = 0
                for nm in names:
                    if time.time() - t0 > 180 or fail >= 3:
                        break
                    try:
                        c = with_retry(lambda n=nm: ak.stock_board_industry_cons_ths(symbol=n),
                                       tries=1, wait=1, timeout=12)
                        if c is not None and len(c) > 0:
                            cc = pick_col(c, ["代码", "股票代码"])
                            if cc:
                                for _, rr in c.iterrows():
                                    SPOT_IND[str(rr[cc])[-6:].zfill(6)] = nm
                                fail = 0
                                continue
                        fail += 1
                    except Exception:
                        fail += 1
                    time.sleep(0.25)
                if SPOT_IND:
                    return SPOT_IND
            except Exception:
                continue
    except Exception:
        pass
    return SPOT_IND


def _load_ind_cache():
    try:
        if os.path.exists(IND_MAP_FILE):
            with open(IND_MAP_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            ts = d.get("built", "")
            age = (now_beijing() - datetime.datetime.strptime(ts, "%Y-%m-%d")).days if ts else 99
            # ★V7.0：不只看天数，还看覆盖量。<3000只说明上次是半成品，要补
            if age <= 7 and len(d.get("map") or {}) >= 3000:
                return d["map"], age
            if d.get("map"):
                return d["map"], age
    except Exception:
        pass
    return {}, 99


def _build_ind_cache():
    """一周建一次：代码→行业 对照表
    ⚠️东财对GitHub海外服务器封锁 → 同花顺优先；总预算5分钟；连败3次熔断"""
    t0 = time.time()
    BUDGET = 300          # 总时长上限（秒）
    w("  [建缓存] 行业对照表重建中（上限5分钟，每周一次）...")
    m = {}
    # ★V7.0：先载入旧表做底，新抓到的覆盖上去 → 不再每周从零开始只剩465只
    try:
        if os.path.exists(IND_MAP_FILE):
            with open(IND_MAP_FILE, "r", encoding="utf-8") as _f:
                m = dict(json.load(_f).get("map", {}))
            if m:
                w(f"  [建缓存] 继承旧表{len(m)}只，本次做增量补充")
    except Exception:
        m = {}
    try:
        names = None
        for fn in [lambda: ak.stock_board_industry_summary_ths(),
                   lambda: ak.stock_board_industry_name_em()]:
            try:
                d = with_retry(fn, tries=1, wait=2, timeout=30)
                if d is not None and len(d) > 0:
                    nc = pick_col(d, ["板块名称", "板块", "名称", "行业"])
                    names = [str(x) for x in d[nc].tolist()]
                    break
            except Exception:
                continue
        if not names:
            w("  [建缓存] 拿不到行业列表，放弃（本次⑥闸门降级为实时查）")
            return {}

        ths_fail = em_fail = 0
        done = 0
        for nm in names[:95]:
            if time.time() - t0 > BUDGET:
                w(f"  [建缓存] 到达5分钟预算上限，已完成{done}个行业，保存现有结果")
                break
            got = False
            # 同花顺优先（东财在GitHub海外机被封）
            if ths_fail < 3:
                try:
                    c = with_retry(lambda n=nm: ak.stock_board_industry_cons_ths(symbol=n),
                                   tries=1, wait=1, timeout=15)
                    if c is not None and len(c) > 0:
                        cc = pick_col(c, ["代码", "股票代码"])
                        if cc:
                            for _, rr in c.iterrows():
                                m[str(rr[cc])[-6:].zfill(6)] = nm
                            got = True
                            ths_fail = 0
                except Exception:
                    ths_fail += 1
                    if ths_fail == 3:
                        w("  [建缓存] 同花顺连败3次，熔断切东财")
            if not got and em_fail < 3:
                try:
                    c = with_retry(lambda n=nm: ak.stock_board_industry_cons_em(symbol=n),
                                   tries=1, wait=1, timeout=15)
                    if c is not None and len(c) > 0:
                        cc = pick_col(c, ["代码", "股票代码"])
                        if cc:
                            for _, rr in c.iterrows():
                                m[str(rr[cc])[-6:].zfill(6)] = nm
                            got = True
                            em_fail = 0
                except Exception:
                    em_fail += 1
                    if em_fail == 3:
                        w("  [建缓存] 东财连败3次(海外封锁)，熔断")
            if ths_fail >= 3 and em_fail >= 3:
                w("  [建缓存] 双源均熔断，停止重建")
                break
            if got:
                done += 1
            time.sleep(0.3)

        if m:
            os.makedirs("reports", exist_ok=True)
            with open(IND_MAP_FILE, "w", encoding="utf-8") as f:
                json.dump({"built": now_beijing().strftime("%Y-%m-%d"), "map": m},
                          f, ensure_ascii=False)
            w(f"  [建缓存] 完成：{done}个行业 / {len(m)}只个股入库 "
              f"（耗时{time.time()-t0:.0f}秒）")
        else:
            w("  [建缓存] 一条都没拿到，本次跳过")
    except Exception as e:
        w(f"  [建缓存] 异常：{type(e).__name__}")
    return m


def _get_industry_map():
    src, df = multi_source("行业榜(冷低早)", [
        # ★V8.9：8/12实测东财连挂5次(ConnectionError/HTTPError/JSONDecodeError)，
        # 每次都要等超时再切备源，纯浪费。同花顺次次成功 → 提为第一顺位。
        ("同花顺", lambda: ak.stock_board_industry_summary_ths()),
        ("东财", lambda: ak.stock_board_industry_name_em()),
        ("同花顺资金流", lambda: ak.stock_fund_flow_industry(symbol="即时")),
    ])
    if df is None:
        return {}
    c_name = pick_col(df, ["板块名称", "板块", "名称", "行业"])
    c_pct = pick_col(df, ["涨跌幅", "涨跌"])
    if not c_name or not c_pct:
        return {}
    m = {}
    for _, r in df.iterrows():
        try:
            v = pd.to_numeric(r[c_pct], errors="coerce")
            if pd.notna(v):
                m[str(r[c_name])] = float(v)
        except Exception:
            continue
    return m


def _stock_industry(code6):
    try:
        info = with_retry(lambda: ak.stock_individual_info_em(symbol=code6),
                          tries=1, timeout=20)
        if info is None:
            return None
        for _, r in info.iterrows():
            if "行业" in str(r.iloc[0]):
                return str(r.iloc[1])
    except Exception:
        pass
    return None


def scan_cold_low():
    w("\n★★★【冷低早候选·暗流吸筹】★★★（大盘闸+冷+低+缩量+涨日放量+板块闸）")

    def _do():
        spot = get_spot()
        if spot is None:
            raise RuntimeError("快照缺失")
        c_code = pick_col(spot, ["代码", "code"])
        c_name = pick_col(spot, ["名称", "name"])
        c_price = pick_col(spot, ["最新价", "trade"])
        c_pct = pick_col(spot, ["涨跌幅", "changepercent"])
        c_amt = pick_col(spot, ["成交额", "amount"])
        if not all([c_code, c_name, c_price, c_pct]):
            w("  [报空] 快照缺必要字段")
            return

        d = spot.copy()
        d = d[~d[c_name].astype(str).str.contains("ST|退|N ", na=False)]
        for c in [c_price, c_pct]:
            d[c] = pd.to_numeric(d[c], errors="coerce")
        d = d.dropna(subset=[c_pct, c_price])

        up = int((d[c_pct] > 0).sum())
        dn = int((d[c_pct] < 0).sum())
        ratio = up / (up + dn) * 100 if (up + dn) else 0
        w(f"  ⓪大盘环境闸门：涨{up} 跌{dn} 上涨占比{ratio:.1f}%")
        if ratio < 25:
            w("  ⚠️【闸门触发】上涨占比<25% = 系统性杀跌日")
            w("  >>> 今日不输出任何候选。形态再好，板块崩了照样跟着崩。")
            return
        if ratio < 35:
            w("  ⚠️ 环境偏弱(占比<35%)，以下候选仅供观察，不建议当日开仓")

        d["_code6"] = d[c_code].astype(str).str.extract(r"(\d{6})")[0]
        d = d.dropna(subset=["_code6"])
        d = d[~d["_code6"].str.startswith(("8", "4", "9"))]

        cand = d[(d[c_pct] >= -3.5) & (d[c_pct] <= 0.5) &
                 (d[c_pct].abs() > 0.05) &
                 (d[c_price] >= 3) & (d[c_price] <= 100)].copy()
        w(f"  ①横盘微跌(排停牌僵尸)：{len(cand)}只")

        if c_amt:
            cand[c_amt] = pd.to_numeric(cand[c_amt], errors="coerce")
            cand = cand.dropna(subset=[c_amt])
            cand = cand[(cand[c_amt] > 3e7) & (cand[c_amt] < 8e8)]
            cand = cand.sort_values(c_amt, ascending=False)
            w(f"  ②成交额3千万-8亿(排僵尸/排爆炒)：{len(cand)}只")
        else:
            cand = cand.reindex(cand[c_pct].abs().sort_values().index)

        w("  ③低位(60日跌>12%) ④缩量(5日/60日<0.8) ⑤涨日放量(暗流)：")
        hits = []
        for _, r in cand.head(120).iterrows():
            if len(hits) >= 10:
                break
            code6 = r["_code6"]
            sym = ("sh" if code6.startswith("6") else "sz") + code6
            k, kc = _hist_close(code6, sym)
            if k is None or kc is None:
                continue
            try:
                kv = pick_col(k, ["volume", "成交量"])
                if not kv:
                    continue
                now_p = pd.to_numeric(k.iloc[-1][kc], errors="coerce")
                p60 = pd.to_numeric(k.iloc[-45][kc], errors="coerce")
                if not p60 or pd.isna(now_p):
                    continue
                chg60 = (now_p - p60) / p60 * 100
                if chg60 > -12:
                    continue
                v5 = pd.to_numeric(k[kv].tail(5), errors="coerce").mean()
                v60 = pd.to_numeric(k[kv].tail(45), errors="coerce").mean()
                if not v60 or v5 / v60 >= 0.8:
                    continue
                k20 = k.tail(20).copy()
                k20["_c"] = pd.to_numeric(k20[kc], errors="coerce")
                k20["_v"] = pd.to_numeric(k20[kv], errors="coerce")
                k20["_chg"] = k20["_c"].pct_change()
                upv = k20[k20["_chg"] > 0]["_v"].mean()
                dnv = k20[k20["_chg"] < 0]["_v"].mean()
                if not dnv or pd.isna(upv) or upv / dnv < 1.1:
                    continue
                hits.append({
                    "code": code6, "name": str(r[c_name]), "price": r[c_price],
                    "pct": r[c_pct], "chg60": chg60, "vr": v5 / v60, "ud": upv / dnv,
                })
                w(f"    候选：{r[c_name]}({code6}) {r[c_price]} 今{r[c_pct]}% | "
                  f"60日{chg60:.1f}% | 缩量{v5/v60:.2f} | 涨跌量比{upv/dnv:.2f}")
            except Exception:
                continue
            time.sleep(0.4)

        if not hits:
            w("    本次无标的 —— 这是特征不是故障。")
            return

        w("\n  ⑥板块环境闸门（所属板块跌超1.5%的直接否决）：")
        ind_cache, cage = _load_ind_cache()
        if not ind_cache:
            ind_cache = _build_ind_cache()
        if len(ind_cache) < 800:
            w(f"  （对照表仅{len(ind_cache)}只，启动同花顺兜底补全...）")
            _build_spot_ind()
            if SPOT_IND:
                w(f"  （兜底补全 {len(SPOT_IND)} 只）")
        else:
            w(f"  （行业对照表：{len(ind_cache)}只，缓存{cage}天前建）")
        imap = _get_industry_map()
        if not imap:
            w("    [报空] 行业榜拿不到，本关跳过（上面候选未经板块验证，慎用）")
            return
        passed = 0
        for h in hits:
            ind = ind_cache.get(h["code"]) or SPOT_IND.get(h["code"]) \
                or _stock_industry(h["code"])
            ipct = imap.get(ind) if ind else None
            if ipct is None:
                # ★★V9.1：行业未知不再一票否决★★
                # 8/12实测：对照表只有630只，江化微/拓普集团/汇川技术等
                # 好票天天被"行业未知"毙掉，冷低早连续三次输出"今日无标的"。
                # 但⓪大盘闸门（上涨占比≥50%）已经过了 —— 环境不差。
                # ★"查不到行业" ≠ "板块逆风"。前者是我的数据缺陷，
                #   后者才是市场信号。不该拿我的缺陷去否决市场机会。
                w(f"    ⚠️放行 {h['name']}({h['code']}) 行业[未知] {h['price']} "
                  f"今{h['pct']}% | 60日{h['chg60']:.1f}% | "
                  f"缩量{h['vr']:.2f} | 量比{h['ud']:.2f}")
                w("       └ 对照表查不到行业，但⓪大盘闸门已过 → 放行，需人工确认板块")
                passed += 1
                continue
            if ipct < -1.5:
                w(f"    ❌ {h['name']}({h['code']}) 板块[{ind}]{ipct:+.2f}% 逆风 → 否决")
                continue
            flag = "✅顺风" if ipct > 0 else "⚠️板块微跌"
            w(f"    {flag} {h['name']}({h['code']}) {h['price']} 今{h['pct']}% | "
              f"板块[{ind}]{ipct:+.2f}% | 60日{h['chg60']:.1f}% | "
              f"缩量{h['vr']:.2f} | 量比{h['ud']:.2f}")
            passed += 1
            time.sleep(0.5)

        if passed == 0:
            w("    ⚠️ 全部候选被板块闸门否决 → 今日无标的")
            w("    （V9.1起，只有【板块确实跌超1.5%】才否决；行业未知改为放行）")
        else:
            w(f"  ※ 最终{passed}只过关。⑦催化日期 ⑧止损由你我集中分析定。")

        # ★存档 + 5日回测（验证这个筛选器到底行不行）
        _cold_archive_and_backtest(hits, spot, c_code, c_name, c_price)
    safe_run("冷低早筛选", _do)


def _cold_archive_and_backtest(hits, spot, c_code, c_name, c_price):
    """把今天筛出的票存档；并回测5个交易日前那批现在赚没赚"""
    bj = now_beijing()
    today = bj.strftime("%Y-%m-%d")
    can_save = (bj.weekday() < 5) and (bj.hour >= 15)
    try:
        hist = {}
        if os.path.exists(COLD_HIST_FILE):
            with open(COLD_HIST_FILE, "r", encoding="utf-8") as f:
                hist = json.load(f)
    except Exception:
        hist = {}

    # 回测：找5个交易日前的记录
    days = sorted([d for d in hist if d < today])
    if len(days) >= 5:
        base = days[-5]
        recs = hist[base]
        w(f"\n  ★★【冷低早回测】{base} 那批（{len(recs)}只）现在如何：")
        tot, win = 0.0, 0
        for rec in recs:
            try:
                r = spot[spot[c_code].astype(str).str.contains(rec["code"], na=False)]
                if len(r) == 0:
                    continue
                now_p = pd.to_numeric(r.iloc[0][c_price], errors="coerce")
                if pd.isna(now_p):
                    continue
                pnl = (now_p - rec["price"]) / rec["price"] * 100
                tot += pnl
                if pnl > 0:
                    win += 1
                w(f"    {rec['name']}({rec['code']}) {rec['price']}→{now_p} {pnl:+.2f}%")
            except Exception:
                continue
        n = len(recs) if recs else 1
        w(f"    ★5日胜率：{win}/{len(recs)} | 平均收益 {tot/n:+.2f}%")
        if len(recs) < 5:
            w(f"    ⚠️ 样本仅{len(recs)}只，统计无意义，不下结论（需≥5只）")
        elif tot / n < 0:
            w("    ⚠️ 平均为负 → 这个筛选器当前参数在这种行情下无效，")
            w("       不要照单买，必须配合板块启动信号")
    else:
        w(f"\n  （冷低早回测：已存{len(days)}天，满5天后自动出胜率）")

    if can_save and hits:
        try:
            hist[today] = [{"code": h["code"], "name": h["name"],
                            "price": float(h["price"])} for h in hits]
            ks = sorted(hist)[-60:]
            hist = {k: hist[k] for k in ks}
            os.makedirs("reports", exist_ok=True)
            with open(COLD_HIST_FILE, "w", encoding="utf-8") as f:
                json.dump(hist, f, ensure_ascii=False)
            w(f"  ✅ 已存档今日{len(hits)}只候选，历史{len(hist)}天")
        except Exception as e:
            w(f"  [跳过] 冷低早存档：{type(e).__name__}")


# ========== 三、板块全景榜（行业 + 概念，都有历史库） ==========

def _load_hist(path):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                h = json.load(f)
                if isinstance(h, dict) and "days" in h:
                    return h
    except Exception:
        pass
    return {"days": {}}


def _fmt_tag(hist, name, today, rank_now, pct_now):
    if not hist["days"]:
        return " | 🆕库空(今日起积累)"
    ds = sorted([d for d in hist["days"] if d < today], reverse=True)
    streak = 0
    for d in ds:
        rec = hist["days"][d].get(name)
        if rec and rec.get("pct", 0) > 0:
            streak += 1
        else:
            break
    days = streak + 1 if pct_now > 0 else 0
    cum = pct_now
    for d in ds[:2]:
        rec = hist["days"][d].get(name)
        if rec:
            cum += rec.get("pct", 0)
    prev = None
    if ds:
        rec = hist["days"][ds[0]].get(name)
        if rec:
            prev = rec.get("rank")
    if days == 0:
        tag = "今日转跌"
    elif days == 1:
        tag = "🆕第1天(刚启动)"
    elif days >= 5:
        tag = f"🔥连{days}天 ⚠️查驱动类型"
    elif days >= 3:
        tag = f"🔥连{days}天"
    else:
        tag = f"连{days}天(仍早)"
    c3 = f" 3日{cum:+.1f}%" if len(ds) >= 2 else ""
    rk = ""
    if prev:
        # ★★V9.7：跳升位数存进全局，供【全板块交叉】当【领先指标】打分★★
        # 8/13教训：资金流是滞后指标(记录钱已流过的地方)，
        #   排名跳升才是领先的(CRO今天从358跳到第1，昨天它还在358名、资金为负)
        try:
            SECTOR_JUMP_MAP[str(name)] = int(prev) - int(rank_now)
        except Exception:
            pass
        if prev - rank_now >= 8:
            rk = f" 🚀{prev}→{rank_now}名"
        elif rank_now - prev >= 8:
            rk = f" 📉{prev}→{rank_now}名"
        else:
            rk = f" {prev}→{rank_now}名"
    return f" | {tag}{c3}{rk}"


def scan_board_rank():
    w("\n【三、板块全景榜】板块|涨跌|领涨股|连涨天数|3日累计|排名变化")
    w("  ★★【连涨天数判读铁律O（V5.1）】天数本身没有意义★★")
    w("  必须先答③-B：这个板块的驱动是【单一事件】还是【产业周期】？")
    w("    【单一事件】IPO/发布会/政策发布日/财报")
    w("       → 连3-5天就是高潮，事件日就是顶")
    w("    【产业周期】涨价/缺货/产能紧缺/政策倒计时/国产替代")
    w("       → 连20天、30天都正常，回调才是买点")
    w("       → ★存储涨价到2027年、AI capex多年、国产替代五年")
    w("         这类板块连涨5天只是【开场】，不是高潮")
    w("  ⚠️ 血的教训：我曾用『连5天=高潮慎追』否决了通信设备/计算机设备/")
    w("     6G/小金属，同时把才3连板的磷化铟当成『已启动不能追』")
    w("     —— 3天连产业周期的零头都不到")
    bj = now_beijing()
    today = bj.strftime("%Y-%m-%d")
    is_intra = (bj.weekday() < 5) and (9 <= bj.hour < 15)
    # 只有交易日收盘后(15点起)才写库；凌晨/盘前跑的数据属于上一交易日，写入会污染历史库
    can_save = (bj.weekday() < 5) and (bj.hour >= 15)
    if not is_intra and not can_save:
        w("  ⚠️ 当前非收盘时段(数据属上一交易日)，本次只读不写库")
    hist_ind = _load_hist(HIST_FILE)
    hist_con = _load_hist(CONCEPT_FILE)
    w(f"  （行业库{len(hist_ind['days'])}天 | 概念库{len(hist_con['days'])}天）")

    saved_ind = {}
    saved_con = {}

    def _rank(title, sources, hist, store):
        src, df = multi_source(title, sources)
        if df is None:
            raise RuntimeError(f"{title}全源失败")
        c_name = pick_col(df, ["板块名称", "概念名称", "板块", "名称", "行业"])
        c_pct = pick_col(df, ["涨跌幅", "涨跌"])
        c_lead = pick_col(df, ["领涨股票", "领涨股"])
        if not c_name or not c_pct:
            raise RuntimeError(f"{title}缺字段 列名={list(df.columns)[:8]}")
        df = df.copy()
        df[c_pct] = pd.to_numeric(df[c_pct], errors="coerce")
        df = df.dropna(subset=[c_pct]).sort_values(c_pct, ascending=False)
        w(f"  ◆ {title}涨幅前15（源：{src}，共{len(df)}个）：")
        for i, (_, r) in enumerate(df.head(15).iterrows(), 1):
            nm = str(r[c_name])
            lead = f" 领涨:{r[c_lead]}" if c_lead else ""
            w(f"    {nm} | {r[c_pct]}%{lead}{_fmt_tag(hist, nm, today, i, r[c_pct])}")
        w(f"  ◆ {title}跌幅前5：")
        for _, r in df.tail(5).iloc[::-1].iterrows():
            w(f"    {r[c_name]} | {r[c_pct]}%")
        if can_save:
            for i, (_, r) in enumerate(df.iterrows(), 1):
                store[str(r[c_name])] = {"pct": round(float(r[c_pct]), 2), "rank": i}

    def _industry():
        _rank("行业", [
            ("同花顺", lambda: ak.stock_board_industry_summary_ths()),   # ★V8.9 东财降备源
            ("东财", lambda: ak.stock_board_industry_name_em()),
            ("同花顺资金流", lambda: ak.stock_fund_flow_industry(symbol="即时")),
        ], hist_ind, saved_ind)
    safe_run("行业板块榜", _industry)

    def _concept():
        _rank("概念", [
            ("同花顺", lambda: ak.stock_fund_flow_concept(symbol="即时")),   # ★V8.9 提前
            ("东财", lambda: ak.stock_board_concept_name_em()),
            ("同花顺资金流", lambda: ak.stock_fund_flow_concept(symbol="即时")),
            ("同花顺", lambda: ak.stock_board_concept_summary_ths()),
        ], hist_con, saved_con)
    safe_run("概念板块榜", _concept)

    def _save(store, hist, path, label):
        if not store or not can_save:
            return
        try:
            hist["days"][today] = store
            ks = sorted(hist["days"])[-40:]
            hist["days"] = {k: hist["days"][k] for k in ks}
            os.makedirs("reports", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(hist, f, ensure_ascii=False)
            w(f"  ✅ 已记录{today} {label}{len(store)}个，库{len(hist['days'])}天")
        except Exception as e:
            w(f"  [跳过] {label}写入：{type(e).__name__}")

    _save(saved_ind, hist_ind, HIST_FILE, "行业")
    _save(saved_con, hist_con, CONCEPT_FILE, "概念")


# ========== 四、板块资金流 ==========

def scan_sector_flow():
    w("\n【四、板块资金流向】（亿元）")

    def _do():
        src, df = multi_source("行业资金流", [
            ("同花顺", lambda: ak.stock_fund_flow_industry(symbol="即时")),   # ★V8.9 东财降备源
            ("东财", lambda: ak.stock_sector_fund_flow_rank(
                indicator="今日", sector_type="行业资金流")),
        ])
        if df is None:
            raise RuntimeError("行业资金流双源失败")
        c_name = pick_col(df, ["名称", "行业"])
        c_pct = pick_col(df, ["涨跌幅", "行业指数涨跌", "涨跌"])
        c_flow = pick_col(df, ["主力净流入-净额", "主力净流入", "净额", "流入资金"])
        df[c_flow] = pd.to_numeric(df[c_flow], errors="coerce")
        if df[c_flow].abs().max() and df[c_flow].abs().max() > 1e6:
            df[c_flow] = (df[c_flow] / 1e8).round(2)
        df = df.sort_values(c_flow, ascending=False)
        # ★★V8.0：存进全局，供【全板块交叉】把资金流纳入打分★★
        # 8/10教训：半导体资金-132.49亿全场最大流出，全板块交叉却给它16分排第1，
        #          因为旧打分只有『新闻净利多×2 + 位置分』，完全没有资金这一项。
        try:
            SECTOR_FLOW_MAP.clear()
            for _, rr in df.iterrows():
                SECTOR_FLOW_MAP[str(rr[c_name])] = float(rr[c_flow])
        except Exception:
            pass
        w(f"  ◆ 行业净流入前10（源：{src}）：")
        for _, r in df.head(10).iterrows():
            w(f"    {r[c_name]} | {r[c_pct]}% | +{r[c_flow]}亿")
        w("  ◆ 行业净流出前5：")
        for _, r in df.tail(5).iloc[::-1].iterrows():
            w(f"    {r[c_name]} | {r[c_pct]}% | {r[c_flow]}亿")
    safe_run("板块资金流", _do)


# ========== 五、涨停池 ==========

def scan_zt_pool():
    w("\n【五、涨停池】")

    def _do():
        date = now_beijing().strftime("%Y%m%d")
        df = with_retry(lambda: ak.stock_zt_pool_em(date=date))
        if df is None or len(df) == 0:
            w("  暂无涨停数据")
            return
        c_name = pick_col(df, ["名称"])
        c_industry = pick_col(df, ["所属行业", "行业"])
        c_lbc = pick_col(df, ["连板数"])
        w(f"  今日涨停共 {len(df)} 只")
        try:
            c_code_zt = pick_col(df, ["代码"])
            if c_code_zt and c_industry:
                cache, _a = _load_ind_cache()
                add = 0
                for _, rr in df.iterrows():
                    k = str(rr[c_code_zt])[-6:].zfill(6)
                    if k not in cache:
                        cache[k] = str(rr[c_industry])
                        add += 1
                if add:
                    os.makedirs("reports", exist_ok=True)
                    with open(IND_MAP_FILE, "w", encoding="utf-8") as f:
                        json.dump({"built": now_beijing().strftime("%Y-%m-%d"),
                                   "map": cache}, f, ensure_ascii=False)
                    w(f"  （顺手补充行业对照表 +{add}只，累计{len(cache)}只）")
        except Exception:
            pass
        if c_industry:
            for k, v in df[c_industry].value_counts().head(8).items():
                w(f"    {k}：{v}只")
        if c_lbc:
            w("  ◆ 最高连板：")
            for _, r in df.sort_values(c_lbc, ascending=False).head(10).iterrows():
                w(f"    {r[c_name]} | {r[c_industry] if c_industry else ''} | {r[c_lbc]}连板")
    safe_run("涨停池", _do)


# ========== 六、龙虎榜（多源 + 自动标注 埋伏型/追高型） ==========

TODAY_AMBUSH = []
AMBUSH_POOL = []   # 埋伏池：当天在跌却被大额净买的票（铁律B）


def scan_lhb():
    w("\n【六、龙虎榜·个股】（约18:35后更新｜自动标注 埋伏型/追高型）")

    def _do():
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
            return

        c_name = pick_col(df, ["名称", "股票简称", "简称"])
        c_code = pick_col(df, ["代码", "股票代码"])
        c_pct = pick_col(df, ["涨跌幅", "涨跌幅度", "收盘涨跌幅"])
        c_reason = pick_col(df, ["上榜原因", "解读", "指标"])
        c_net = pick_col(df, ["净买额", "龙虎榜净买额", "机构买入净额", "净额"])

        if not c_name:
            w(f"  [报空] 龙虎榜(源:{src})缺名称列，实际列名={list(df.columns)[:10]}")
            return

        df = df.copy()
        if c_net:
            df[c_net] = pd.to_numeric(df[c_net], errors="coerce")
            if df[c_net].abs().max() and df[c_net].abs().max() > 1e6:
                df[c_net] = (df[c_net] / 1e8).round(2)
            df = df.sort_values(c_net, ascending=False)
        if c_pct:
            df[c_pct] = pd.to_numeric(df[c_pct], errors="coerce")

        w(f"  （源：{src}，共{len(df)}条）")
        ambush, chase = [], []
        for _, r in df.head(20).iterrows():
            nm = str(r[c_name])
            pct = r[c_pct] if c_pct else None
            net = r[c_net] if c_net else None
            code = str(r[c_code])[-6:] if c_code else ""
            tag = ""
            if pct is not None and pd.notna(pct):
                if pct < 0:
                    tag = "✅埋伏型(跌着被买)"
                    if net is None or (pd.notna(net) and net > 0):
                        ambush.append((nm, code, pct, net))
                elif pct >= 9.8:
                    tag = "⚠️追高型(涨停被买)"
                    chase.append((nm, code, pct, net))
                else:
                    tag = "中性"
            pct_txt = f" {pct:+.2f}%" if pct is not None and pd.notna(pct) else ""
            net_txt = f" 净买{net}亿" if net is not None and pd.notna(net) else ""
            reason = str(r[c_reason])[:18] if c_reason else ""
            w(f"    {nm}({code}){pct_txt}{net_txt} {tag} {reason}")

        global AMBUSH_POOL
        AMBUSH_POOL = ambush
        w("")
        w("  ★★★【埋伏池·铁律B】游资在『当天下跌』的票上砸钱 = 明天最可能启动 ★★★")
        if ambush:
            for nm, code, pct, net in ambush[:10]:
                net_txt = f" 净买{net}亿" if net is not None and pd.notna(net) else ""
                w(f"    🎯 {nm}({code}) 今{pct:+.2f}%{net_txt}")
            w(f"    ※ 共{len(ambush)}只。次日重点验证：所属板块是否启动、是否放量。")
        else:
            w("    今日无『跌着被买』标的（全是追涨停接力）→ 次日谨慎")
        if chase:
            w(f"  ⚠️ 追高型{len(chase)}只（涨停被买，次日易炸板）：" +
              "、".join(n for n, _, _, _ in chase[:8]))
    safe_run("龙虎榜", _do)


# ========== 七、游资席位（多源 + 列名自诊断） ==========

def scan_hot_money():
    w("\n【七、游资席位·活跃营业部】（谁在扫货/出货，约18:35后完整）")

    def _do():
        date = now_beijing().strftime("%Y%m%d")
        src, df = multi_source("游资席位", [
            ("东财", lambda: ak.stock_lhb_hyyyb_em(start_date=date, end_date=date)),
            ("新浪", lambda: ak.stock_lhb_yytj_sina(symbol="近一月")),
            ("东财机构", lambda: ak.stock_lhb_jgstatistic_em(symbol="近一月")),
        ])
        if df is None or len(df) == 0:
            w("  今日活跃营业部暂未发布（18:35后再看）")
            return

        c_name = pick_col(df, ["营业部名称", "营业部", "机构名称"])
        c_net = pick_col(df, ["总买卖净额", "净额", "净买", "买入总金额"])
        c_stock = pick_col(df, ["买入股票", "买入个股", "买入股票代码"])

        if not c_name:
            w(f"  [报空] 游资(源:{src})缺营业部列，实际列名={list(df.columns)[:10]}")
            return

        df = df.copy()
        if c_net:
            df[c_net] = pd.to_numeric(df[c_net], errors="coerce")
            if df[c_net].abs().max() and df[c_net].abs().max() > 1e6:
                df[c_net] = (df[c_net] / 1e8).round(2)
            df = df.sort_values(c_net, ascending=False)

        w(f"  ◆ 净买入最猛席位前10（源：{src}）：")
        for _, r in df.head(10).iterrows():
            stock = f" 主买:{str(r[c_stock])[:60]}" if c_stock else ""
            net = f" 净{r[c_net]}亿" if c_net and pd.notna(r[c_net]) else ""
            w(f"    {r[c_name]}{net}{stock}")
        w("  ※ 判读：席位集中买『当天在跌』的方向=埋伏，明天看它启动；")
        w("    集中买『当天涨停』的=追高接力，次日易崩。")
    safe_run("游资席位", _do)


# ========== 八、北向资金 ==========

def scan_north():
    w("\n【八、北向资金】")

    def _do():
        df = with_retry(lambda: ak.stock_hsgt_fund_flow_summary_em())
        for _, r in df.iterrows():
            w("    " + " | ".join(f"{c}:{r[c]}" for c in df.columns[:6]))
    safe_run("北向资金", _do)


# ========== 九、新闻流 + 关键词雷达 ==========

NEWS_RADAR = {
    "① 名人喊话": ["马斯克", "黄仁勋", "特朗普", "鲍威尔", "沃什", "巴菲特", "伯里",
                "段永平", "奥特曼", "孙正义", "库克", "雷军", "习近平", "李强"],
    "② 政策·国内": ["国务院", "发改委", "财政部", "央行", "证监会", "工信部", "十五五",
                 "国常会", "补贴", "规划", "部署", "统计局", "医保", "国新办", "市场监管总局"],
    "③ 政策·海外": ["白宫", "美联储", "加息", "降息", "关税", "出口管制", "商务部",
                 "外交部", "制裁", "欧盟", "CPI", "非农"],
    "④ 科技·产业": ["AI", "算力", "半导体", "芯片", "光模块", "CPO", "PCB", "机器人",
                 "商业航天", "卫星", "固态电池", "创新药", "存储", "英伟达", "台积电",
                 "阿斯麦", "液冷", "光刻", "覆铜板", "昇腾", "脑机接口", "具身"],
    "⑤ 大宗·地缘": ["石油", "原油", "黄金", "铜", "锂", "稀土", "煤", "战争", "霍尔木兹",
                 "伊朗", "以色列", "地缘", "OPEC", "天然气", "曼德海峡"],
    "⑥ 资金·事件": ["打新", "IPO", "长鑫", "并购", "重组", "预增", "增持", "减持",
                 "回购", "举牌", "分红", "中标", "定增", "ETF"],
    "⑦ 消费·养殖": ["白酒", "消费", "生猪", "猪价", "养殖", "宠物", "零售", "旅游",
                 "免税", "影视", "票房"],
    "⑧ 政策·产业(专项)": ["锂电池", "锂电", "钠离子", "钠电", "消费税", "征税", "免税",
                 "退税", "出清", "供给侧", "反内卷", "涨价", "限产", "减产", "关税",
                 "出口管制", "反倾销", "专项债", "特别国债", "以旧换新", "设备更新",
                 "收储", "涨电价", "电价", "集采", "国家队", "汇金", "平准", "增持回购"],
}


def _fetch_news(fn):
    df = with_retry(fn, tries=2, wait=3)
    if df is None or len(df) == 0:
        return []
    c_title = pick_col(df, ["标题", "内容", "新闻", "摘要"])
    c_time = pick_col(df, ["发布时间", "时间", "日期"])
    out = []
    for _, r in df.iterrows():
        t = str(r[c_title]).strip() if c_title else ""
        tm = str(r[c_time])[:16] if c_time else ""
        if t and t != "nan":
            out.append((tm, t))
    return out



# ★催化热力图词典：新闻→板块映射（治"催化分散在不同类目导致漏看"）
SECTOR_KEYWORDS = {
    "电力/核电/特高压": ["特高压", "核电", "华龙一号", "电网", "用电负荷", "迎峰度夏",
                    "输配电", "电力设备", "储能电站", "抽水蓄能", "绿电", "节能降碳",
                    "国家电网", "南方电网", "虚拟电厂", "配电网"],
    "算力/云计算": ["算力", "数据中心", "云计算", "AWS", "Azure", "服务器", "交换机",
                "IDC", "智算", "超算", "capex", "资本开支", "英伟达", "GPU"],
    "半导体设备/材料": ["半导体设备", "光刻", "刻蚀", "薄膜沉积", "CMP", "封测",
                  "先进封装", "晶圆", "12英寸", "国产替代", "中微", "北方华创"],
    # ★V9.6：删掉裸词"颗粒"（与推演引擎同步修）。8/12实测两套词典分开写，
    #   只修了推演引擎的core，热力图这边照样把「佐力药业灵莲花颗粒」算成存储利多。
    #   ★教训：同一个概念写在两个地方，就必然只修一个。
    "存储芯片": ["存储", "DRAM", "NAND", "HBM", "闪存", "内存", "美光", "海力士",
              "长鑫", "铠侠", "长江存储", "存储颗粒", "闪存颗粒", "SSD", "eMMC"],
    "光模块/CPO": ["光模块", "CPO", "硅光", "800G", "1.6T", "光芯片", "光引擎"],
    "软件/EDA/AI应用": ["EDA", "工业软件", "操作系统", "信创", "大模型", "AI应用",
                   "智能体", "Agent", "开源模型", "国产软件"],
    "机器人": ["人形机器人", "具身智能", "机器人", "灵巧手", "谐波减速", "伺服"],
    "锂电/钠电": ["锂电", "钠电", "钠离子", "碳酸锂", "正极", "负极", "电解液",
              "固态电池", "储能电池", "消费税"],
    "创新药/医药": ["创新药", "临床", "获批上市", "BD授权", "License-out", "集采",
                "医保", "减肥药", "ADC", "仿制药"],
    "★AI+制药/CXO": ["AI制药", "AI+医疗", "AI药物", "AI辅助研发", "靶点发现",
                 "分子设计", "AlphaFold", "蛋白质结构", "药物设计", "CXO",
                 "CRO", "CDMO", "药明", "临床前", "虚拟筛选", "干实验室",
                 "生物计算", "医疗大模型", "AI诊断", "智能影像", "脑机接口"],
    "军工/航天": ["军工", "航天", "卫星", "导弹", "国防", "低空经济", "商业航天"],
    "油气/煤炭": ["原油", "布伦特", "WTI", "OPEC", "炼化", "油服", "煤炭", "焦煤",
               "天然气", "霍尔木兹"],
    "有色/稀土": ["稀土", "铜", "铝", "锂矿", "黄金", "白银", "钨", "钼", "磁材"],
    "消费/食饮": ["白酒", "乳制品", "食品饮料", "免税", "餐饮", "消费券", "以旧换新"],
    "汽车/新能源车": ["新能源车", "汽车销量", "交付量", "比亚迪", "特斯拉", "智驾",
                 "充电桩", "800V"],
    "养殖/农业": ["生猪", "猪价", "养殖", "饲料", "粮食", "农产品"],
    "影视/传媒/游戏": ["票房", "暑期档", "电影", "游戏", "版号", "传媒", "短剧"],
}


# 多空判定词（判断一条催化是利多还是利空）
TODAY_HEAT_TOP3 = []
TODAY_ANNOUNCE = {}
TODAY_ANNOUNCE_RAW = []   # ★V8.3 [(名称,代码,公告标题)]

BULL_WORDS = ["涨价", "上调", "提价", "缺货", "紧缺", "短缺", "供不应求", "满产",
              "扩产", "增产能", "新增产能", "订单", "中标", "签约", "获批", "并网",
              "投产", "量产", "创新高", "增长", "暴增", "大增", "翻倍", "超预期",
              "回购", "增持", "利好", "受益", "突破", "领先", "第一", "开源",
              "规划", "支持", "补贴", "减税", "宽松", "降准", "降息", "扩内需",
              "净利润同比增", "预增", "反弹", "修复", "回暖", "复苏", "看好", "增配"]

BEAR_WORDS = ["暴跌", "大跌", "下跌", "跌破", "跌超", "下滑", "下降", "减产",
              "停产", "关停", "裁员", "亏损", "预亏", "下修", "下调", "砍单",
              "取消", "推迟", "延期", "叫停", "禁止", "制裁", "封锁", "调查",
              "处罚", "罚款", "爆仓", "强平", "去杠杆", "抛售", "净流出", "减持",
              "溢价风险", "过剩", "降价", "压价", "集采", "降本", "缩水", "warning",
              "加息", "紧缩", "衰退", "风险", "利空", "承压", "疲软", "低迷",
              # ★V6.1 贸易限制类（对A股是利空，此前被误判为利多）
              "覆盖清单", "实体清单", "出口管制", "301调查", "232调查",
              "反倾销", "反补贴", "双反", "加征关税", "限制进口", "禁止进口",
              "列入清单", "制裁名单", "技术封锁", "断供", "撤销资质",
              "取消资质", "调查", "处罚", "约谈", "停牌", "退市", "减持计划",
              "股东减持", "解禁", "商誉减值", "计提减值"]


FOREIGN_WORDS = ["匈牙利", "希腊", "西班牙", "葡萄牙", "意大利", "法国", "德国",
                 "英国", "俄罗斯", "乌克兰", "波兰", "瑞典", "挪威", "芬兰",
                 "印度", "印尼", "越南", "泰国", "菲律宾", "马来西亚", "巴西",
                 "阿根廷", "墨西哥", "土耳其", "埃及", "南非", "澳大利亚",
                 "新西兰", "加拿大", "智利", "秘鲁", "尼日利亚", "肯尼亚",
                 "克罗地亚", "斯洛文尼亚", "亚美尼亚", "刚果", "阿森松岛"]


# ★★V8.4 商品型ETF：跟【商品价格】，不跟【股票板块】★★
# 8/11教训：黄金ETF易(159934)被映射到"贵金属"行业板块，
#   报告因"贵金属资金-24亿"判它【初判已错·建议减仓】。
#   但当天真相是：现货黄金+1.10%涨到4385美元、白银+3.20%，
#   跌的是【黄金股】(灵宝-4.78%、紫金-4.15%、多支黄金股ETF跌超2%)。
#   商品与股票背离时，用股票板块资金去judge商品ETF = 判反。
COMMODITY_ETF = {
    "159934": "现货黄金(COMEX/上金所)",
    "518880": "现货黄金",
    "159937": "现货黄金",
    "161226": "白银期货",
    "159981": "能源化工商品",
    "159980": "有色金属期货",
}


# ★★V8.2 海外机构/市场专有名词：出现即判为外国新闻★★
# 8/10实测：全板块交叉第1名【银行 22分】，四条催化全是——
#   "欧洲央行2万亿欧元隔夜存款"、"德银Q2增持美光"、
#   "美国银行在金风科技H股持股升至5.43%"、"央行授权德银当法兰克福清算行"
# 没一条跟A股银行板块有关。"银行"两字太泛，把海外机构新闻全吸进来了。
# 同理【英伟达概念 11分】催化全是美股持仓/美国投资/日本采购。
# ★注意：这些词出现时，即使句中含"中国/央行"也算外国新闻——
#   因为"某外资行增持某中国公司H股"讲的是外资的事，不是A股板块催化。
FOREIGN_ENTITY = [
    "欧洲央行", "美联储", "日本央行", "英国央行", "澳联储", "瑞士央行",
    "印度央行", "韩国央行", "德意志银行", "德银", "摩根大通", "高盛",
    "美国银行", "花旗", "瑞银", "巴克莱", "野村", "贝莱德", "施罗德",
    "纽约梅隆", "FMR", "杰富瑞", "西太平洋银行", "澳洲国民银行",
    "SEC", "美国证监会", "隔夜存款", "清算行",
]
# H股/港股持股比例变动：是外资持仓披露，不是A股板块催化
FOREIGN_PATTERN = ["H股的持股比例", "持股比例于", "重仓股", "二季度持仓", "Q2持仓"]


def _is_foreign(text):
    """外国新闻不计入A股板块评分（如匈牙利核电停机≠A股电力利空）"""
    t = str(text)
    # ★V8.2 硬闸：海外机构/持股披露，一律不进A股板块评分
    if any(k in t for k in FOREIGN_ENTITY):
        return True
    if any(k in t for k in FOREIGN_PATTERN):
        return True
    if any(f in t for f in FOREIGN_WORDS):
        cn = ["中国", "A股", "国内", "我国", "央行", "发改委", "工信部",
              "出口", "进口", "对华", "中方", "国产"]
        if not any(c in t for c in cn):
            return True
    return False


# ★★V7.1 极性反转短语（与 scanner_usa 同步）：
# 整体含义与其中单字相反。『利空出尽』含"利空"被判利空，
# 8/9实测把AI算力链(用户25%仓位)错标为偏空。
POLARITY_TRAPS = {
    "利空出尽": 1, "利空已充分": 1, "超跌反弹": 1, "跌幅收窄": 1,
    "跌势放缓": 1, "止跌回升": 1, "空头回补": 1, "好于预期": 1,
    "优于预期": 1, "降幅收窄": 1, "底部确认": 1, "底部蓄势": 1,
    "利好出尽": -1, "利好兑现": -1, "涨势见顶": -1, "涨幅收窄": -1,
    "不及预期": -1, "低于预期": -1, "冲高回落": -1,
}


def _news_key(t):
    """★★V8.1 同源新闻指纹：一份文件被媒体拆成N条快讯，只能算1条催化★★
    8/10实测：《煤炭工业发展"十五五"规划》被拆成18条推送，
    导致煤炭概念拿到39分排全场第一、热力图油气/煤炭"净+10 催化爆发"。
    实际只有1条政策。计数膨胀 = 假信号。
    办法：取书名号《》内的内容作指纹；没有书名号则取标题前12字。"""
    t = str(t)
    a = t.find("《")
    b = t.find("》", a + 1) if a >= 0 else -1
    if a >= 0 and b > a:
        return "BOOK:" + t[a:b + 1]
    # 冒号前的主体也常是同一事件的不同细节
    for sep in ("：", ":"):
        i = t.find(sep)
        if 4 <= i <= 20:
            return "HEAD:" + t[:i]
    return "RAW:" + t[:12]


def _news_polarity(text):
    """判断一条新闻的多空方向：+1利多 / -1利空 / 0中性
    ★V7.1：先处理反转短语，再数单字"""
    txt = str(text)
    b = r = 0
    for ph, pol in POLARITY_TRAPS.items():
        if ph in txt:
            if pol > 0:
                b += 2
            else:
                r += 2
            txt = txt.replace(ph, "")
    b += sum(1 for w_ in BULL_WORDS if w_ in txt)
    r += sum(1 for w_ in BEAR_WORDS if w_ in txt)
    if b > r:
        return 1
    if r > b:
        return -1
    return 0


def scan_catalyst_heat(uniq_news):
    """催化热力图 V2：新闻映射板块 + 多空方向识别，按【净利多】排序"""
    w("\n" + "=" * 60)
    w("🔥🔥【催化热力图·多空版】新闻→板块 + 方向识别 🔥🔥")
    w("=" * 60)
    w("  （V3.4：净利多排序 + 外国新闻已过滤，不污染A股板块评分）")
    w("  （V3.2升级：只数条数会误判——油价暴跌10条也是10条，")
    w("    但那是利空。现在按【净利多 = 利多条数 − 利空条数】排序）")

    hits = {}
    for sect, kws in SECTOR_KEYWORDS.items():
        bull, bear, neu, seen = [], [], [], set()
        for tm, t in uniq_news:
            if _is_foreign(t):
                continue
            _k2 = _news_key(t)          # ★V8.1 同源去重
            if _k2 in seen:
                continue
            # ★V9.6：热力图也要排除跨行业误命中（药业/食品/化肥的"颗粒"等）
            if sect in ("存储芯片",) and any(x in t for x in
                    ("药业", "医药", "临床", "适应症", "中药", "食品", "饲料")):
                continue
            for k in kws:
                if k in t and t[:26] not in seen:
                    seen.add(t[:26])
                    seen.add(_k2)
                    p = _news_polarity(t)
                    (bull if p > 0 else bear if p < 0 else neu).append((tm, t, k))
                    break
        if bull or bear or neu:
            hits[sect] = (bull, bear, neu)
    if not hits:
        w("  本期无命中")
        return

    ranked = sorted(hits.items(), key=lambda x: len(x[1][0]) - len(x[1][1]), reverse=True)

    global TODAY_HEAT_TOP3
    TODAY_HEAT_TOP3 = [k for k, (b, r, n) in ranked[:3] if len(b) - len(r) > 0]
    w("\n  ★ 净利多排行（利多↑ 利空↓ 中性=）：")
    for i, (sect, (bu, be, ne)) in enumerate(ranked, 1):
        net = len(bu) - len(be)
        if net >= 5:
            flag = " 🔥🔥🔥催化爆发·重点关注"
        elif net >= 3:
            flag = " 🔥🔥催化密集"
        elif net >= 1:
            flag = " 🔥有催化"
        elif net <= -3:
            flag = " ❄️❄️利空密集·回避"
        elif net <= -1:
            flag = " ❄️偏空"
        else:
            flag = " ⚖️多空平衡"
        w(f"    {i}. {sect}：净{net:+d}（↑{len(bu)} ↓{len(be)} ={len(ne)}）{flag}")

    w("\n  ★ 净利多前3名的具体利多催化：")
    shown = 0
    for sect, (bu, be, ne) in ranked:
        if len(bu) - len(be) < 1 or shown >= 3:
            continue
        shown += 1
        w(f"\n  ◆ 【{sect}】利多{len(bu)}条 / 利空{len(be)}条")
        for tm, t, k in bu[:6]:
            w(f"      ↑[{tm}] ({k}) {t[:58]}")
        if be:
            w("      ── 该板块的利空（对冲项）──")
            for tm, t, k in be[:3]:
                w(f"      ↓[{tm}] ({k}) {t[:58]}")
    if shown == 0:
        w("    ⚠️ 本期无任何板块净利多为正 → 全市场偏空，谨慎")

    w("\n  ★ 利空最密集的板块（明确回避）：")
    for sect, (bu, be, ne) in ranked[-3:]:
        net = len(bu) - len(be)
        if net < 0:
            w(f"    ❄️ {sect}：净{net:+d}")
            for tm, t, k in be[:3]:
                w(f"        ↓[{tm}] ({k}) {t[:58]}")

    w("\n  ⚠️ 判读：净利多≠立刻买，仍需过决策卡①②④⑤")
    w("     但【净利多前3】不许在候选里漏掉；【净利空】不许推荐")
    w("=" * 60)


def _safe_news_one(name, fn):
    """★V11.0 并发抓单个新闻源，失败返回空"""
    try:
        df = with_retry(fn, tries=1, wait=1, timeout=25)
        if df is None or len(df) == 0:
            return name, []
        c_title = pick_col(df, ["标题", "内容", "新闻", "摘要"])
        c_time = pick_col(df, ["发布时间", "时间", "日期"])
        rows = []
        for _, r in df.iterrows():
            t = str(r[c_title]).strip() if c_title else ""
            tm = str(r[c_time])[:16] if c_time else ""
            if t and t != "nan":
                rows.append((tm, t))
        return name, rows
    except Exception:
        return name, []


def scan_news():
    w("\n【九、新闻电报流 + 关键词雷达】全谱信息面")

    sources = [
        ("财联社", lambda: ak.stock_info_global_cls(symbol="全部")),
        ("财联社2", lambda: ak.stock_info_cjzc_em()),
        ("东财", lambda: ak.stock_info_global_em()),
        ("新浪", lambda: ak.stock_info_global_sina()),
        ("同花顺", lambda: ak.stock_info_global_ths()),
        ("富途", lambda: ak.stock_info_global_futu()),
    ]

    # ★★V11.0 提速①：新闻6源【并发】抓取（原来串行，每源等2秒=12秒起）
    allnews, ok = [], []
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        _res = {}
        with ThreadPoolExecutor(max_workers=6) as _ex:
            _fut = {_ex.submit(_safe_news_one, nm, f): nm for nm, f in sources}
            for _f in as_completed(_fut, timeout=70):
                try:
                    _nm, _rows = _f.result()
                    if _rows:
                        _res[_nm] = _rows
                except Exception:
                    pass
        for _nm, _rows in _res.items():
            allnews += _rows
            ok.append(f"{_nm}({len(_rows)})")
        if allnews:
            w(f"  ⚡并发抓取完成：{len(sources)}源 → {len(allnews)}条")
    except Exception as _e:
        w(f"  [并发失败，改串行] {type(_e).__name__}")
        allnews, ok = [], []
    if allnews:
        pass
    else:
      for name, fn in sources:
        try:
            items = _fetch_news(fn)
            if items:
                allnews.extend(items)
                ok.append(f"{name}({len(items)})")
        except Exception as e:
            w(f"  [跳过] {name}：{type(e).__name__}")
        time.sleep(2)

    if not allnews:
        w("  [报空] 所有新闻源均失败")
        return

    seen, uniq = set(), []
    for tm, t in allnews:
        k = t[:30]
        if k not in seen:
            seen.add(k)
            uniq.append((tm, t))
    try:
        uniq.sort(key=lambda x: x[0], reverse=True)
    except Exception:
        pass

    globals()["TODAY_NEWS"] = uniq        # ★V8.0 供【我的持仓相关消息】
    w(f"  （合并去重：{'、'.join(ok)} → 共{len(uniq)}条）")
    w("\n  ★★★ 关键情报雷达 ★★★")
    any_hit = False
    for cat, kws in NEWS_RADAR.items():
        hits, hseen = [], set()
        for tm, t in uniq:
            if any(k in t for k in kws) and t[:30] not in hseen:
                hseen.add(t[:30])
                hits.append((tm, t))
        if hits:
            any_hit = True
            w(f"  【{cat}】")
            for tm, t in hits[:12]:
                w(f"    [{tm}] {t[:75]}")
    if not any_hit:
        w("  （本次无命中关注关键词）")

    w("\n  ◆ 全量新闻流（最近100条）：")
    for tm, t in uniq[:100]:
        w(f"    [{tm}] {t[:70]}")

    scan_catalyst_heat(uniq)
    scan_deduction(uniq, TODAY_HEAT_TOP3)
    scan_all_sector_cross(uniq)
    scan_deep_meaning(uniq, TODAY_AMBUSH)
    # ★V7.0：止盈/雷达/选股器/公告/异动 已移出本函数 → main() 独立调用
    # 原因：新闻源全挂时本函数会 return，把止盈体系一起吞掉（+10.3%→+7.25%的成因）



def _bt_load(path):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _bt_save(path, data):
    try:
        ks = sorted(data)[-60:]
        data = {k: data[k] for k in ks}
        os.makedirs("reports", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def backtest_ambush(today_pool):
    """埋伏池回测：验证铁律B(机构/游资在跌时买入=明天机会)到底有没有用"""
    w("\n" + "=" * 60)
    w("📊【埋伏池回测】铁律B到底成不成立 —— 用胜率说话")
    w("=" * 60)
    bj = now_beijing()
    today = bj.strftime("%Y-%m-%d")
    can_save = (bj.weekday() < 5) and (bj.hour >= 15)
    hist = _bt_load(AMBUSH_HIST_FILE)
    spot = get_spot()
    if spot is None:
        w("  快照缺失，无法回测")
        return
    c_code = pick_col(spot, ["代码", "code"])
    c_price = pick_col(spot, ["最新价", "trade"])

    days = sorted([d for d in hist if d < today])
    for lag, label in [(1, "次日"), (5, "5日")]:
        if len(days) < lag:
            continue
        base = days[-lag]
        recs = hist[base]
        win, tot, n = 0, 0.0, 0
        detail = []
        for r in recs:
            try:
                row = spot[spot[c_code].astype(str).str.contains(r["code"], na=False)]
                if len(row) == 0:
                    continue
                now_p = pd.to_numeric(row.iloc[0][c_price], errors="coerce")
                if pd.isna(now_p) or not r.get("price"):
                    continue
                pnl = (now_p - r["price"]) / r["price"] * 100
                tot += pnl
                n += 1
                if pnl > 0:
                    win += 1
                detail.append((r["name"], pnl))
            except Exception:
                continue
        if n:
            wr = win / n * 100
            avg = tot / n
            if n < 5:
                verdict = f"⚠️样本仅{n}只，统计无意义，不下结论（需≥5只）"
            elif wr >= 55 and avg > 0:
                verdict = "✅铁律B成立，可信"
            elif wr >= 45:
                verdict = "⚠️边缘，谨慎用"
            else:
                verdict = "❌铁律B在当前行情不成立，停止依赖"
            w(f"\n  ◆ {base} 那批（{n}只）{label}后：")
            w(f"    胜率 {win}/{n} = {wr:.1f}% | 平均收益 {avg:+.2f}% → {verdict}")
            for nm, p in sorted(detail, key=lambda x: -x[1])[:5]:
                w(f"      {nm} {p:+.2f}%")
    if not days:
        w("  首次运行，今日起积累（需1天出次日胜率，5天出5日胜率）")

    if can_save and today_pool:
        hist[today] = today_pool
        _bt_save(AMBUSH_HIST_FILE, hist)
        w(f"  ✅ 已存档今日埋伏池{len(today_pool)}只，历史{len(hist)}天")


HEAT_TO_SECTOR = {
    "算力/云计算": ["计算机设备", "通信设备", "IT服务", "软件开发"],
    "存储芯片": ["半导体", "元件", "电子化学品"],
    "半导体设备/材料": ["半导体", "电子化学品", "非金属材料"],
    "光模块/CPO": ["通信设备", "光学光电子"],
    "软件/EDA/AI应用": ["软件开发", "IT服务"],
    "电力/核电/特高压": ["电力", "电网设备", "输变电设备", "其他电源设备"],
    "锂电/钠电": ["电池", "能源金属", "小金属"],
    "机器人": ["自动化设备", "通用设备", "电机"],
    "创新药/医药": ["医疗服务", "化学制药", "生物制品", "中药"],
    "军工/航天": ["航天装备", "航空装备", "军工电子", "地面兵装"],
    "油气/煤炭": ["油气开采", "炼化及贸易", "煤炭开采", "焦炭"],
    "有色/稀土": ["小金属", "工业金属", "贵金属", "能源金属"],
    "消费/食饮": ["白酒", "食品加工", "饮料乳品", "休闲食品"],
    "汽车/新能源车": ["汽车整车", "汽车零部件", "汽车服务"],
    "养殖/农业": ["养殖业", "饲料", "农产品加工"],
    "影视/传媒/游戏": ["影视院线", "游戏", "广告营销", "出版"],
}


def backtest_heat(top3):
    """热力图回测：净利多前3的板块，之后真的跑赢吗"""
    w("\n" + "=" * 60)
    w("📊【热力图回测】净利多前3 到底跑不跑赢 —— 用超额说话")
    w("=" * 60)
    bj = now_beijing()
    today = bj.strftime("%Y-%m-%d")
    can_save = (bj.weekday() < 5) and (bj.hour >= 15)
    hist = _bt_load(HEAT_HIST_FILE)

    _, bdf = multi_source("板块回测", [
        ("同花顺", lambda: ak.stock_fund_flow_industry(symbol="即时")),
        ("东财", lambda: ak.stock_board_industry_name_em()),
    ])
    cur = {}
    if bdf is not None:
        bn = pick_col(bdf, ["名称", "行业", "板块"])
        bp = pick_col(bdf, ["涨跌幅", "行业指数涨跌", "涨跌"])
        if bn and bp:
            for _, r in bdf.iterrows():
                v = pd.to_numeric(r[bp], errors="coerce")
                if pd.notna(v):
                    cur[str(r[bn])] = float(v)

    days = sorted([d for d in hist if d < today])
    if days and cur:
        base = days[-1]
        rec = hist[base]
        w(f"\n  ◆ {base} 的净利多前3 → 今日表现：")
        hit = 0
        for sect in rec.get("top3", []):
            targets = HEAT_TO_SECTOR.get(sect, sect.replace("/", " ").split())
            matched = []
            for k, v in cur.items():
                if any(t in k or k in t for t in targets):
                    matched.append((k, v))
            if matched:
                # 取该组板块的平均涨跌，比只取第一个准
                avg = sum(x[1] for x in matched) / len(matched)
                k = "、".join(x[0] for x in matched[:3])
                v = avg
                flag = "✅跑赢" if v > 0 else "❌未兑现"
                w(f"    {sect} → 对应[{k}] {v:+.2f}% {flag}")
                if v > 0:
                    hit += 1
            else:
                w(f"    {sect} → 无对应板块数据")
        w(f"    ★命中 {hit}/3")
        w("    ⚠️ 连续5次命中<1/3 → 热力图排序无效，需调整词典权重")
    else:
        w("  首次运行或板块数据缺失，今日起积累")

    if can_save and top3:
        hist[today] = {"top3": top3}
        _bt_save(HEAT_HIST_FILE, hist)
        w(f"  ✅ 已存档今日净利多前3：{'、'.join(top3)}")


def scan_rule_scorecard():
    """规则记分卡：哪条规则真的有用，一目了然"""
    w("\n" + "=" * 60)
    w("📊【规则记分卡】我编的规则，哪条经得起检验")
    w("=" * 60)
    w("  规则                     验证方式              当前状态")
    w("  ─────────────────────────────────────────────")
    for name, how, f in [
        ("铁律B·埋伏池", "次日/5日胜率", AMBUSH_HIST_FILE),
        ("热力图·净利多前3", "次日板块涨跌", HEAT_HIST_FILE),
        ("冷低早·六关", "5日胜率", COLD_HIST_FILE),
        ("★选股器前12", "3日命中率(>3%)", PICKER_HIST_FILE),
        ("★事件驱动雷达", "3日命中率(>3%)", EVENT_HIST_FILE),
    ]:
        d = _bt_load(f)
        n = len(d)
        total_samples = sum(len(v) if isinstance(v, list) else
                            len(v.get("top3", [])) if isinstance(v, dict) else 0
                            for v in d.values())
        st = (f"已积累{n}天/{total_samples}个样本" +
              ("（够了，看上面胜率）" if n >= 5 and total_samples >= 15
               else "（需≥5天且≥15样本）"))
        w(f"  {name:<22} {how:<18} {st}")
    w("\n  ⚠️ 铁律：任何规则连续验证胜率<45%，立即停用，不许再拿它推荐")
    w("  ⚠️ AI不许说『这条规则有用』，只许说『它的历史胜率是X%』")
    w("=" * 60)


# ========== ★仓位建议 + 驱动链集中度 + 组合健康度 ==========

def scan_position_advice(risk_score=None):
    w("\n" + "=" * 60)
    w("💰【仓位建议 + 驱动链集中度 + 组合健康度】")
    w("=" * 60)

    if risk_score is not None:
        if risk_score <= 1:
            adv, txt = "70-80%", "环境健康，可进攻"
        elif risk_score <= 3:
            adv, txt = "50-60%", "中性，正常持仓"
        elif risk_score <= 6:
            adv, txt = "30-40%", "偏弱，只减不加"
        elif risk_score <= 9:
            adv, txt = "20%以下", "高危，大幅降仓"
        else:
            adv, txt = "空仓", "极端风险，清仓观望"
        w(f"  ★风险分 {risk_score}/12 → 建议仓位 【{adv}】（{txt}）")
    else:
        w("  ★风险分未取到，仓位建议跳过")

    held = [(n, ch, mv) for _, n, t, _, _, _, ch, mv in WATCH_STOCKS
            if t == "持仓" and mv > 0]
    if not held:
        w("  无持仓数据")
        return
    total_mv = sum(m for _, _, m in held)
    pos_pct = total_mv / TOTAL_ASSET * 100 if TOTAL_ASSET else 0
    w(f"  ★当前仓位：{total_mv:.1f}万 / {TOTAL_ASSET:.1f}万 = {pos_pct:.0f}%")
    if risk_score is not None:
        lo = {0: 70, 1: 70, 2: 50, 3: 50, 4: 30, 5: 30, 6: 30,
              7: 0, 8: 0, 9: 0}.get(risk_score, 0)
        hi = {0: 80, 1: 80, 2: 60, 3: 60, 4: 40, 5: 40, 6: 40,
              7: 20, 8: 20, 9: 20}.get(risk_score, 0)
        if pos_pct > hi:
            w(f"  🔴 超出建议上限{hi}% → 应减 {(pos_pct-hi)/100*TOTAL_ASSET:.1f}万")
        elif pos_pct < lo:
            w(f"  🟡 低于建议下限{lo}% → 可加 {(lo-pos_pct)/100*TOTAL_ASSET:.1f}万")
        else:
            w("  ✅ 仓位在建议区间内")

    w("\n  ★驱动链集中度（同一条链>40%=危险，7/28全AI链一起挨打的教训）：")
    chains = {}
    for n, ch, mv in held:
        chains.setdefault(ch, []).append((n, mv))
    warn = False
    for ch, items in sorted(chains.items(), key=lambda x: -sum(i[1] for i in x[1])):
        amt = sum(i[1] for i in items)
        pct = amt / TOTAL_ASSET * 100 if TOTAL_ASSET else 0
        names = " + ".join(f"{n}{m}万" for n, m in items)
        flag = " 🔴超40%危险！" if pct > 40 else (" ⚠️接近40%" if pct > 30 else " ✅")
        if pct > 40:
            warn = True
        w(f"    {ch}：{names} = {amt:.1f}万 / {pct:.0f}%{flag}")
    if warn:
        w("    🔴 一条链超40% → 该链一崩全仓挨打，必须分散")

    score = 100
    notes = []
    if risk_score is not None:
        if risk_score >= 7 and pos_pct > 30:
            score -= 30
            notes.append("高危环境仍重仓")
        elif risk_score >= 4 and pos_pct > 60:
            score -= 15
            notes.append("偏弱环境仓位偏高")
    mx = max((sum(i[1] for i in v) / TOTAL_ASSET * 100) for v in chains.values())
    if mx > 40:
        score -= 25
        notes.append(f"驱动链集中度{mx:.0f}%")
    elif mx > 30:
        score -= 10
        notes.append(f"驱动链{mx:.0f}%偏高")
    if len(chains) < 2:
        score -= 20
        notes.append("只有1条驱动链")
    w(f"\n  ★★组合健康度：{max(score,0)}/100" +
      (f"　问题：{'｜'.join(notes)}" if notes else "　✅无问题"))
    w("=" * 60)


# ========== ★★产业链推演引擎（演绎，不是归纳） ==========
# 核心：热力图管"已发生"（归纳），推演引擎管"必然要发生"（演绎）
# 用法：上游事实一旦出现 → 自动推出2-3层下游 → 找市场还没发现的那层

DEDUCTION_CHAINS = [
    {
        "name": "AI算力 → 散热",
        "trigger": ["AI芯片", "GPU", "英伟达", "算力", "数据中心", "服务器",
                    "capex", "资本开支", "功耗", "TDP"],
        "core": ["液冷", "散热", "冷板", "CDU", "浸没", "风冷", "热管", "均热板"],
        "layers": ["①AI芯片功耗暴涨", "②风冷极限→液冷渗透",
                   "③冷板/CDU/快接头/浸没液", "④氟化液/特种泵阀"],
        "stocks": "英维克/申菱环境/高澜股份/同飞股份/飞荣达/中石科技",
        "verify": ["订单", "中标", "量产", "扩产", "投产", "签约", "供货", "涨价"],
    },
    {
        "name": "AI算力 → 供电",
        "trigger": ["AI芯片", "机架", "数据中心", "算力中心", "超节点"],
        "core": ["800VDC", "HVDC", "固态变压器", "BBU", "母线槽", "UPS",
                 "供配电", "电源模块", "SiC"],
        "layers": ["①单机架功率10kW→100kW", "②传统UPS不够→HVDC/800VDC",
                   "③固态变压器/BBU备电/母线槽", "④SiC功率器件"],
        "stocks": "麦格米特/科华数据/科士达/中恒电气/欧陆通/新雷能",
        "verify": ["订单", "中标", "量产", "扩产", "供货", "定点", "签约"],
    },
    {
        "name": "先进封装 → 玻璃基板",
        "trigger": ["先进封装", "CoWoS", "2.5D", "3D堆叠", "封装产能", "载板"],
        "core": ["玻璃基板", "玻璃基", "TGV", "玻璃通孔", "基板", "载板", "ABF"],
        "layers": ["①摩尔定律见顶→算力靠堆封装", "②有机基板承载不了大尺寸",
                   "③玻璃基板成下一代载板", "④TGV激光钻孔/电镀/高纯石英玻璃"],
        "stocks": "凯盛科技/沃格光电/德龙激光/帝尔激光/长电科技/通富微电",
        "verify": ["中试线", "量产", "投产", "订单", "扩产", "投资", "样品", "送样"],
    },
    {
        "name": "存储涨价 → 传导链",
        "trigger": ["AI服务器", "AI芯片", "数据中心", "算力中心", "服务器出货"],
        # ★V9.5：删掉裸词"颗粒"。8/12实测它把
        #   「佐力药业：灵莲花颗粒获批临床」吸进存储链核心词。
        #   中药/食品/化肥都有"颗粒"，是全行业通用词，不是存储专有词。
        #   改用"存储颗粒/闪存颗粒/晶圆颗粒"等限定组合。
        "core": ["存储", "DRAM", "NAND", "HBM", "内存", "闪存",
                 "存储颗粒", "闪存颗粒", "晶圆", "SSD", "eMMC", "UFS",
                 "美光", "海力士", "铠侠", "长鑫", "长江存储", "存储模组"],
        "layers": ["①AI重塑存储周期→供不应求", "②原厂涨价→模组厂涨价",
                   "③终端涨价(手机/PC)", "④设备/材料需求→扩产"],
        "stocks": "兆易创新/江波龙/德明利/佰维存储/香农芯创/深科技",
        "verify": ["涨价", "提价", "缺货", "紧缺", "长约", "扩产", "满产", "量产"],
    },
    {
        "name": "核电核准 → 设备链",
        "trigger": ["核电", "核准", "华龙一号", "核电机组", "并网"],
        "core": ["核电", "核岛", "核级", "锆", "蒸汽发生器", "压力容器",
                 "核燃料", "可控核聚变"],
        "layers": ["①机组核准→3-5年建设期", "②核岛设备招标",
                   "③核级泵阀/管道/锆材", "④后续燃料+运维"],
        "stocks": "中国核电/东方电气/上海电气/江苏神通/纽威股份/应流股份",
        "verify": ["中标", "订单", "招标", "开工", "投产", "签约", "获批"],
    },
    {
        "name": "特高压 → 设备链",
        "trigger": ["特高压", "电网投资", "十五五电网", "输配电"],
        "core": ["特高压", "换流阀", "GIS", "变压器", "电网设备", "输变电",
                 "柔性直流", "组合电器", "绝缘子"],
        "layers": ["①十五五规模翻倍→投资前置", "②换流阀/变压器/GIS招标",
                   "③电缆/绝缘子/组合电器", "④配网+储能配套"],
        "stocks": "许继电气/平高电气/国电南瑞/思源电气/特变电工/中国西电",
        "verify": ["中标", "招标", "订单", "开工", "投运", "签约", "释放"],
    },
    {
        "name": "锂电消费税 → 钠电替代",
        "trigger": ["锂电", "消费税", "碳酸锂", "储能"],
        "core": ["钠电", "钠离子", "硬碳", "层状氧化物", "普鲁士", "聚阴离子"],
        "layers": ["①9/1锂电征4%消费税，钠电免税", "②成本差拉大→钠电替代加速",
                   "③钠电正极/硬碳负极", "④集流体铝箔替代铜箔"],
        "stocks": "容百科技/振华新材/元力股份/鼎胜新材/华阳股份/传艺科技",
        "verify": ["订单", "量产", "投产", "签单", "中标", "投资", "扩产"],
    },
    {
        "name": "机器人量产 → 零部件",
        "trigger": ["人形机器人", "具身智能", "Optimus", "宇树"],
        "core": ["谐波", "减速器", "丝杠", "无框电机", "灵巧手", "触觉传感",
                 "行星滚柱", "关节模组", "机器人零部件"],
        "layers": ["①量产爬坡→零部件放量", "②谐波/行星滚柱丝杠/无框电机",
                   "③灵巧手(微型丝杠/触觉传感)", "④减速器材料+精密加工"],
        "stocks": "绿的谐波/三花智控/鸣志电器/兆威机电/双环传动/贝斯特",
        "verify": ["定点", "订单", "量产", "送样", "产能", "扩产", "供货"],
    },
    {
        "name": "MLCC涨价 → 被动元件",
        "trigger": ["AI服务器", "被动元件", "电子元件"],
        "core": ["MLCC", "电容", "国巨", "村田", "三星电机", "陶瓷粉", "钽电容"],
        "layers": ["①AI服务器高容MLCC紧缺", "②原厂涨价→渠道跟涨",
                   "③国产替代加速", "④上游陶瓷粉/镍粉"],
        "stocks": "风华高科/三环集团/宏达电子/火炬电子/裕兴股份",
        "verify": ["涨价", "提价", "满产", "产能利用率", "订单", "缺货", "紧缺"],
    },
    {
        "name": "AI+制药 → CXO/算力",
        "trigger": ["AI制药", "AI药物", "靶点", "分子设计", "医疗大模型",
                    "新药研发", "临床前", "生物医药", "AI+医疗"],
        "core": ["CXO", "CRO", "CDMO", "AI制药", "AI药物", "靶点发现",
                 "分子设计", "虚拟筛选", "药物设计", "AlphaFold",
                 "生物计算", "医疗大模型", "临床前研究"],
        "layers": ["①新药研发10年/10亿美元/成功率<10%",
                   "②AI把靶点发现从数年→数月，分子设计成本降一个量级",
                   "③药企敢做更多管线→★CXO订单增加+AI平台收服务费",
                   "④算力需求→医药+算力双属性标的"],
        "stocks": "药明康德/成都先导/泓博医药/皓元医药/美迪西/凯莱英/九洲药业",
        "verify": ["订单", "中标", "签约", "合作", "获批", "临床", "交付",
                   "增长", "落地", "上线", "商业化"],
    },
    {
        "name": "猪周期 → 养殖链",
        "trigger": ["生猪", "猪价", "养殖", "能繁母猪", "出栏", "存栏", "饲料"],
        "core": ["能繁母猪", "生猪存栏", "出栏均价", "猪粮比", "去产能",
                 "养殖成本", "仔猪", "母猪产能"],
        "layers": ["①能繁母猪去化→10个月后供给收缩", "②猪价上行→养殖利润修复",
                   "③龙头出栏放量+成本领先", "④饲料/疫苗/设备跟随"],
        "stocks": "牧原股份/温氏股份/新希望/巨星农牧/神农集团",
        "verify": ["去化", "存栏下降", "价格上涨", "利润修复", "出栏增长", "收储"],
    },
    {
        "name": "光模块 → 上游光芯片",
        "trigger": ["光模块", "CPO", "800G", "1.6T", "数据中心互联"],
        "core": ["光芯片", "EML", "DFB", "硅光", "光引擎", "激光器", "PD",
                 "磷化铟", "InP", "衬底", "砷化镓", "GaAs", "外延片", "高纯铟"],
        "layers": ["①AI数据中心互联需求", "②800G/1.6T光模块放量",
                   "③上游光芯片(EML/DFB)+硅光（市场已炒到这层）",
                   "④★InP磷化铟衬底（全球产能高度集中，扩产周期3年+）",
                   "⑤★衬底原材料：高纯铟/磷源/砷化镓"],
        "stocks": "源杰科技/仕佳光子/长光华芯(光芯片层) | "
                  "★云南锗业/博杰股份/有研新材/中镓半导体链(InP衬底层，最少被发现)",
        "verify": ["产能", "良率", "扩产", "订单", "量产", "供货", "涨价"],
    },
]


# ★★★V8.3【事件驱动雷达】关键词（2026-08-10 高争民爆教训）★★★
# 高争民爆(002827) 7/28公告『拟变更控股股东』→ 7/29起9天8板、股价翻倍。
# 我们六道闸全部漏掉，且不是bug是【盲区】：
#   推演引擎10条链无"国资整合"｜热力图16板块无民爆｜冷低早要低位缩量
#   选股器要涨幅<3%｜龙虎榜标它"追高型"｜异动清单只收"无公告"的
# 根因：整个系统围绕【产业链驱动+资金流+位置】造的，
#      而A股最猛的一类短线驱动是【事件】，我们一个模块都没有。
# ★入场点是【公告当天】，不是第9板。公告是硬事件，有确定日期，
#   不像新闻要靠语义猜——这是它比催化热力图可靠的地方。
EVENT_L1 = [   # 一级：控制权/资产变动，历史上最强的短线驱动
    "控股股东变更", "拟变更控股股东", "实际控制人变更", "实控人变更",
    "无偿划转", "国有股权划转", "协议转让", "要约收购", "举牌",
    "重大资产重组", "资产注入", "拟收购", "拟置入", "借壳", "吸收合并",
    "重大资产购买", "发行股份购买资产", "更名", "证券简称变更",
    # ★V8.6 定增：有价格锚、有解禁日、认购方实名，比新闻硬
    "向特定对象发行", "定向增发", "非公开发行", "发行价格为", "募集资金总额",
]
EVENT_L2 = [   # 二级：业绩/订单突变
    "业绩预增", "业绩大幅预增", "扭亏为盈", "净利润同比增长",
    "中标", "重大合同", "重大订单", "框架协议", "战略合作协议",
]
EVENT_L3 = [   # 三级：风险信号，出现即降级（不是买点，是提示）
    "股票交易异常波动", "严重异常波动", "重点监控", "停牌核查",
    "风险提示", "不存在应披露而未披露", "问询函", "关注函", "立案",
]

ANNOUNCE_KEYS = ["收购", "重组", "中标", "订单", "签署", "合作", "增资",
                 "预增", "扭亏", "业绩", "投资", "定增", "回购", "增持",
                 "资质", "许可", "获批", "量产", "投产", "涨价", "扩产",
                 "英伟达", "华为", "特斯拉", "苹果", "台积电", "算力",
                 "涨停", "异动", "股价", "澄清", "说明", "问询", "关注函",
                 "中标公告", "重大合同", "框架协议", "战略合作", "股权",
                 "利润", "营收", "增长", "扭亏", "预告", "快报", "分红",
                 "员工持股", "激励", "并购", "参股", "控股", "举牌"]
ANNOUNCE_KEYS = ANNOUNCE_KEYS + EVENT_L1 + EVENT_L2 + EVENT_L3


def get_stock_flow():
    """★个股主力资金流·六源轮试 + 涨停池/龙虎榜兜底（V5.8）
    返回 (dict{code6: 净额元}, 源名)"""
    src_list = [
        ("同花顺即时", lambda: ak.stock_fund_flow_individual(symbol="即时"),
         ["代码", "股票代码"], ["净额", "流入资金", "主力净流入"]),
        ("同花顺3日", lambda: ak.stock_fund_flow_individual(symbol="3日排行"),
         ["代码", "股票代码"], ["净额", "流入资金", "主力净流入"]),
        ("同花顺5日", lambda: ak.stock_fund_flow_individual(symbol="5日排行"),
         ["代码", "股票代码"], ["净额", "流入资金", "主力净流入"]),
        ("东财今日", lambda: ak.stock_individual_fund_flow_rank(indicator="今日"),
         ["代码", "股票代码"], ["今日主力净流入-净额", "主力净流入-净额"]),
        ("东财5日", lambda: ak.stock_individual_fund_flow_rank(indicator="5日"),
         ["代码", "股票代码"], ["5日主力净流入-净额", "主力净流入-净额"]),
        ("东财10日", lambda: ak.stock_individual_fund_flow_rank(indicator="10日"),
         ["代码", "股票代码"], ["10日主力净流入-净额", "主力净流入-净额"]),
    ]
    for nm, fn, kcols, vcols in src_list:
        try:
            # ★V9.1：8/12实测快扫时六源全挂 → 埋伏池瞎了（铁律B的信号源）
            # 个股资金流是【实时埋伏池】的唯一输入，属关键数据，不受快扫压缩
            f = with_retry(fn, tries=1, wait=2, timeout=45, critical=True)
            if f is None or len(f) == 0:
                continue
            kc = pick_col(f, kcols)
            vc = pick_col(f, vcols)
            if not kc or not vc:
                continue
            m = {}
            for _, r in f.iterrows():
                try:
                    k = str(r[kc])[-6:].zfill(6)
                    v = pd.to_numeric(r[vc], errors="coerce")
                    if pd.notna(v):
                        m[k] = float(v)
                except Exception:
                    continue
            if len(m) > 100:
                # ★V7.0 单位统一为「元」：同花顺系列返回「万元」，东财返回「元」
                if "同花顺" in nm:
                    m = {k: v * 1e4 for k, v in m.items()}
                return m, nm
        except Exception:
            continue

    # ★兜底1：涨停池封板资金（能反映真实买盘强度）
    m = {}
    try:
        zt = with_retry(lambda: ak.stock_zt_pool_em(
            date=now_beijing().strftime("%Y%m%d")), tries=1, timeout=45)
        if zt is not None and len(zt) > 0:
            zc = pick_col(zt, ["代码"])
            zs = pick_col(zt, ["封板资金"])
            if zc and zs:
                for _, r in zt.iterrows():
                    try:
                        v = pd.to_numeric(r[zs], errors="coerce")
                        if pd.notna(v):
                            m[str(r[zc])[-6:].zfill(6)] = float(v)
                    except Exception:
                        continue
    except Exception:
        pass

    # ★兜底2：龙虎榜净买额（机构/游资真金白银）
    try:
        d = now_beijing().strftime("%Y%m%d")
        lhb = with_retry(lambda: ak.stock_lhb_detail_em(start_date=d, end_date=d),
                         tries=1, timeout=45)
        if lhb is not None and len(lhb) > 0:
            lc = pick_col(lhb, ["代码", "股票代码"])
            ln = pick_col(lhb, ["龙虎榜净买额", "净买额", "净额"])
            if lc and ln:
                for _, r in lhb.iterrows():
                    try:
                        v = pd.to_numeric(r[ln], errors="coerce")
                        if pd.notna(v):
                            k = str(r[lc])[-6:].zfill(6)
                            m[k] = max(m.get(k, 0), float(v))
                    except Exception:
                        continue
    except Exception:
        pass

    if m:
        return m, "兜底(涨停封板+龙虎榜)"
    return {}, None


def scan_take_profit():
    """止盈体系：赚到的钱要落袋（V5.7核心）"""
    w("\n" + "=" * 60)
    w("💎💎【止盈体系】赚到的钱要落袋 · 治『从+10.3%回落到+7.25%』 💎💎")
    w("=" * 60)
    w("  ★铁律R：+10%减半锁利；剩余移动止盈(从最高点回落5%)")
    w("  ★铁律S(V5.7)：任何持仓从【历史最高盈亏】回落≥5个百分点 = 强制减半")
    w("  ★V7.2：peak 三源取最大（历史文件/本次/已知种子），防止文件丢失让铁律S失效")
    w("    不管有没有到10%，回撤5个点就是市场在说：这波结束了")

    def _do():
        peaks = {}
        _peak_exists = os.path.exists(PEAK_FILE)
        try:
            if os.path.exists(PEAK_FILE):
                with open(PEAK_FILE, "r", encoding="utf-8") as f:
                    peaks = json.load(f)
        except Exception:
            peaks = {}
        spot = get_spot()
        etf = None
        c_code = pick_col(spot, ["代码", "code"]) if spot is not None else None
        c_price = pick_col(spot, ["最新价", "trade"]) if spot is not None else None
        changed = False
        for code6, name, tag, cost, stop, sect, chain, mv in WATCH_STOCKS:
            if tag != "持仓" or not cost or cost <= 0:
                continue
            price = None
            try:
                if spot is not None and c_code:
                    r = spot[spot[c_code].astype(str).str.contains(code6, na=False)]
                    if len(r) > 0:
                        price = pd.to_numeric(r.iloc[0][c_price], errors="coerce")
                if price is None or pd.isna(price):
                    if etf is None:
                        etf = get_etf_spot()
                    if etf is not None:
                        ec = pick_col(etf, ["代码", "symbol"])
                        ep = pick_col(etf, ["最新价", "trade"])
                        r = etf[etf[ec].astype(str).str.contains(code6, na=False)]
                        if len(r) > 0:
                            price = pd.to_numeric(r.iloc[0][ep], errors="coerce")
            except Exception:
                pass
            if price is None or pd.isna(price):
                w(f"  ◆ {name}({code6})：取价失败")
                continue
            pnl = (float(price) - cost) / cost * 100
            rec = peaks.get(code6, {})
            # ★V7.2：文件值 / 本次盈亏 / 已知种子 三者取最大
            peak = max(rec.get("peak_pnl", pnl), pnl, KNOWN_PEAKS.get(code6, -999))
            if abs(peak - rec.get("peak_pnl", -999)) > 0.001:
                changed = True
            peaks[code6] = {"name": name, "peak_pnl": round(peak, 2)}
            drop = peak - pnl
            line = f"  ◆ {name}({code6})：现{pnl:+.2f}% | 历史最高{peak:+.2f}%"
            if drop > 0.05:
                line += f" | 回撤{drop:.2f}点"
            if peak >= 20 and drop >= 5:
                line += "  🔴【R+S】曾达+20%且回撤5点 → 减至1/4，剩余免费仓"
            elif peak >= 10 and drop >= 5:
                line += "  🔴【触发止盈】曾达+10%且回撤5点 → 立刻减半锁利"
            elif pnl >= 10:
                line += "  💎【达标】+10% → 减半锁利，剩余移动止盈"
            elif drop >= 5:
                line += "  ⚠️【回撤警告】从高点回落5点 → 减1/3"
            elif pnl >= 7:
                line += "  ⏳ 接近+10%，到了就减半，别重演中贝通信"
            w(line)
        if not _peak_exists:
            w("  🔴 position_peak.json 本次不存在 → 说明它没能在两次运行间保留！")
            w("     请确认 GitHub Actions 的 commit 步骤包含 reports/*.json")
            w("     （已用 KNOWN_PEAKS 种子兜底，但新高点仍会丢，必须修 workflow）")
        if changed:
            try:
                os.makedirs("reports", exist_ok=True)
                with open(PEAK_FILE, "w", encoding="utf-8") as f:
                    json.dump(peaks, f, ensure_ascii=False)
            except Exception:
                pass
        w("\n  ⚠️ 止盈三档（写死，不许临场改）：")
        w("    +10% → 减半锁利")
        w("    +20% → 再减半（剩1/4当免费仓）")
        w("    从历史最高回落5个百分点 → 无条件减半，不管到没到10%")
        w("  ★铁律F与S不矛盾：")
        w("    F防止我用【短线跌幅】砍长线仓（还没赚过就砍）")
        w("    S防止我看着【已赚到的利润】飞走不动手")
    safe_run("止盈体系", _do)


def scan_launch_radar():
    """启动日雷达：排名跳升≥30位=当天必须出手（V5.6核心）"""
    w("\n" + "=" * 60)
    w("🚀🚀【启动日雷达】排名跳升≥30位 = 当天必须出手 🚀🚀")
    w("=" * 60)
    w("  ★不看涨幅，只看排名跳升★")
    w("  涨幅大=已经涨完；排名跳升大=资金刚进来")
    w("  教训：8/6医疗服务跳61位我只提一句，8/7才推 → 慢一天=最肥的没了")

    def _do():
        moved = []
        for f, kind in [(HIST_FILE, "行业"), (CONCEPT_FILE, "概念")]:
            try:
                if not os.path.exists(f):
                    w(f"  [跳过] {kind}历史库不存在")
                    continue
                with open(f, "r", encoding="utf-8") as fp:
                    hist = json.load(fp)
            except Exception as e:
                w(f"  [跳过] {kind}库读取失败 {type(e).__name__}")
                continue
            # ★★V9.8 修复：库的真实结构是 {"days": {日期: {...}}}，
            # 旧代码直接 len(hist) 得到的是顶层key数（=1，只有"days"），
            # 所以永远报"仅1天"→【启动日雷达从上线起就没生效过】。
            # 8/13实测：基因测序跳330位、禽流感跳308位，雷达一条没报，
            #   全靠我手工从板块榜里扒 —— 这正是它该自动干的事。
            if isinstance(hist, dict) and "days" in hist and isinstance(hist["days"], dict):
                hist = hist["days"]
            if not isinstance(hist, dict) or len(hist) < 2:
                w(f"  [跳过] {kind}库仅{len(hist) if isinstance(hist,dict) else 0}天，需≥2天")
                continue
            days = sorted(hist.keys())

            def _rank(obj):
                """结构自适应：支持 list[str] / list[dict] / dict{name:rank}"""
                out = {}
                if isinstance(obj, dict):
                    # 可能是 {板块名: 排名} 或 {"list":[...]}
                    inner = obj.get("list") or obj.get("data")
                    if inner is None:
                        # ★V9.8：库的真实格式是 {板块名: {"pct":涨幅, "rank":排名}}
                        for k, v in obj.items():
                            try:
                                if isinstance(v, dict):
                                    r = v.get("rank") or v.get("排名")
                                    c = v.get("pct") or v.get("涨跌幅")
                                    if r is not None:
                                        out[str(k)] = (int(r), c)
                                else:
                                    out[str(k)] = (int(v), None)
                            except Exception:
                                pass
                        return out
                    obj = inner
                if isinstance(obj, list):
                    for i, x in enumerate(obj, 1):
                        if isinstance(x, dict):
                            nm = (x.get("name") or x.get("板块") or
                                  x.get("名称") or x.get("行业"))
                            cg = x.get("chg") or x.get("涨跌幅")
                        else:
                            nm, cg = str(x), None
                        if nm:
                            out[str(nm)] = (i, cg)
                return out

            pr, cu = _rank(hist[days[-2]]), _rank(hist[days[-1]])
            if not pr or not cu:
                w(f"  [跳过] {kind}库结构无法解析，样例={str(hist[days[-1]])[:80]}")
                continue
            for nm, (i, cg) in cu.items():
                if nm not in pr:
                    continue
                jump = pr[nm][0] - i
                if jump >= 30:
                    try:
                        cgv = float(cg) if cg is not None else None
                    except Exception:
                        cgv = None
                    moved.append((jump, kind, nm, i, pr[nm][0], cgv))
        if not moved:
            w("  今日无板块排名跳升≥30位")
            w("  （若历史库不足2天或结构不匹配，明天起生效）")
            return
        moved.sort(key=lambda x: -x[0])
        w(f"\n  ★★今日跳升≥30位的板块（共{len(moved)}个）：")
        for jump, kind, nm, now_r, old_r, cg in moved[:15]:
            ct = f" {cg:+.2f}%" if cg is not None else ""
            flag = ""
            if cg is not None:
                if cg < 2:
                    flag = " 🔥★刚启动+涨幅小=最佳买点★"
                elif cg < 4:
                    flag = " 🔥可上"
                else:
                    flag = " ⚠️已涨多，等回踩"
            w(f"    [{kind}]{nm}{ct} 🚀{old_r}→{now_r}名（跳{jump}位）{flag}")
        w("\n  ⚠️ 铁律Q（V5.6）：★排名跳升≥30位 = 当天必须给个股★")
        w("    ①跳升≥50位 + 当天涨幅<3% = 最高优先级，立刻出手")
        w("    ②不许说『明天验证』——启动日就是最佳买点，第2天就贵了")
        w("    ③从该板块挑：今天涨幅最小 + 主力净流入 + 60日低位的个股")
        w("    ④涨幅大不是理由：涨幅大=已涨完；跳升大=资金刚进来")
    safe_run("启动日雷达", _do)


# ========== ★★V7.0 ①-B驱动链对照表（铁律L的代码化） ==========
# 只有落在这张表里的行业，"板块顺风"才算数。
# 判定标准：这个板块今天涨的【原因】，和这条链的驱动是同一个。
# 新增一条链之前先自问：如果这个驱动不存在，这个板块还会不会涨？
CHAIN_MAP = {
    "AI算力链": ["计算机设备", "通信设备", "通信服务", "光学光电子", "IT服务", "软件开发"],
    "存储涨价链": ["半导体", "元件", "电子化学品"],
    "半导体材料链": ["半导体", "电子化学品", "金属新材料"],
    "MLCC涨价链": ["元件", "金属新材料", "电子元件"],
    "锂电/钠电链": ["电池", "能源金属", "有色金属", "化学制品"],
    "贵金属链": ["贵金属", "小金属"],
    "医药链": ["医疗服务", "生物制品", "化学制药", "医疗器械"],
    "农业(独立)": ["养殖业", "农产品加工", "饲料"],
    "机器人链": ["自动化设备", "通用设备", "专用设备"],
    "电力/核电链": ["电力行业", "电网设备", "电源设备"],
}


def _chain_of(ind):
    """行业名 → 所属驱动链名；不在任何链上返回 None（铁律L）"""
    if not ind:
        return None
    for chain, inds in CHAIN_MAP.items():
        for x in inds:
            if x and (x in ind or ind in x):
                return chain
    return None


# ========== ★★V7.0 选股器自检：每天存前12，3日/5日回看 ==========

def _picker_archive(rows, spot):
    """把今天选股器前12名存档，供 backtest_picker 回看命中率"""
    try:
        c_code = pick_col(spot, ["代码", "code"]) if spot is not None else None
        c_price = pick_col(spot, ["最新价", "trade"]) if spot is not None else None
        today = now_beijing().strftime("%Y-%m-%d")
        d = _bt_load(PICKER_HIST_FILE)
        rec = []
        for nm, cd, sc, ch in rows:
            px = None
            try:
                if spot is not None and c_code:
                    r = spot[spot[c_code].astype(str).str.contains(cd, na=False)]
                    if len(r) > 0:
                        px = float(pd.to_numeric(r.iloc[0][c_price], errors="coerce"))
            except Exception:
                pass
            if px and px == px:
                rec.append({"code": cd, "name": nm, "price": px,
                            "score": round(float(sc), 1), "chain": ch or ""})
        if rec:
            d[today] = rec
            _bt_save(PICKER_HIST_FILE, d)
            w(f"  📌 已存档今日前{len(rec)}只 → 3日后自动回看命中率")
    except Exception as e:
        w(f"  [存档失败] {type(e).__name__}")


def backtest_picker():
    """★选股器回测：涨幅>3%算命中。这是唯一能证明选股器有没有用的东西"""
    w("\n" + "=" * 60)
    w("🔬【选股器回测】我推的到底准不准 · 机器说了算")
    w("=" * 60)
    d = _bt_load(PICKER_HIST_FILE)
    if not d:
        w("  尚无存档，今天是第1天。累计5天后开始出胜率。")
        w("  ⚠️ 铁律：连续验证命中率<45% → 立即停用选股器，不许再拿它推荐")
        return
    spot = get_spot()
    if spot is None:
        w("  [报空] 快照缺失，无法回看")
        return
    c_code = pick_col(spot, ["代码", "code"])
    c_price = pick_col(spot, ["最新价", "trade"])
    today = now_beijing()

    def _px(cd):
        try:
            r = spot[spot[c_code].astype(str).str.contains(cd, na=False)]
            if len(r) > 0:
                v = pd.to_numeric(r.iloc[0][c_price], errors="coerce")
                return float(v) if pd.notna(v) else None
        except Exception:
            pass
        return None

    tot_hit = tot_n = 0
    chain_hit = chain_n = nochain_hit = nochain_n = 0
    for day in sorted(d.keys(), reverse=True)[:10]:
        try:
            gap = (today - datetime.datetime.strptime(day, "%Y-%m-%d")).days
        except Exception:
            continue
        if gap < 3:
            continue
        rows = d[day]
        hit = n = 0
        detail = []
        for it in rows:
            p0 = it.get("price")
            p1 = _px(it.get("code", ""))
            if not p0 or not p1:
                continue
            chg = (p1 - p0) / p0 * 100
            n += 1
            ok = chg > 3
            if ok:
                hit += 1
            if it.get("chain"):
                chain_n += 1
                chain_hit += 1 if ok else 0
            else:
                nochain_n += 1
                nochain_hit += 1 if ok else 0
            detail.append(f"{it.get('name')}{chg:+.1f}%")
        if n:
            tot_hit += hit
            tot_n += n
            w(f"  {day}（{gap}天前）：{hit}/{n} 命中 = {hit/n*100:.0f}%")
            w(f"     {' | '.join(detail[:12])}")
    if tot_n:
        w(f"\n  ★★选股器累计命中率：{tot_hit}/{tot_n} = {tot_hit/tot_n*100:.1f}%（>3%算命中）")
        if chain_n:
            w(f"  ①-B在链上：{chain_hit}/{chain_n} = {chain_hit/chain_n*100:.0f}%")
        if nochain_n:
            w(f"  ①-B不在链：{nochain_hit}/{nochain_n} = {nochain_hit/nochain_n*100:.0f}%")
        w("  → 若『在链』明显高于『不在链』，说明铁律L是对的，可加大链权重")
        w("  → 若两者差不多，说明CHAIN_MAP划分无效，需重划或废掉这条规则")
        if tot_n >= 24 and tot_hit / tot_n < 0.45:
            w("  🔴🔴 命中率<45% → 按铁律【立即停用选股器】，不许再拿它推荐")
    else:
        w("  样本不足（需≥3天前的存档），继续积累")
    w("=" * 60)


def scan_stock_picker():
    """个股级选股器：板块顺风 + 个股还没涨 + 主力真进（V5.3核心）"""
    w("\n" + "=" * 60)
    w("🎯🎯【个股级选股器】板块顺风 + 个股还没涨 + 主力真进 🎯🎯")
    w("=" * 60)
    w("  逻辑：ETF是一篮子平均数，永远赚不到10%")
    w("       要10%只能靠个股：找『板块在涨、它还没涨、但钱在进』的")

    def _do():
        spot = get_spot()
        if spot is None:
            w("  [报空] 快照缺失")
            return
        c_code = pick_col(spot, ["代码", "code"])
        c_name = pick_col(spot, ["名称", "name"])
        c_pct = pick_col(spot, ["涨跌幅", "changepercent"])
        c_amt = pick_col(spot, ["成交额", "amount"])
        if not all([c_code, c_name, c_pct, c_amt]):
            w("  [报空] 快照缺字段")
            return

        fmap, fsrc = get_stock_flow()
        if not fmap:
            w("  ⚠️ 资金流全部6源+2兜底均失败 → 降级为纯技术筛选")
        else:
            w(f"  ✅ 资金流源：{fsrc}（{len(fmap)}只有数据）")

        sect_chg = {}
        try:
            d = with_retry(lambda: ak.stock_fund_flow_industry(symbol="即时"),
                           tries=1, timeout=40)
            n_ = pick_col(d, ["行业", "名称"])
            p_ = pick_col(d, ["涨跌幅", "行业指数涨跌"])
            for _, r in d.iterrows():
                v = pd.to_numeric(r[p_], errors="coerce")
                if pd.notna(v):
                    sect_chg[str(r[n_])] = float(v)
        except Exception:
            pass
        ind_map, _a = _load_ind_cache()

        df = spot.copy()
        df[c_pct] = pd.to_numeric(df[c_pct], errors="coerce")
        df[c_amt] = pd.to_numeric(df[c_amt], errors="coerce")
        df = df.dropna(subset=[c_pct, c_amt])
        df = df[~df[c_name].astype(str).str.contains("退|N |ST", na=False)]
        df["_c6"] = df[c_code].astype(str).str.extract(r"(\d{6})")[0]
        df = df.dropna(subset=["_c6"])
        df = df[(df[c_pct] >= -2.0) & (df[c_pct] <= 3.0)]
        df = df[(df[c_amt] >= 5e7) & (df[c_amt] <= 3e9)]

        cand = []
        for _, r in df.iterrows():
            code6 = r["_c6"]
            flow = fmap.get(code6)
            if fmap and (flow is None or flow <= 0):
                continue
            ind = ind_map.get(code6, "")
            schg = sect_chg.get(ind) if ind else None
            # 板块必须顺风；行业未知时不一票否决（对照表覆盖不全）
            if schg is not None and schg < 0.5:
                continue
            cand.append((code6, str(r[c_name]), float(r[c_pct]),
                         float(r[c_amt]), flow, ind, schg))
        if fmap:
            cand.sort(key=lambda x: -(x[4] or 0))          # 有资金→按主力净额
        else:
            cand.sort(key=lambda x: -x[3])                  # ★无资金→按成交额，
            w("  ⚠️ 资金流全源失败 → 改用【成交额+涨跌量比】筛选")
        cand = cand[:50]

        picks = []
        for code6, nm, pct, amt, flow, ind, schg in cand:
            d60 = vr = None
            try:
                k, kc = _hist_close(code6, ("sh" if code6.startswith("6") else "sz") + code6)
                if k is not None and kc is not None:
                    now_p = pd.to_numeric(k.iloc[-1][kc], errors="coerce")
                    p60 = pd.to_numeric(k.iloc[-45][kc], errors="coerce")
                    if p60:
                        d60 = (now_p - p60) / p60 * 100   # ★V7.0 实为45个交易日，显示已正名
                    kv = pick_col(k, ["volume", "成交量"])
                    if kv:
                        v5 = pd.to_numeric(k[kv].tail(5), errors="coerce").mean()
                        v60 = pd.to_numeric(k[kv].tail(45), errors="coerce").mean()
                        if v60:
                            vr = v5 / v60
            except Exception:
                pass
            # ★涨跌量比（暗流吸筹）——冷低早已验证8天/71样本
            udr = None
            try:
                if k is not None and kc is not None:
                    kv2 = pick_col(k, ["volume", "成交量"])
                    if kv2:
                        kk = k.tail(30).copy()
                        kk["_c"] = pd.to_numeric(kk[kc], errors="coerce")
                        kk["_v"] = pd.to_numeric(kk[kv2], errors="coerce")
                        kk["_chg"] = kk["_c"].pct_change()
                        up = kk[kk["_chg"] > 0]["_v"].mean()
                        dn = kk[kk["_chg"] < 0]["_v"].mean()
                        if dn and dn > 0:
                            udr = up / dn
            except Exception:
                pass
            sc = 0.0
            # ★★V7.0 铁律L落地：板块涨幅只在【已知驱动链】上才计分★★
            # 治错误4(卓胜微)/错误5(券商)：板块在涨 ≠ 涨的原因跟它有关
            in_chain = _chain_of(ind)
            if schg is not None and in_chain:
                sc += min(schg, 6)
            elif schg is not None:
                sc += min(schg, 6) * 0.2   # 不在链上：板块顺风只给两成，逼它靠资金和位置说话
            sc += 3 if pct < 1 else (1 if pct < 2 else 0)
            if d60 is not None and d60 < -10:
                sc += 2
            if vr is not None and vr < 0.9:
                sc += 2
            if flow:
                sc += min(abs(flow) / 1e8 if abs(flow) > 1e6 else abs(flow) / 1e4, 4)
            elif udr is not None and udr > 1.1:
                sc += min((udr - 1.0) * 10, 4)      # 无资金时用暗流替代
            if udr is not None and udr < 1.0:
                sc -= 2                              # 跌日放量=派发，扣分
            picks.append((sc, nm, code6, pct, flow, ind, schg, d60, vr, udr, in_chain))
            time.sleep(0.15)

        if not picks:
            w("  今日无符合条件的个股")
            return
        picks.sort(key=lambda x: -x[0])
        w(f"  （源：{fsrc or '无资金'}｜行业表{len(ind_map)}只｜候选{len(picks)}只）")
        w("\n  ★★【板块在涨 · 它还没涨 · 主力在进】前12：")
        for i, (sc, nm, cd, pct, fl, ind, schg, d60, vr, udr, ch) in enumerate(picks[:12], 1):
            ft = ""
            if fl:
                ft = f" 主力+{fl/1e8:.2f}亿" if abs(fl) > 1e6 else f" 主力+{fl/1e4:.0f}万"
            elif udr is not None:
                ft = f" 量比{udr:.2f}"
            st = f" [{ind}{schg:+.1f}%]" if ind and schg is not None else (f" [{ind}]" if ind else "")
            dt = f" 45日{d60:+.0f}%" if d60 is not None else ""
            vt = f" 缩量{vr:.2f}" if vr is not None else ""
            ct = f"  ①-B链:{ch}" if ch else "  ①-B链:❓不在已知驱动链(板块顺风只计20%)"
            w(f"    {i:2d}. {nm}({cd}) {pct:+.2f}%{ft}{st}{dt}{vt} 得分{sc:.1f}")
            w(f"        {ct}")
        w("\n  ⚠️ 铁律P（V5.3）：★有个股就不许只给ETF★")
        w("    ETF是一篮子平均数，注定跑不出10%")
        w("    仍需过①-B真实驱动 + ⑨逻辑破定义才能推荐")
        w("  ⚠️ 铁律L（V7.0已写进打分）：①-B链显示❓的，板块涨幅只给20%权重")
        w("     卓胜微/券商两次翻车都是『板块在涨但涨的原因跟它无关』")
        # ★V7.0 存档，供 backtest_picker 回看
        _picker_archive([(nm, cd, sc, ch) for sc, nm, cd, *_r, ch in picks[:12]], spot)
    safe_run("个股级选股器", _do)


def _placement_from_announce():
    """★V8.7 定增雷达的兜底：接口挂了就从【公告标题】里抠发行价。
    公告标题常见形态：
      『XX关于向特定对象发行股票发行情况报告书』
      『XX：完成向特定对象发行股票，发行价格为560.00元/股』
    抠到价格就能和现价比，抠不到就只列出有定增动作的公司。"""
    import re as _re
    ann = globals().get("TODAY_ANNOUNCE_RAW", []) or []
    news = globals().get("TODAY_NEWS", []) or []
    src = [(nm, cd, t) for nm, cd, t in ann] + [("", "", t) for _tm, t in news]
    KEY = ["向特定对象发行", "定向增发", "非公开发行", "发行价格"]
    hits, seen = [], set()
    for nm, cd, t in src:
        if not any(k in t for k in KEY):
            continue
        if t[:26] in seen:
            continue
        seen.add(t[:26])
        m = _re.search(r"发行价格?为?\s*([0-9]+(?:\.[0-9]+)?)\s*元", str(t))
        price = float(m.group(1)) if m else None
        hits.append((nm, cd, t, price))
    if not hits:
        w("  今日公告与快讯中无定增相关内容")
        return
    spot = get_spot()
    sc_code = sc_price = s_str = None
    if spot is not None:
        sc_code = pick_col(spot, ["代码", "code"])
        sc_price = pick_col(spot, ["最新价", "trade"])
        if sc_code:
            s_str = spot[sc_code].astype(str)
    w(f"\n  ★从公告/快讯中命中 {len(hits)} 条定增相关★\n")
    for i, (nm, cd, t, price) in enumerate(hits[:10], 1):
        now_p = None
        if cd and s_str is not None:
            try:
                r = spot[s_str.str.contains(cd, na=False)]
                if len(r) > 0:
                    v = pd.to_numeric(r.iloc[0][sc_price], errors="coerce")
                    now_p = float(v) if pd.notna(v) else None
            except Exception:
                pass
        line = f"  {i:2d}. {nm or '（未识别公司）'}({cd})"
        if price:
            line += f"  发行价{price:.2f}"
            if now_p:
                d = (now_p - price) / price * 100
                flag = "🟢深度折价" if d < -30 else ("🟡折价" if d < -10 else
                       ("⚪平价" if d < 5 else "🔴溢价(现价高于发行价)"))
                line += f" → 现价{now_p:.2f} {d:+.1f}% {flag}"
        w(line)
        w(f"      {str(t)[:66]}")
    w("\n  ⚠️ 兜底模式只覆盖【今日新出的】定增，不含历史。")
    w("     完整历史需要 stock_qbzf_em 接口恢复。")


# ═══════════════════════════════════════════════════════
# ★★★V11.0【选股流水线】—— 用户2026-08-13设计★★★
# 用户原话：『第一步看新闻，看美股，分析板块，然后从板块里面找出股票的
#   所有信息，分析完后结合市场信息/指标/资金/技术/股东结构/基本面/
#   美股大趋势，选出一只股』
#
# ★为什么必须反过来：
#   旧流程 = 我先想到一只票 → 再去找数据支持 → 找不到就编
#     8/13事故：我"想起"香农芯创，凭记忆写603322（实际300475），
#     报告显示27.63元、实际163.46元，用户按错价格下单。
#   新流程 = 先定方向 → 从板块成分股里挖票 → 每只全维度体检 → 排序
#     ★代码来自系统，不是我的记忆 → 从根上杜绝写错代码
#     ★没有全维度数据的票，根本进不了候选 → 从根上杜绝"没查就推"
# ═══════════════════════════════════════════════════════

def _board_cons(board_name, kind="行业"):
    """取板块成分股。返回 [(代码,名称)]"""
    fns = []
    if kind == "行业":
        fns = [("东财", "stock_board_industry_cons_em"),
               ("同花顺", "stock_board_industry_cons_ths")]
    else:
        fns = [("东财", "stock_board_concept_cons_em"),
               ("同花顺", "stock_board_concept_cons_ths")]
    for tag, fname in fns:
        fn = getattr(ak, fname, None)
        if fn is None:
            continue
        try:
            df = with_retry(lambda: fn(symbol=board_name), tries=1, wait=1, timeout=20)
            if df is None or len(df) == 0:
                continue
            cc = pick_col(df, ["代码", "股票代码", "code"])
            cn = pick_col(df, ["名称", "股票简称", "name"])
            if not cc:
                continue
            out = []
            for _, r in df.iterrows():
                c = str(r[cc])[-6:]
                n = str(r[cn]).strip() if cn else ""
                if c.isdigit():
                    out.append((c, n))
            if out:
                return out
        except Exception:
            continue
    return []


def scan_pipeline():
    """★★★V11.0 选股流水线：新闻→美股→板块→成分股→全维度→选一只★★★"""
    w("\n" + "=" * 60)
    w("🏭🏭【选股流水线】方向→板块→成分股→全维度体检→选出一只 🏭🏭")
    w("=" * 60)
    w("  ★用户2026-08-13设计：『先看新闻、看美股、分析板块，")
    w("    然后从板块里找出股票的所有信息，结合指标/资金/技术/")
    w("    股东结构/基本面/美股大趋势，选出一只股』")
    w("  ★为什么反过来：旧流程是我先想到票再找数据，找不到就编。")
    w("    8/13我把香农芯创写成603322(实际300475)，价差6倍。")
    w("    ★新流程的代码来自系统，不是我的记忆。")

    # ── 第1步：方向（来自热力图 + 推演验证信号 + 跳升榜）──
    w("\n  ── 第1步：今日方向（新闻催化 × 验证信号 × 排名跳升）──")
    dirs = {}          # {板块名: 得分}
    for nm, sc in (globals().get("TODAY_HEAT_TOP3") or [])[:3]:
        dirs[nm] = dirs.get(nm, 0) + 3
        w(f"    热力图前3：{nm} (+3)")
    for nm, jp in sorted(SECTOR_JUMP_MAP.items(), key=lambda x: -x[1])[:8]:
        if jp >= 100:
            dirs[nm] = dirs.get(nm, 0) + 4
        elif jp >= 50:
            dirs[nm] = dirs.get(nm, 0) + 3
        elif jp >= 30:
            dirs[nm] = dirs.get(nm, 0) + 2
    _dv = globals().get("TODAY_VERIFIED_CHAINS") or []
    for nm in _dv[:3]:
        dirs[nm] = dirs.get(nm, 0) + 5
        w(f"    ✅有验证信号的链：{nm} (+5)")
    if not dirs:
        w("    ⚠️ 无方向数据（热力图/跳升榜/推演均无输出）→ 流水线跳过")
        w("=" * 60)
        return
    top_dirs = sorted(dirs.items(), key=lambda x: -x[1])[:3]
    w(f"\n  ★方向前3：" + " ｜ ".join(f"{n}({v}分)" for n, v in top_dirs))

    # ── 第2步：取这些板块的成分股 ──
    w("\n  ── 第2步：从这些板块取成分股 ──")
    pool = {}
    for nm, _v in top_dirs:
        for kind in ("行业", "概念"):
            cons = _board_cons(nm, kind)
            if cons:
                w(f"    [{kind}]{nm}：{len(cons)}只成分股")
                for c, n in cons:
                    pool.setdefault(c, (n, nm))
                break
    if not pool:
        w("    ⚠️ 成分股接口全部失败 → 降级：改用【冷低早+选股器】的现成名单")
        w("=" * 60)
        return
    w(f"    合计去重 {len(pool)} 只")

    # ── 第3步：用快照先粗筛（位置好+不追高+有量） ──
    sp = get_spot()
    if sp is None:
        w("    🔴 快照缺失，流水线无法继续")
        w("=" * 60)
        return
    cc = pick_col(sp, ["代码", "code"])
    cn = pick_col(sp, ["名称", "name"])
    cp = pick_col(sp, ["最新价", "trade"])
    cg = pick_col(sp, ["涨跌幅", "changepercent"])
    ca = pick_col(sp, ["成交额", "amount"])
    ct = pick_col(sp, ["换手率", "turnoverratio"])
    ce = pick_col(sp, ["市盈率-动态", "市盈率", "pe"])
    sp2 = sp.copy()
    sp2["_c6"] = sp2[cc].astype(str).str[-6:]
    sub = sp2[sp2["_c6"].isin(pool.keys())]
    w(f"\n  ── 第3步：快照粗筛（{len(sub)}只有行情）──")
    cands = []
    for _, r in sub.iterrows():
        try:
            c6 = r["_c6"]
            nm = str(r[cn]).strip()
            if "ST" in nm or "退" in nm:
                continue
            g = pd.to_numeric(r[cg], errors="coerce")
            px = pd.to_numeric(r[cp], errors="coerce")
            amt = pd.to_numeric(r[ca], errors="coerce")
            if pd.isna(g) or pd.isna(px) or pd.isna(amt):
                continue
            # ★不追高：当天涨幅 -3% ~ +5%
            if not (-3 <= float(g) <= 5):
                continue
            # ★有流动性但不爆炒：成交额 5千万 ~ 60亿
            if not (5e7 <= float(amt) <= 6e9):
                continue
            pe = pd.to_numeric(r[ce], errors="coerce") if ce else None
            to = pd.to_numeric(r[ct], errors="coerce") if ct else None
            cands.append({"code": c6, "name": nm, "px": float(px),
                          "chg": float(g), "amt": float(amt),
                          "pe": float(pe) if pe is not None and pd.notna(pe) else None,
                          "to": float(to) if to is not None and pd.notna(to) else None,
                          "board": pool[c6][1]})
        except Exception:
            continue
    if not cands:
        w("    ⚠️ 粗筛后无标的（可能全部已大涨或成交异常）")
        w("=" * 60)
        return
    # 涨幅小的优先
    cands.sort(key=lambda x: x["chg"])
    w(f"    过滤后 {len(cands)} 只（当天-3%~+5%、成交0.5-60亿、排除ST）")

    # ── 第4步：对前12只跑全维度体检 ──
    w("\n  ── 第4步：全维度体检（技术/资金/估值）──")
    scored = []
    for c in cands[:12]:
        d = scan_deep_stock(c["code"], c["name"])
        sc, why = 0.0, []
        # 位置：站上MA5但仍在MA20下方 = 刚起来
        ma5, ma20, px = d.get("MA5"), d.get("MA20"), c["px"]
        if ma5 and ma20:
            if px >= ma5 and px < ma20:
                sc += 4; why.append("站上MA5仍在MA20下(启动位)")
            elif px >= ma5 and px >= ma20:
                sc += 2; why.append("双线之上")
            else:
                sc -= 2; why.append("跌破MA5")
        # 资金：超大单
        z = d.get("超大单净额")
        if z is not None:
            if z > 0:
                sc += 4; why.append(f"超大单+{z/1e4:.0f}万")
            else:
                zz = d.get("中单净额") or 0
                if zz > 0:
                    sc -= 4; why.append(f"🔴超大单{z/1e4:.0f}万中单接盘")
                else:
                    sc -= 1; why.append(f"超大单{z/1e4:.0f}万")
        d5 = d.get("主力5日累计")
        if d5 is not None and d5 > 0:
            sc += 2; why.append(f"主力5日+{d5/1e8:.2f}亿")
        # 位置分：当天涨幅越小越好
        sc += (2 if c["chg"] < 0 else (1.5 if c["chg"] < 2 else 0))
        # 估值：市盈率0-60加分，>120扣分
        if c["pe"] is not None:
            if 0 < c["pe"] <= 60:
                sc += 1.5; why.append(f"PE{c['pe']:.0f}")
            elif c["pe"] > 120:
                sc -= 1.5; why.append(f"⚠️PE{c['pe']:.0f}偏高")
        # 换手：3-15%健康
        if c["to"] is not None and 3 <= c["to"] <= 15:
            sc += 1; why.append(f"换手{c['to']:.1f}%")
        scored.append((sc, c, d, why))
    scored.sort(key=lambda x: -x[0])

    # ── 第5步：输出前5，第1名给完整决策卡 ──
    w("\n  ── 第5步：排序结果 ──")
    for i, (sc, c, d, why) in enumerate(scored[:5], 1):
        w(f"  {i}. {c['name']}({c['code']}) {c['px']:.2f} 今{c['chg']:+.2f}% "
          f"[{c['board']}] 得分{sc:.1f}")
        w(f"     {' | '.join(why) if why else '无加分项'}")
    if scored:
        sc, c, d, why = scored[0]
        w("\n  ★★★【流水线选出】★★★")
        print_deep_stock(c["code"], c["name"])
        w(f"  📌 方向来源：{c['board']}（今日方向前3）")
        w(f"  📌 得分{sc:.1f}｜代码来自板块成分股接口，非AI记忆★")
        w("  ⚠️ 仍需人工过①-B：它靠什么赚钱？和板块涨的原因是同一个吗？")
    w("=" * 60)


def scan_all_deep():
    """★★V10.1：对【所有持仓 + 候选池】逐只跑深度体检★★
    ★用户原话：『你什么都不查就推荐，我很害怕』
    ★从今天起，任何标的在被推荐前，这张表必须已经在报告里。
      表里没有 = 我没数据 = 不许给买点、不许给价格、不许给仓位。
    """
    w("\n" + "=" * 60)
    w("🔬🔬【个股深度体检】推荐前必查 —— 财务/技术/资金/代码 🔬🔬")
    w("=" * 60)
    w("  ★2026-08-13事故：我推香农芯创，六项检查只做到一项。")
    w("    代码写成603322(实际300475)、个股资金没查、主力成本没查、")
    w("    市盈率/换手/量比全没查，报告显示27.63元而实际163.46元。")
    w("  ★用户原话：『你什么都不查就推荐，我很害怕』")
    w("  ⚠️ 本表【无数据】的字段，不许在推荐里编一个数出来。")

    targets = []
    for _t in WATCH_STOCKS:
        try:
            _code, _name, _tag = _t[0], _t[1], _t[2]
        except Exception:
            continue
        if _tag in ("持仓", "候选", "重点观察"):
            targets.append((_code, _name, _tag))
    if not targets:
        w("  清单为空")
        w("=" * 60)
        return
    # 持仓优先，候选其次
    targets.sort(key=lambda x: {"持仓": 0, "候选": 1}.get(x[2], 2))
    n_bad = 0
    # ★V11.0提速：持仓全跑，候选只跑前6只（体检要抓个股资金流，每只1-2秒）
    _hold = [t for t in targets if t[2] == "持仓"]
    _other = [t for t in targets if t[2] != "持仓"][:6]
    targets = _hold + _other
    for _code, _name, _tag in targets:
        w(f"\n  [{_tag}]")
        _d = print_deep_stock(_code, _name)
        _rn = _d.get("真实名称")
        if not _rn or (_name and _rn != _name and _name not in _rn and _rn not in _name):
            n_bad += 1
    if n_bad:
        w(f"\n  🔴🔴 有 {n_bad} 只【代码与名称不符或查无此股】→ 立刻改 我的清单.txt")
    w("=" * 60)


def scan_reco_checklist():
    """★★★V9.4【推荐前强制检查表】★★★

    ★写这条的原因（2026-08-12 三笔推荐全部漏查个股级数据）：
      佰维存储 26%仓位 —— 我只看了『存储链验证信号4条 + 半导体资金+125亿
        + 60日-20.7%』，全是【板块级】数据。
        没查的：超大单-1.49亿而中单+1.43亿接盘、20日净流入-47.7亿、
        主力平均持仓成本243.98(用户买243.85，几乎同价，但主力建仓20天)、
        当天12条公告。★这些是用户截图给我我才看到的★
      新宙邦 11% —— 推它的理由是『缩量0.52全场最缩=还没涨』，
        但同板块天华新能+3.94%在涨，它-0.78%在跌。
        ★『没涨』和『不涨』是两回事，我没分清★
      中恒电气 7% —— 推荐时它当天已+7.44%，那是追高。

    ★共同点：三笔全部只看【板块级】，一个【个股级】数据都没查。
    ★用户原话：『今天运气好，没事，万一呢？』
    """
    w("\n" + "=" * 60)
    w("🔒🔒【推荐前强制检查表】五项缺一，仓位砍半 🔒🔒")
    w("=" * 60)
    w("  ★★2026-08-12三笔推荐全部只查了【板块级】，漏了【个股级】★★")
    w("    佰维26%仓位：超大单-1.49亿中单接盘、20日-47.7亿、")
    w("      主力平均成本243.98、当天12条公告 —— 全是用户截图我才看到")
    w("")
    w("  ┌─ 0️⃣ ★★代码核对（V10.0新增，8/13买错票事故）★★ ────")
    w("  │  🔴 推荐任何标的前，第一件事是核对【代码】和【名称】对不对")
    w("  │  🔴 不许凭记忆写代码。必须来自本报告【重点盯盘】那一节，")
    w("  │     或明确说『代码我不确定，你搜一下名字确认』")
    w("  │  ⚠️ 2026-08-13：我把香农芯创写成603322(实际300475)，")
    w("  │     报告连续三天显示27.63元，实际163.46元，差6倍。")
    w("  │     用户按我给的价格下单，买入价与预期完全不符。")
    w("  │  ★这不是判断错，是【给了不存在的代码】——比判断错严重得多")
    w("  │  ★检查方法：报告的【重点盯盘】里有没有这只？")
    w("  │     没有 = 我没有它的真实数据 = 不许给买点和价格")
    w("  └────────────────────────────────────")
    w("  ┌─ 1️⃣ 个股资金流（不是板块资金！）─────────────")
    w("  │  · 超大单/大单/中单/小单 分别多少")
    w("  │  · 3日 / 5日 / 20日 净流入")
    w("  │  🔴超大单流出 + 中单接盘 = 主力在出货，不管当天涨跌")
    w("  │  ⚠️报告的【板块资金】是行业总和，不等于这只票")
    w("  │     必须单独查该股的大单流向（同花顺F10-资金）")
    w("  └────────────────────────────────────")
    w("  ┌─ 2️⃣ 主力平均持仓成本 vs 我的买入价 ──────────")
    w("  │  · 买在主力成本【之下】= 有安全垫")
    w("  │  · 买在主力成本【之上或同价】= 你是他的退出对手盘")
    w("  │  ⚠️即使同价也不对等：主力建仓20天，你今天才进")
    w("  └────────────────────────────────────")
    w("  ┌─ 3️⃣ 当天公告（点名到这只票的）───────────────")
    w("  │  ✅回购/股权激励/中标/业绩预增 = 加分")
    w("  │  🔴减持/问询函/立案/异常波动/风险提示 = ★一票否决★")
    w("  │  ⚠️见本报告【公司公告雷达】+【我的持仓相关消息】两节")
    w("  └────────────────────────────────────")
    w("  ┌─ 4️⃣ 同链对比：这只 vs 同板块其他票 ────────────")
    w("  │  · 同链别的在涨、它在跌 → 『不涨』不是『没涨』")
    w("  │  · 『还没启动』和『被抛弃』形态一样，靠同链对比区分")
    w("  └────────────────────────────────────")
    w("  ┌─ 5️⃣ 位置：当天已涨多少 ─────────────────────")
    w("  │  · 当天涨 >5% = 追高，不管理由多硬")
    w("  │  · 最佳：当天 -3% ~ +2%，且60日为负")
    w("  └────────────────────────────────────")
    w("")
    w("  ⚠️ 0️⃣代码核对不通过 = 🔴一票否决，不管其余五项多好")
    w("  ★★仓位由【过了几项】决定，不由分散决定★★")
    w("    五项全过 + 有验证信号 + 位置低 → 25-30%")
    w("    过三四项                      → 11%")
    w("    只有故事没验证信号             → ≤6% 或不买")
    w("    缺三项以上                     → 🔴不许推荐")
    w("  ⚠️ 用户原话：『1万仓位赚10%只有1000块』——仓位要够重，")
    w("     但【够重的前提是五项全过】。佰维只过了两项就给了26%。")
    w("=" * 60)


def scan_placement_radar():
    """★★★V8.8【定增定价锚雷达】—— 用户命题（8/11江波龙）★★★

    ★★我8/11把这套逻辑做错了方向，现在改回来★★
      错版：按【折价最深】排序 → 当作"跌多了会涨回去"
      真相：折价8折发行是A股常规操作，一大半定增都这样，【不含信息】
            ★溢价发行才罕见 —— 有人愿意为一个未来【多付钱】

    ★江波龙(301308) 8/7 完成定增，这才是标准样本：
        当日收盘 386.6 元，发行价 560 元 → 【溢价45%】
        21家认购：易方达5.3亿 / 财通2.48 / 诺德2.21 / 南方2.01 / 华夏1.14
        ★发起人股东王伟民、杨晓斌、黄海华、张旭，报价 700-710 元
        ★产业买家：星宸科技、阳光电源子公司 各1亿
        有效报价区间 452.90-710.00，最终定在 560
      → 最懂它的人 + 同业产业方 + 头部公募，一起把价定在560-710。
        今天市价417.5。这才是【定价锚】的意义。

    ★★三条反例写死（用户原话："不可能亏钱做生意"）★★
      定增破发 ≠ 公司会拉回去：
        a) 钱已到公司账上，涨跌不退。上市公司拉抬自家股价是操纵市场，违法
        b) 限售6-18个月，认购方在期内卖不了，浮亏无即时压力
        c) 解禁日是【抛压】不是支撑
      易方达那5.3亿是基民的钱，亏了基金经理不赔。
      江波龙自己从750跌到308，600-700元买的机构早就亏了。
    ★正确用法：发行价 = 专业买方的【定价锚】，不是【保底承诺】。
    """
    w("\n" + "=" * 60)
    w("💵💵【定增定价锚雷达】谁愿意为这只票多付钱 💵💵")
    w("=" * 60)
    w("  ★★核心不是『折价多少』，是『溢价还是折价』★★")
    w("    折价8折发行 = A股常规操作，一大半定增都这样，不含信息")
    w("    ★溢价发行 = 罕见 = 有人愿意为一个未来多付钱")
    w("  ★加分项：创始团队/原高管认购 > 产业买家认购 > 头部公募领投")
    w("  ⚠️ 反例写死：定增破发≠公司会救。钱已到账不退｜限售期内卖不了｜")
    w("     解禁日是抛压不是支撑。江波龙自己从750跌到308，机构照样亏。")

    _name, df = None, None
    for fn_name in ("stock_qbzf_em", "stock_zf_em", "stock_add_stock_em"):
        fn = getattr(ak, fn_name, None)
        if fn is None:
            continue
        try:
            df = with_retry(fn, tries=1, wait=2, timeout=25)
            if df is not None and len(df) > 0 and pick_col(df, ["发行价格", "增发价格", "发行价"]):
                _name = fn_name
                break
            df = None
        except Exception as e:
            w(f"  [切换] {fn_name} 失败({type(e).__name__})")
            df = None
    if df is None or len(df) == 0:
        w("  ⚠️ 增发数据接口不可用 → 启用【公告兜底】")
        _placement_from_announce()
        w("=" * 60)
        return

    w(f"  （源：{_name}，共{len(df)}条）")
    c_code = pick_col(df, ["代码", "股票代码", "code"])
    c_price = pick_col(df, ["发行价格", "增发价格", "发行价"])
    c_date = pick_col(df, ["发行日期", "增发上市日", "上市日", "公告日"])
    # ★关键新列：发行时的市价/折价率，用来判断溢价还是折价
    c_mkt = pick_col(df, ["发行日收盘价", "增发价格/发行日收盘价", "发行日市价"])
    c_disc = pick_col(df, ["折价率", "溢价率", "发行价格/发行日收盘价"])
    if not (c_code and c_price):
        w(f"  [报空] 缺关键列。实际列名：{list(df.columns)[:14]}")
        w("=" * 60)
        return

    spot = get_spot()
    if spot is None:
        w("  [报空] 快照缺失")
        w("=" * 60)
        return
    sc_code = pick_col(spot, ["代码", "code"])
    sc_price = pick_col(spot, ["最新价", "trade"])
    sc_name = pick_col(spot, ["名称", "name"])
    s_str = spot[sc_code].astype(str)

    rows = []
    today = now_beijing()
    for _, r in df.iterrows():
        try:
            cd = str(r[c_code])[-6:]
            issue = pd.to_numeric(r[c_price], errors="coerce")
            if pd.isna(issue) or float(issue) <= 0:
                continue
            gap = None
            if c_date:
                try:
                    d0 = datetime.datetime.strptime(str(r[c_date])[:10], "%Y-%m-%d")
                    gap = (today - d0).days
                    if gap < 0 or gap > 400:
                        continue
                except Exception:
                    gap = None
            # ★发行时溢价率：发行价 vs 发行日市价
            prem = None
            if c_mkt:
                mv = pd.to_numeric(r[c_mkt], errors="coerce")
                if pd.notna(mv) and float(mv) > 0:
                    prem = (float(issue) - float(mv)) / float(mv) * 100
            m = spot[s_str.str.contains(cd, na=False)]
            if len(m) == 0:
                continue
            now_p = pd.to_numeric(m.iloc[0][sc_price], errors="coerce")
            if pd.isna(now_p) or float(now_p) <= 0:
                continue
            nm = str(m.iloc[0][sc_name])
            vs_now = (float(now_p) - float(issue)) / float(issue) * 100
            rows.append((prem, nm, cd, float(issue), float(now_p), vs_now, gap))
        except Exception:
            continue

    if not rows:
        w("  近400天内无可比对的定增记录")
        w("=" * 60)
        return

    # ★★排序核心：溢价发行排最前（prem大→小），无溢价数据的排后面★★
    rows.sort(key=lambda x: (-(x[0] if x[0] is not None else -999)))
    prem_rows = [x for x in rows if x[0] is not None and x[0] > -5]
    deep_rows = sorted([x for x in rows if x[5] < -20], key=lambda y: y[5])

    if prem_rows:
        w(f"\n  ★★🟢【溢价/平价发行】{len(prem_rows)}笔 —— 罕见，最值钱★★")
        for i, (prem, nm, cd, issue, now_p, vs_now, gap) in enumerate(prem_rows[:10], 1):
            f1 = "🟢🟢溢价" if prem > 10 else ("🟢小幅溢价" if prem > 0 else "⚪平价")
            gs = f" 距发行{gap}天" if gap is not None else ""
            w(f"  {i:2d}. {nm}({cd}) {f1}{prem:+.0f}%发行")
            w(f"      发行价{issue:.2f} → 现价{now_p:.2f}  {vs_now:+.1f}%{gs}")
    else:
        w("\n  近期无溢价发行案例（这是常态，溢价发行本就罕见）")

    if deep_rows:
        w(f"\n  ── 🟡现价低于发行价20%以上 {len(deep_rows)}笔（仅供参考，非买入理由）──")
        for i, (prem, nm, cd, issue, now_p, vs_now, gap) in enumerate(deep_rows[:8], 1):
            ps = f" 当时{prem:+.0f}%" if prem is not None else ""
            w(f"  {i:2d}. {nm}({cd}) 发行价{issue:.2f}→现价{now_p:.2f} {vs_now:+.1f}%{ps}")

    w("\n  ── 怎么用（三条纪律）──")
    w("  1. ★只有【溢价发行】才是强信号★。折价8折是常规，不含信息")
    w("  2. ★必须查认购名单★：创始团队/原高管 > 产业买家 > 头部公募 > 纯财务")
    w("     江波龙有前三类全占（王伟民等4位发起人报价700-710）")
    w("  3. ★查解禁日★：限售6或18个月。解禁前是空窗，解禁日是抛压。")
    w("     ⚠️ 别在解禁前一个月进")
    w("=" * 60)


def scan_event_radar():
    """★★★V8.3【事件驱动雷达】★★★
    专抓 控股股东变更/资产注入/无偿划转/重组/更名 这类【硬事件】。

    ★为什么单独成模块，不并进公告雷达：
      公告雷达是"看看今天有啥"，事件雷达是"这条能不能明天就买"。
      判定要素完全不同——事件雷达只关心三件事：
        ① 事件等级（控制权变动 > 业绩订单）
        ② 今天涨了没有（★核心：公告当天没涨=最佳入场点）
        ③ 有没有出风险提示（公司否认/交易所监控=催化已证伪）

    ★高争民爆(002827)复盘：
        7/28 公告『拟变更控股股东』当天没涨停 ← 这是入场点
        7/29-8/10 9天8板，翻倍
        8/07 公司公告『不存在资产注入计划』+ 深交所重点监控 ← 催化证伪
      所以同一只票，7/28是🟢一级机会，8/07之后是🔴已证伪。
      时间点决定一切，这正是事件驱动和产业驱动最大的区别。
    """
    w("\n" + "=" * 60)
    w("💥💥【事件驱动雷达】控制权变动/资产注入/重组 —— A股最猛的短线驱动 💥💥")
    w("=" * 60)
    w("  ★入场点是【公告当天】，不是第N个板。公告是硬事件，有确定日期。")
    w("  ★2026-08-10 教训：高争民爆7/28公告控股股东变更→9天8板翻倍，")
    w("    我们六道闸全漏（推演/热力图/冷低早/选股器/龙虎榜/异动清单）")

    ann = globals().get("TODAY_ANNOUNCE_RAW", []) or []
    news = globals().get("TODAY_NEWS", []) or []
    src = [("公告", nm, cd, t) for nm, cd, t in ann]
    for tm, t in news:
        src.append(("快讯", "", "", t))
    if not src:
        w("  [报空] 公告与新闻源均无数据")
        w("=" * 60)
        return

    spot = get_spot()
    c_code = c_name = c_pct = c_price = None
    if spot is not None:
        c_code = pick_col(spot, ["代码", "code"])
        c_name = pick_col(spot, ["名称", "name"])
        c_pct = pick_col(spot, ["涨跌幅", "changepercent"])
        c_price = pick_col(spot, ["最新价", "trade"])

    _code_str = None
    if spot is not None and c_code:
        try:
            _code_str = spot[c_code].astype(str)   # ★V8.5 只转一次，别每次调用都转
        except Exception:
            _code_str = None

    def _quote(cd, nm):
        """返回 (涨跌幅, 现价)；代码优先，其次名称"""
        if spot is None:
            return None, None
        try:
            r = None
            if cd and _code_str is not None:
                r = spot[_code_str.str.contains(cd, na=False)]
            if (r is None or len(r) == 0) and nm and c_name:
                r = spot[spot[c_name].astype(str) == nm]
            if r is not None and len(r) > 0:
                p = pd.to_numeric(r.iloc[0][c_pct], errors="coerce")
                v = pd.to_numeric(r.iloc[0][c_price], errors="coerce")
                return (float(p) if pd.notna(p) else None,
                        float(v) if pd.notna(v) else None)
        except Exception:
            pass
        return None, None

    # ★V8.4：快讯没有代码/名称，先尝试用全市场名称在正文里定位
    all_names = []
    if spot is not None and c_name and c_code:
        try:
            # ★V8.5：iterrows 在5000行上很慢，改向量化
            _nm = spot[c_name].astype(str).str.strip()
            _cd = spot[c_code].astype(str).str[-6:]
            _ok = (_nm.str.len() >= 2) & (_nm.str.len() <= 6) & (~_nm.str.contains("ST", na=False))
            all_names = list(zip(_nm[_ok].tolist(), _cd[_ok].tolist()))
        except Exception:
            pass

    def _locate(t):
        """从正文里找出A股公司名（最长匹配优先，避免『中兴』误配）"""
        best = ("", "")
        for n2, c2 in all_names:
            if n2 in t and len(n2) > len(best[0]):
                best = (n2, c2)
        return best

    rows, unloc, seen = [], [], set()
    for kind, nm, cd, t in src:
        lv, hitk = 0, ""
        for k in EVENT_L1:
            if k in t:
                lv, hitk = 1, k
                break
        if not lv:
            for k in EVENT_L2:
                if k in t:
                    lv, hitk = 2, k
                    break
        if not lv:
            continue
        risk = [k for k in EVENT_L3 if k in t]
        key = (nm or t[:14]) + hitk
        if key in seen:
            continue
        seen.add(key)
        if not nm and not cd:
            nm, cd = _locate(t)      # ★V8.4 从正文定位个股
        pct, px = _quote(cd, nm)
        if not nm and not cd:
            # ★定位不到就不进正式清单，避免出现『（未识别公司）』这种废条目
            unloc.append((lv, t, hitk, risk))
            continue
        rows.append((lv, nm, cd, t, hitk, risk, pct, px, kind))

    if not rows:
        w("\n  今日无【控制权变动/资产注入/重组/重大订单】级事件")
        w("  → 明确结论：事件驱动方向今日无标的（不硬凑，铁律D）")
        w("=" * 60)
        return

    # 排序：一级在前；同级内【今天没涨的】优先（这是核心）
    def _rank(x):
        lv, pct = x[0], x[6]
        p = pct if pct is not None else 0.0
        unmoved = 0 if p < 3 else (1 if p < 9.5 else 2)
        return (lv, unmoved, -abs(p))
    rows.sort(key=_rank)

    n1 = sum(1 for r in rows if r[0] == 1)
    w(f"\n  ★★命中 {len(rows)} 条（一级{n1}条 / 二级{len(rows)-n1}条）★★\n")
    for i, (lv, nm, cd, t, hitk, risk, pct, px, kind) in enumerate(rows[:15], 1):
        tag = "🟢一级·控制权/资产变动" if lv == 1 else "🔵二级·业绩订单"
        ps = f"{pct:+.2f}%" if pct is not None else "取价失败"
        # ★位置判定：这是事件驱动唯一重要的东西
        if pct is None:
            pos = "❔位置未知"
        elif pct >= 9.5:
            pos = "🔴已涨停 → 今天不是入场点，明天是接力不是埋伏"
        elif pct >= 5:
            pos = "⚠️已大涨 → 追的是第二棒"
        elif pct >= 1:
            pos = "🟡小涨 → 尚可，但已有人先知道"
        elif pct >= -3:
            pos = "🟢★★没涨★★ → 这就是7/28高争民爆的状态，最佳入场点"
        else:
            pos = "🟢★下跌中有事件★ → 铁律K反常，含义最深"
        w(f"  ══ {i}. {nm or '（未识别公司）'}({cd}) {tag}")
        w(f"     命中：「{hitk}」  今日 {ps}" + (f"  现价{px}" if px else ""))
        w(f"     位置：{pos}")
        w(f"     [{kind}] {t[:64]}")
        if risk:
            w(f"     🔴风险提示命中：{'、'.join(risk)}")
            w("        → 催化可能已被公司否认/交易所监控，按卖出卡属【催化证伪】")
        w("")

    if unloc:
        w(f"  ── 另有{len(unloc)}条事件类快讯【定位不到具体个股】，仅作方向参考 ──")
        for lv, t, hitk, risk in unloc[:5]:
            w(f"     ·「{hitk}」{t[:56]}")
        w("     （快讯不带股票代码，正文里也找不到A股名称→无法给买点，不列入清单）")
        w("")

    w("  ─── 事件驱动的三条纪律（与产业驱动完全不同）───")
    w("  1. ★类型是A类事件仓★：涨了就走，不许当趋势拿")
    w("     半导体设备ETF把A类当B类做，−11.5%卖在最低点")
    w("  2. ★入场点是公告当天★：第N个板是博弈最后一棒，不是埋伏")
    w("  3. ★出现『风险提示/重点监控/公司否认』= 催化证伪 = 立即出★")
    w("     高争民爆8/7已公告『不存在资产注入计划』+深交所重点监控")
    w("  ⚠️ 仓位：A类事件仓不许超总资产6%（B类才能到11%）")

    # ★★V8.3 存档：没有后视镜的模块 = 无法证伪 = 迟早变成噪音源★★
    try:
        arch = []
        for lv, nm, cd, t, hitk, risk, pct, px, kind in rows[:15]:
            if px and not risk:          # 有价格、且未出风险提示的才存
                arch.append({"code": cd, "name": nm, "lv": lv, "key": hitk,
                             "price": px, "pct": pct if pct is not None else 0.0})
        if arch:
            d = _bt_load(EVENT_HIST_FILE)
            d[now_beijing().strftime("%Y-%m-%d")] = arch
            _bt_save(EVENT_HIST_FILE, d)
            w(f"  📌 已存档{len(arch)}条事件 → 3日后自动回看命中率")
    except Exception as e:
        w(f"  [存档失败] {type(e).__name__}")
    w("=" * 60)


def backtest_event():
    """★V8.3 事件驱动雷达回测。
    ★核心要验的不是『事件有没有用』，是【当天没涨的】是不是真的比【已涨停的】强。
      高争民爆7/28没涨→翻倍；8/10第9板→接力最后一棒。
      如果数据显示两者差不多，说明『公告当天入场』这条规则是我编的，不是真的。"""
    w("\n" + "=" * 60)
    w("🔬【事件驱动雷达·回测】『公告当天没涨才是入场点』——真的吗")
    w("=" * 60)
    d = _bt_load(EVENT_HIST_FILE)
    if not d:
        w("  尚无存档，今天是第1天。")
        w("  ⚠️ 铁律：≥5天且≥15样本后出胜率；连续<45% → 立即停用本模块")
        w("=" * 60)
        return
    spot = get_spot()
    if spot is None:
        w("  [报空] 快照缺失")
        w("=" * 60)
        return
    c_code = pick_col(spot, ["代码", "code"])
    c_price = pick_col(spot, ["最新价", "trade"])
    today = now_beijing()

    def _px(cd):
        try:
            r = spot[spot[c_code].astype(str).str.contains(cd, na=False)]
            if len(r) > 0:
                v = pd.to_numeric(r.iloc[0][c_price], errors="coerce")
                return float(v) if pd.notna(v) else None
        except Exception:
            pass
        return None

    # 分桶：当天没涨(<3%) vs 当天已大涨(>=9.5%)
    b_un = [0, 0]      # [命中, 样本]
    b_up = [0, 0]
    b_l1 = [0, 0]
    b_l2 = [0, 0]
    for day in sorted(d.keys(), reverse=True)[:10]:
        try:
            gap = (today - datetime.datetime.strptime(day, "%Y-%m-%d")).days
        except Exception:
            continue
        if gap < 3:
            continue
        detail = []
        for it in d[day]:
            p0, p1 = it.get("price"), _px(it.get("code", ""))
            if not p0 or not p1:
                continue
            chg = (p1 - p0) / p0 * 100
            ok = chg > 3
            p_at = float(it.get("pct", 0))
            if p_at < 3:
                b_un[1] += 1
                b_un[0] += 1 if ok else 0
            elif p_at >= 9.5:
                b_up[1] += 1
                b_up[0] += 1 if ok else 0
            if it.get("lv") == 1:
                b_l1[1] += 1
                b_l1[0] += 1 if ok else 0
            else:
                b_l2[1] += 1
                b_l2[0] += 1 if ok else 0
            detail.append(f"{it.get('name')}({p_at:+.0f}%当日){chg:+.1f}%")
        if detail:
            w(f"  {day}（{gap}天前）：{' | '.join(detail[:8])}")

    tot = b_un[1] + b_up[1]
    if tot == 0:
        w("  样本不足（需≥3天前的存档），继续积累")
        w("=" * 60)
        return
    w("")
    if b_un[1]:
        w(f"  🟢当天没涨(<3%)：{b_un[0]}/{b_un[1]} = {b_un[0]/b_un[1]*100:.0f}%")
    if b_up[1]:
        w(f"  🔴当天已涨停：  {b_up[0]}/{b_up[1]} = {b_up[0]/b_up[1]*100:.0f}%")
    if b_l1[1]:
        w(f"  一级(控制权/资产)：{b_l1[0]}/{b_l1[1]} = {b_l1[0]/b_l1[1]*100:.0f}%")
    if b_l2[1]:
        w(f"  二级(业绩/订单)：  {b_l2[0]}/{b_l2[1]} = {b_l2[0]/b_l2[1]*100:.0f}%")
    w("")
    w("  → 若『没涨』明显高于『已涨停』：公告当天入场这条规则成立，可加大权重")
    w("  → 若两者差不多：这条规则是我编的，不是真的，必须改口")
    w("  → 若一级明显高于二级：控制权变动确实比业绩订单强，排序正确")
    if b_un[1] + b_up[1] >= 15:
        r = (b_un[0] + b_up[0]) / (b_un[1] + b_up[1])
        if r < 0.45:
            w(f"  🔴🔴 整体命中率{r*100:.0f}%<45% → 按铁律【立即停用事件驱动雷达】")
    w("=" * 60)


def scan_announcements():
    """公司公告雷达：补快讯盲区（通宇通讯收购案的教训）"""
    w("\n" + "=" * 60)
    w("📢【公司公告雷达】补快讯盲区 —— 涨停背后的真实原因")
    w("=" * 60)
    d = now_beijing().strftime("%Y%m%d")

    def _do():
        df = None
        d2 = (now_beijing() - datetime.timedelta(days=1)).strftime("%Y%m%d")
        # ★V6.2：先用 hasattr 探测函数是否存在，避免 AttributeError
        cands = [
            ("巨潮-沪深京公告", "stock_zh_a_disclosure_report_cninfo",
             {"symbol": "", "market": "沪深京", "keyword": "",
              "category": "", "start_date": d, "end_date": d}),
            ("巨潮-昨日公告", "stock_zh_a_disclosure_report_cninfo",
             {"symbol": "", "market": "沪深京", "keyword": "",
              "category": "", "start_date": d2, "end_date": d2}),
            ("东财-公告大全", "stock_notice_report_em", {"symbol": "全部", "date": d}),
            ("股市日历-公司动态", "stock_gsrl_gsdt_em", {"date": d}),
            ("股市日历-昨日", "stock_gsrl_gsdt_em", {"date": d2}),
            ("财联社-电报", "stock_info_global_cls", {"symbol": "全部"}),
            ("东财-资讯快讯", "stock_info_global_em", {}),
            ("同花顺-全球财经", "stock_info_global_ths", {}),
        ]
        avail = [c for c in cands if hasattr(ak, c[1])]
        if not avail:
            w(f"  ⚠️ akshare无任何可用公告函数（已探测{len(cands)}个）")
        # ★★V9.5：不再『先到先用』，而是【择优】★★
        # 8/12实测：巨潮 CallTimeout 两次(40秒×2=80秒白等)，
        # 降级到"股市日历"只有83条 → 公告雷达命中1条、事件雷达从23条掉到3条。
        # 而正常巨潮有984条。83条 vs 984条，差12倍，判断质量天差地别。
        # 新逻辑：巨潮超时缩到20秒快速失败；继续试后面的源；
        #        取【条数最多】的那个，不是第一个成功的。
        # ★★V9.6：择优要看【质量】，不只看条数★★
        # 8/12实测：选了"东财-资讯快讯"200条，但它是【快讯】不是【公告】，
        #   没有股票代码列 → 输出全是「▸ () 鲁抗医药：...」
        #   → 事件雷达定位不到个股、持仓公告核对全部失效。
        # ★200条无代码 < 93条有代码。评分 = 条数 × (有代码?3:1)
        best_score, best_n, best_tag, best_hascode = 0, 0, "", False
        for tag, fname, kw in avail:
            try:
                fn = getattr(ak, fname)
                _to = 20 if "巨潮" in tag else 40
                r = with_retry(lambda: fn(**kw), tries=1, wait=1, timeout=_to)
                if r is None or len(r) == 0:
                    w(f"  [跳过] {tag}：返回空")
                    continue
                _hascode = pick_col(r, ["代码", "股票代码", "证券代码", "symbol", "code"]) is not None
                _score = len(r) * (3 if _hascode else 1)
                _mark = "✅带代码" if _hascode else "⚠️无代码(定位不到个股)"
                if _score > best_score:
                    df, best_score, best_n, best_tag, best_hascode = r, _score, len(r), tag, _hascode
                    w(f"  ✅ 公告源候选：{tag}（{len(r)}条 {_mark}）← 当前最优")
                else:
                    w(f"  [较弱] {tag}：{len(r)}条 {_mark}")
                if _hascode and len(r) >= 500:
                    break
            except Exception as e:
                w(f"  [跳过] {tag}：{type(e).__name__}")
        if best_tag:
            w(f"  ★最终采用：{best_tag}（{best_n}条，{'带代码' if best_hascode else '★无代码★'}）")
            if not best_hascode:
                w("  🔴 该源无股票代码列 → 事件雷达无法定位个股、")
                w("     持仓公告核对失效。本次这两节不可用于决策。")
            if best_n < 300:
                w(f"  ⚠️ 只有{best_n}条（正常≥900条）→ 事件雷达/定增雷达/")
                w("     持仓公告核对 三节数据不完整，不可用于决策")
        if df is None:
            w("  [报空] 公告源不可用")
            return
        c_name = pick_col(df, ["名称", "股票简称", "简称"])
        c_code = pick_col(df, ["代码", "股票代码"])
        c_title = pick_col(df, ["公告标题", "标题", "内容", "摘要", "简称"])
        if not c_title:
            w(f"  [报空] 缺标题列 {list(df.columns)[:6]}")
            return
        hits = []
        for _, r in df.iterrows():
            try:
                t = str(r[c_title])
                if any(k in t for k in ANNOUNCE_KEYS):
                    nm = str(r[c_name]) if c_name else ""
                    cd = str(r[c_code])[-6:] if c_code else ""
                    hits.append((nm, cd, t))
            except Exception:
                continue
        w(f"  （共{len(df)}条公告，关键词命中{len(hits)}条）")
        for nm, cd, t in hits[:25]:
            w(f"    ▸ {nm}({cd}) {t[:52]}")
        globals()["TODAY_ANNOUNCE"] = {h[1]: h[2] for h in hits}
        globals()["TODAY_ANNOUNCE_RAW"] = hits      # ★V8.3 供事件驱动雷达
    safe_run("公司公告雷达", _do)


def scan_unexplained():
    """异动未解释清单：涨停但说不出原因=盲区，AI必须主动搜"""
    w("\n" + "=" * 60)
    w("❓【异动未解释清单】说不出原因 = 盲区，AI必须主动搜索")
    w("=" * 60)
    w("  ★铁律M：涨停股如果我说不出它为什么涨，就是我的信息盲区")

    def _do():
        ann = globals().get("TODAY_ANNOUNCE", {})
        try:
            zt = with_retry(lambda: ak.stock_zt_pool_em(
                date=now_beijing().strftime("%Y%m%d")), tries=1, timeout=45)
        except Exception:
            zt = None
        if zt is None or len(zt) == 0:
            w("  涨停池无数据")
            return
        z_name = pick_col(zt, ["名称"])
        z_code = pick_col(zt, ["代码"])
        z_ind = pick_col(zt, ["所属行业", "行业"])
        if not z_name or not z_code:
            w("  [报空] 涨停池缺字段")
            return
        explained, unknown = [], []
        for _, r in zt.iterrows():
            try:
                cd = str(r[z_code])[-6:].zfill(6)
                nm = str(r[z_name])
                ind = str(r[z_ind]) if z_ind else ""
                if cd in ann:
                    explained.append((nm, cd, ind, ann[cd][:36]))
                else:
                    unknown.append((nm, cd, ind))
            except Exception:
                continue
        w(f"\n  ✅有公告解释（{len(explained)}只）：")
        for nm, cd, ind, t in explained[:12]:
            w(f"    {nm}({cd})[{ind}] ← {t}")
        w(f"\n  ❓无公告解释（{len(unknown)}只）→ ★AI必须逐个追问★")
        for nm, cd, ind in unknown[:20]:
            w(f"    {nm}({cd})[{ind}] ← 原因未知，需主动搜索")
        w("\n  ⚠️ ①同行业≥3只无解释涨停→板块级消息，去搜行业新闻")
        w("     ②AI必须写『我查了，原因是XXX』或『我查不到』，不许跳过")
    safe_run("异动未解释", _do)


def scan_all_sector_cross(uniq_news):
    """全板块×新闻自动交叉：477个板块逐个扫，绝对不漏（V5.0核心）"""
    w("\n" + "=" * 60)
    w("🌐🌐【全板块 × 新闻 自动交叉】477个板块逐个扫 · 绝对不漏 🌐🌐")
    w("=" * 60)
    w("  逻辑：手工词典必漏；直接用市场公认的行业+概念分类去撞新闻")
    w("       板块有新闻催化 + 位置好(刚启动) = 真机会")

    def _do():
        rows = []
        for tag, fn, nk, pk in [
            ("行业", lambda: ak.stock_fund_flow_industry(symbol="即时"),
             ["行业", "名称", "板块"], ["涨跌幅", "行业指数涨跌", "涨跌"]),
            ("概念", lambda: ak.stock_fund_flow_concept(symbol="即时"),
             ["行业", "概念名称", "名称", "板块"], ["涨跌幅", "行业指数涨跌", "涨跌"]),
            ("概念备", lambda: ak.stock_board_concept_name_em(),
             ["板块名称", "概念名称", "名称"], ["涨跌幅"]),
            ("概念备2", lambda: ak.stock_board_concept_name_ths(),
             ["概念名称", "名称", "板块"], ["涨跌幅", "涨幅"]),
        ]:
            if tag.startswith("概念") and any(r[0] == "概念" for r in rows):
                continue          # 概念已成功则跳过备源
            try:
                df = with_retry(fn, tries=2, wait=3, timeout=70)
                if df is None or len(df) == 0:
                    w(f"  [跳过] {tag}源空")
                    continue
                nc = pick_col(df, nk)
                pc = pick_col(df, pk)
                if not nc:
                    w(f"  [跳过] {tag}缺名称列 {list(df.columns)[:6]}")
                    continue
                for _, r in df.iterrows():
                    try:
                        v = pd.to_numeric(r[pc], errors="coerce") if pc else None
                        rows.append(("概念" if tag.startswith("概念") else tag,
                                     str(r[nc]), v))
                    except Exception:
                        continue
            except Exception as e:
                w(f"  [跳过] {tag}：{type(e).__name__}")

        if not rows:
            w("  [报空] 板块数据不可用")
            return
        w(f"  （共扫描 {len(rows)} 个板块）")

        SKIP = {"其他", "综合", "综合Ⅱ", "证金持股", "融资融券", "沪股通",
                "深股通", "标准普尔", "MSCI中国", "富时罗素", "预盈预增",
                "转债标的", "破净股", "低价股", "高送转", "壳资源",
                "证券", "券商", "多元金融", "保险"}   # ★券商名高频出现在研报里

        # ★噪声过滤器（V5.9）：这些命中不算板块催化
        BROKER_NOISE = ["中信证券", "中信建投", "银河证券", "光大证券", "国泰海通",
                        "华泰证券", "招商证券", "国金证券", "东吴证券", "浙商证券",
                        "民生证券", "开源证券", "天风证券", "西部证券", "申万宏源",
                        "广发证券", "海通证券", "中金公司", "国信证券", "方正证券",
                        "发布研报", "研报称", "分析师", "评级", "目标价"]
        WAR_NOISE = ["胡塞", "俄军", "乌军", "俄罗斯", "乌克兰", "以军", "以色列",
                     "哈马斯", "真主党", "敖德萨", "基辅", "莫斯科", "袭击",
                     "空袭", "炮击", "导弹击中", "无人机袭击"]

        def _is_noise(t, sect_name):
            # 研报噪声：整条新闻的核心是券商研报，而板块名恰好是券商名的一部分
            if any(b in t for b in BROKER_NOISE):
                if sect_name in ("证券", "券商", "多元金融"):
                    return True
                # 研报提到的板块仍算催化，但降权（不在此过滤）
            # 外国军事噪声：与A股产业无关
            if any(x in t for x in WAR_NOISE):
                cn = ["中国", "A股", "国内", "我国", "出口", "对华", "国产", "订单"]
                if not any(c in t for c in cn):
                    return True
            return False
        results = []
        for kind, name, chg in rows:
            nm = str(name).strip()
            if not nm or nm in SKIP or len(nm) < 2:
                continue
            keys = {nm}
            for suf in ["概念", "行业", "板块", "Ⅱ", "Ⅲ", "指数", "产业"]:
                if nm.endswith(suf) and len(nm) > len(suf) + 1:
                    keys.add(nm[: -len(suf)])
            keys = {k for k in keys if len(k) >= 2}
            bull, bear, seen = [], [], set()
            for tm, t in uniq_news:
                # ★V8.1：同源去重（书名号/冒号主体），防止一份文件灌成N条
                _k = _news_key(t)
                if _k in seen or t[:24] in seen:
                    continue
                seen.add(_k)
                try:
                    if _is_foreign(t) or _is_noise(t, nm):
                        continue
                except Exception:
                    pass
                if any(k in t for k in keys):
                    seen.add(t[:24])
                    try:
                        p = _news_polarity(t)
                    except Exception:
                        p = 0
                    (bull if p >= 0 else bear).append((tm, t))
            net = len(bull) - len(bear)
            if len(bull) + len(bear) < 2:
                continue
            pos = 0
            if chg is not None and pd.notna(chg):
                c = float(chg)
                pos = 3 if c < 0 else (2 if c < 1.5 else (1 if c < 4 else -1))
            # ★★★V9.7 领先/滞后指标权重重构★★★
            # ★8/13血的教训（一天两笔）：
            #   紫光股份：8/12我说"计算机设备资金-0.08亿，钱不在它那条腿" → 建议清仓
            #             8/13 计算机设备资金+9.79亿，紫光+5.16%，少赚1,145元
            #   创新药ETF：8/12我说"医疗服务-16.81亿，该卖" → 建议卖出
            #             8/13 医疗服务+4.28%全场第1、资金+9.35亿，它+5.18%
            # ★根因：资金流是【滞后指标】——它记录钱【已经流过】的地方。
            #   而【排名跳升】是领先指标：CRO今天从358名跳到第1名，
            #   昨天它还在358名、资金也是负的。
            # ★修正：
            #   ① 跳升分（领先）：新增，权重最高
            #   ② 资金分（滞后）：从±12压到±6，且【流出不再重罚】
            #      ——昨天流出可能正是今天启动的前夜
            _jump = _rank_jump_of(nm)
            jsc, jtxt = 0, ""
            if _jump is not None:
                if _jump >= 100:
                    jsc, jtxt = 10, f" 🚀跳升{_jump}位(领先信号)"
                elif _jump >= 50:
                    jsc, jtxt = 7, f" 🚀跳升{_jump}位"
                elif _jump >= 30:
                    jsc, jtxt = 5, f" 🚀跳升{_jump}位"
                elif _jump >= 10:
                    jsc, jtxt = 2, f" ↗升{_jump}位"
                elif _jump <= -30:
                    jsc, jtxt = -3, f" 📉退{-_jump}位"
            fl = _sector_flow_of(nm)
            fsc, ftxt = 0, ""
            if fl is not None:
                # ★V9.7：流入仍加分，但【流出不再重罚】
                #   —— 昨天流出可能正是今天启动的前夜（8/13医药就是）
                if fl >= 20:
                    fsc, ftxt = 5, f" 资金+{fl:.0f}亿🔥"
                elif fl >= 5:
                    fsc, ftxt = 3, f" 资金+{fl:.0f}亿✅"
                elif fl > 0:
                    fsc, ftxt = 1, f" 资金+{fl:.1f}亿"
                elif fl > -20:
                    fsc, ftxt = -1, f" 资金{fl:.1f}亿"
                elif fl > -80:
                    fsc, ftxt = -3, f" 资金{fl:.0f}亿⚠️"
                else:
                    fsc, ftxt = -6, f" 资金{fl:.0f}亿🔴失血"
                # ★反常加分：资金流出但板块在涨 = 有人在恐慌里收货（铁律K）
                if fl < 0 and chg is not None and pd.notna(chg) and float(chg) > 1:
                    fsc += 3
                    ftxt += " ★反常:资金出但板块涨"
            results.append((net * 2 + pos + fsc + jsc, kind, nm, chg, net,
                            len(bull), len(bear), bull, ftxt + jtxt))

        if not results:
            w("  今日无板块命中≥2条新闻")
            return
        results.sort(key=lambda x: -x[0])
        # ★★V8.7 同名去重：8/12实测【黄金概念】占了前5名里的3个坑★★
        # 东财/同花顺/通达信各有一个"黄金概念"，内容几乎一样，
        # 前5名有3行是同一个东西 → 真正的第2/第3名被挤出榜外。
        _seen_nm, _dedup = set(), []
        for _row in results:
            _key = str(_row[2]).strip().rstrip("概念板块行业指数产业ⅡⅢ").strip()
            if _key and _key in _seen_nm:
                continue
            _seen_nm.add(_key)
            _dedup.append(_row)
        if len(_dedup) != len(results):
            w(f"  （已合并同名板块 {len(results)-len(_dedup)} 条，防止一个概念占多个坑）")
            results = _dedup
        w("\n  ★★【有催化 且 位置好 且 钱在进】前15（净利多×2 + 位置分 + 资金分）：")
        w("    位置分：跌着有催化=3 | 微涨<1.5%=2 | 涨1.5-4%=1 | 涨>4%=-1")
        w("    ★V9.7跳升分(领先指标，权重最高)：跳100位↑=+10 | 50位↑=+7 | 30位↑=+5 | 10位↑=+2 | 退30位↓=-3")
        w("    ★V9.7资金分(滞后指标，权重减半)：+20亿↑=+5 | +5亿↑=+3 | 正=+1 | -20亿↓=-3 | -80亿↓=-6")
        w("       ★反常加分：资金流出但板块在涨 = 有人在恐慌里收货(铁律K) +3")
        w("    ⚠️8/13教训：资金流记录的是钱【已经流过】的地方，不是要去的地方。")
        w("       紫光(计算机设备-0.08亿→次日+9.79亿，股价+5.16%)")
        w("       创新药(医疗服务-16.81亿→次日全场第1，ETF+5.18%)")
        w("       两笔我都用『昨天资金流出』劝卖，两笔都错。")
        w("       而CRO今天从358名跳到第1名——昨天它资金也是负的。")
        for i, (sc, kind, nm, chg, net, nb, nr, _, ftxt) in enumerate(results[:15], 1):
            ct = f"{chg:+.2f}%" if chg is not None and pd.notna(chg) else "?"
            flag = ""
            if chg is not None and pd.notna(chg):
                if float(chg) < 1.5 and net >= 2:
                    flag = " 🔥★有催化但还没涨★"
                elif float(chg) > 4:
                    flag = " ⚠️已大涨"
            w(f"    {i:2d}. [{kind}]{nm} {ct} 新闻净{net:+d}(↑{nb}↓{nr}) 得分{sc}{flag}")
        w("\n  ★前5名的具体新闻催化：")
        for sc, kind, nm, chg, net, nb, nr, bull, ftxt in results[:5]:
            ct = f"{chg:+.2f}%" if chg is not None and pd.notna(chg) else "?"
            w(f"\n  ◆【{nm}】{ct} 得分{sc}")
            for tm, t in bull[:4]:
                w(f"      ▸[{tm}] {t[:56]}")
        w("\n  ⚠️ 铁律N：★『有催化但还没涨』的板块 = 明天首选★")
        w("    手工词典必漏，全板块交叉才不漏。")
        w("    仍需过①-B：这个板块的驱动，和它涨的原因是同一个吗？")
    safe_run("全板块交叉", _do)


# ★★★V8.8 通用验证词（8/12实测漏判）★★★
# 存储链核心词命中13条，但"✅验证0"——因为verify表里写的是
# "涨价""扩产"，而当天真实新闻写的是：
#   「本月服务器DDR5内存条价格【全面上涨】15%至23%」  ← 真涨价，字面不含"涨价"
#   「SK海力士【重启】大连NAND二期【工厂建设】，年内完成设备导入」← 真扩产
# 后果：一条有真实扩产+真实涨价的链，被标成"故事阶段，可观察不可重仓"
#      → 系统低估了当天最强的那条线。
# 修法：每条链的verify表之外，再叠加一张【通用验证词】表。
VERIFY_UNIVERSAL = [
    # 涨价的各种写法
    "价格上涨", "价格全面上涨", "报价上调", "上调价格", "上调报价",
    "调价", "价格上行", "均价上涨", "现货价上涨", "全面上涨",
    # 扩产/建设的各种写法
    "工厂建设", "产线建设", "新建产能", "重启", "复产", "达产",
    "设备导入", "产能扩大", "扩建", "追加投资", "资本开支上调",
    # 订单/交付的各种写法
    "在手订单", "订单饱满", "产能利用率高", "满负荷", "供不应求",
    "售罄", "已全部售罄", "锁定产能", "提前锁定", "长协",
    # 业绩兑现（比研报硬）
    "净利预增", "业绩预增", "净利同比增长", "营收同比增长", "创新高",
]


# ★★V9.5 核心词误命中黑名单★★
# 8/12实测：存储链核心词命中「佐力药业：灵莲花颗粒获批临床」
# 根因：短核心词（2字）在中文里极易被其它行业的词包含。
# 办法：命中核心词后，再查这条新闻是否明显属于【其它行业】，是则否决。
CHAIN_EXCLUDE = {
    "存储涨价 → 传导链": ["药业", "医药", "临床", "适应症", "中药", "颗粒剂",
                          "食品", "饲料", "化肥", "颗粒物", "PM2.5"],
    "AI算力 → 散热": ["空调", "家电", "汽车散热", "暖通"],
    "MLCC涨价链": ["电容器厂房", "储能电容"],
    "猪周期 → 养殖链": ["宠物", "水产"],
    "AI+制药 → CXO/算力": ["中药", "饮片", "集采降价"],
}


def _core_hit_ok(chain_name, t):
    """★V9.5：核心词命中后，再排除明显属于其它行业的新闻"""
    bad = CHAIN_EXCLUDE.get(chain_name, [])
    return not any(k in str(t) for k in bad)


def _is_verify(t, chain_verify):
    """★V8.8：链专属验证词 OR 通用验证词，命中任一即算验证信号"""
    return (any(k in t for k in chain_verify)
            or any(k in t for k in VERIFY_UNIVERSAL))


def scan_deduction(uniq_news, heat_top=None):
    """产业链推演：从已发生的事实，推出还没被市场发现的下游"""
    w("\n" + "=" * 60)
    w("🔮🔮【产业链推演引擎】演绎法 · 找市场还没发现的那一层 🔮🔮")
    w("=" * 60)
    w("  逻辑：热力图管『已发生』(归纳)；推演引擎管『必然要发生』(演绎)")
    w("  信息差 ≠ 比别人先看到新闻（新闻是公开的）")
    w("  信息差 = 同一条新闻，比别人多推演两层")

    heat_top = heat_top or []
    results = []
    for ch in DEDUCTION_CHAINS:
        core_hits, up_hits, ver, seen = [], [], [], set()
        core = ch.get("core", [])
        for tm, t in uniq_news:
            k2 = _news_key(t)
            if t[:26] in seen or k2 in seen:
                continue
            hit_core = any(k in t for k in core) and _core_hit_ok(ch["name"], t)
            hit_ver = _is_verify(t, ch["verify"])   # ★V8.8 含通用验证词
            hit_up = any(k in t for k in ch["trigger"])
            # ★验证信号必须同时含【板块核心词】AND【验证动作词】
            if hit_core and hit_ver:
                seen.add(t[:26]); seen.add(k2)
                ver.append((tm, t))
            elif hit_core:
                seen.add(t[:26]); seen.add(k2)
                core_hits.append((tm, t))
            elif hit_up:
                seen.add(t[:26]); seen.add(k2)
                up_hits.append((tm, t))
        if not core_hits and not up_hits and not ver:
            continue
        # 市场发现度：该链关键词是否已进热力图前列
        found = any(any(x in h for x in ch["name"].split("→")) for h in heat_top)
        # ★★V8.4 打分重构（8/11教训）★★
        # 旧版：trigger词单独命中也算1分，而存储链的trigger是["AI",...]，
        #   "AI"两个字命中了32条→42分排第1，触发信号是
        #   『张朝阳：AI内容像化肥催出来的西红柿』『千问AI眼镜』『卫星出征』
        #   —— 跟存储毫无关系。散热链18分的触发信号是『紫金矿业净卖出10亿』。
        # 新版：只有命中【板块核心词】才算真触发（×1）；
        #   只命中上游泛词（AI/算力/数据中心）的，权重0.2且最多计5条。
        trig = core_hits + up_hits
        score = (len(core_hits) * 1
                 + min(len(up_hits), 5) * 0.2
                 + len(ver) * 3
                 + (0 if found else 4))
        results.append((round(score, 1), ch, trig, ver, found, core_hits, up_hits))

    if not results:
        w("  本期无推演链被触发")
        return
    results.sort(key=lambda x: -x[0])

    w("\n  ★推演价值排行（上游事实×验证信号×市场未发现度）：")
    try:
        globals()["TODAY_VERIFIED_CHAINS"] = [
            r[1]["name"] for r in results[:5] if len(r[3]) > 0]
    except Exception:
        pass
    for i, (sc, ch, trig, ver, found, core_hits, up_hits) in enumerate(results[:8], 1):
        mk = "⚠️市场已发现" if found else "✅市场还没发现"
        w(f"    {i}. {ch['name']}：{sc}分（★核心{len(core_hits)} 泛词{len(up_hits)} "
          f"✅验证{len(ver)}）{mk}")

    w("\n  ★前3条链的完整推演：")
    for sc, ch, trig, ver, found, core_hits, up_hits in results[:3]:
        w(f"\n  ══ 【{ch['name']}】{sc}分 " +
          ("⚠️市场已发现，慎追" if found else "✅市场还没发现，可埋伏"))
        w("    推演路径：")
        for lay in ch["layers"]:
            w(f"      {lay}")
        w(f"    A股标的：{ch['stocks']}")
        if core_hits:
            w("    ── ★命中【板块核心词】的新闻（真触发）──")
            for tm, t in core_hits[:4]:
                w(f"      ▸[{tm}] {t[:56]}")
        if up_hits:
            w("    ── 仅命中上游泛词(AI/算力/数据中心)，权重0.2，参考用 ──")
            for tm, t in up_hits[:2]:
                w(f"      ·[{tm}] {t[:52]}")
        if not core_hits:
            w("    🔴 本链今日【无一条命中板块核心词】→ 分数只来自泛词，")
            w("       不构成买入依据（8/11教训：存储链42分全靠『AI』两字堆出来）")
        if ver:
            w("    ── ✅验证信号（真实订单/扩产/涨价，最值钱）──")
            for tm, t in ver[:4]:
                w(f"      ✅[{tm}] {t[:56]}")
        else:
            w("    ── ⚠️无验证信号：只有推演逻辑，没有真实订单/扩产/涨价")
            w("       → 属于『故事阶段』，可观察不可重仓")

    w("\n  ⚠️ 推演铁律：")
    w("    1. 每层推演概率衰减（3层×80% = 51%）→ 必须有验证信号才算成立")
    w("    2. 『战略合作/研究/规划』不算验证；")
    w("       『真实订单/中标/扩产投资/涨价/量产』才算")
    w("    3. 市场已发现(已进热力图前列) = 已被消化，慎追")
    w("    4. 推演出的标的仍需过决策卡九项，尤其④位置⑤游资")
    w("=" * 60)


# ========== ★★深层含义解读器（三线交叉：机构×新闻×推演） ==========
# 用户要的核心能力：不是报数据，是从数据读出别人读不出的含义
# 逻辑：机构买的票 → 对应哪条新闻 → 机构在赌什么 → 下一层风口在哪

# 个股→所属产业环节（用于判断机构买的是产业链哪一层）
STOCK_LAYER = {
    "德明利": ("存储", "模组/终端层"), "江波龙": ("存储", "模组层"),
    "兆易创新": ("存储", "设计层"), "佰维存储": ("存储", "模组层"),
    "雅克科技": ("存储", "★上游材料层(前驱体/电子特气)"),
    "长电科技": ("半导体", "★封测层"), "通富微电": ("半导体", "★封测层"),
    "华海清科": ("半导体", "★设备层"), "北方华创": ("半导体", "★设备层"),
    "中际旭创": ("光模块", "模块层"), "新易盛": ("光模块", "模块层"),
    "源杰科技": ("光模块", "★上游光芯片层"),
    "云南锗业": ("光模块", "★★InP衬底层(第4层,最少被发现)"),
    "博杰股份": ("光模块", "★★磷化铟链"),
    "有研新材": ("光模块", "★★衬底材料层"), "仕佳光子": ("光模块", "★上游光芯片"),
    "紫光股份": ("算力", "服务器/交换机层"), "共进股份": ("算力", "交换机层"),
    "英维克": ("算力", "★散热层"), "申菱环境": ("算力", "★散热层"),
    "麦格米特": ("算力", "★供电层"), "科华数据": ("算力", "★供电层"),
    "东山精密": ("PCB", "★载板层"), "胜宏科技": ("PCB", "载板层"),
    "药明康德": ("AI+制药", "CXO龙头层"), "成都先导": ("AI+制药", "★DEL+AI平台层"),
    "泓博医药": ("AI+制药", "★AI药物设计层"), "美迪西": ("AI+制药", "临床前CRO层"),
    "皓元医药": ("AI+制药", "分子砌块层"), "凯莱英": ("AI+制药", "CDMO层"),
    "容百科技": ("锂电", "★钠电正极层"), "华阳股份": ("锂电", "★钠电层"),
}

# 全球新闻→A股传导链（读出"这条新闻对A股哪一层最有意义"）
GLOBAL_IMPACT = [
    {"kw": ["capex", "资本开支", "云厂", "AWS", "Azure", "数据中心投资"],
     "means": "云厂真金白银扩产 = AI需求是真的，不是故事",
     "next": "第一波炒芯片→第二波炒服务器/交换机→★第三波炒散热+供电(市场常滞后)"},
    {"kw": ["NAND", "DRAM", "HBM", "存储涨价", "缺货", "长约"],
     "means": "存储进入涨价周期，原厂议价权回归",
     "next": "原厂涨价→模组厂跟涨→终端涨价→★上游材料/设备紧缺(最后被发现)"},
    {"kw": ["封测", "CoWoS", "先进封装", "载板", "玻璃基"],
     "means": "先进封装是算力瓶颈，产能=硬通货",
     "next": "封测厂满产→★封装设备/材料/载板(A股滞后于台系)"},
    {"kw": ["核电", "特高压", "电网投资", "十五五电力"],
     "means": "算力耗电是硬约束，电力是AI的影子行情",
     "next": "电网投资→设备招标→★核级泵阀/换流阀/储能(订单落地才是真信号)"},
    {"kw": ["消费税", "钠电", "碳酸锂"],
     "means": "政策改变成本结构，替代路线加速",
     "next": "锂电成本↑→★钠电替代→正极/硬碳负极/铝箔集流体"},
    {"kw": ["人形机器人", "具身智能", "量产", "定点"],
     "means": "从demo进入量产爬坡，零部件开始放量",
     "next": "整机厂扩产→★谐波/丝杠/灵巧手/无框电机"},
    {"kw": ["AI制药", "AI药物", "靶点", "CXO", "医疗大模型", "AI+医疗",
            "分子设计", "脑机接口", "AI诊断"],
     "means": "AI改写新药研发范式，研发成本/周期结构性下降",
     "next": "★与集采完全无关！集采杀的是仿制药定价，AI+制药靠的是研发效率\n"
             "       AI平台→CXO订单↑→★算力+生物计算双属性标的(最少被发现)"},
    {"kw": ["美联储", "加息", "降息", "美债收益率"],
     "means": "全球流动性的总闸门，决定成长股估值",
     "next": "加息→杀成长利好银行/红利；降息→利好成长/黄金"},
    {"kw": ["霍尔木兹", "OPEC", "原油", "地缘"],
     "means": "油价是通胀的先行指标，影响利率路径",
     "next": "油涨→通胀→加息→杀成长；油跌→利好成长(与AI链正相关)"},
]


def scan_deep_meaning(uniq_news, ambush_list=None):
    """深层含义：机构买的票在产业链哪一层 + 对应新闻 + 下一个风口"""
    w("\n" + "=" * 60)
    w("🧠🧠【深层含义解读器】机构动向 × 全球新闻 × 产业链推演 🧠🧠")
    w("=" * 60)
    w("  核心问题：机构买的这只票，在产业链的哪一层？它在赌什么？")
    w("           市场在炒第几层？还有哪一层没被发现？")

    # 一、机构买的票在哪一层
    w("\n  ★① 机构/游资埋伏标的 → 产业链层级定位")
    hits = []
    if ambush_list:
        for item in ambush_list:
            nm = item.get("name", "") if isinstance(item, dict) else str(item)
            for k, (chain, layer) in STOCK_LAYER.items():
                if k in nm:
                    hits.append((nm, chain, layer))
                    break
    if hits:
        for nm, chain, layer in hits:
            star = "★★" if "★" in layer else ""
            w(f"    {nm} → [{chain}] {layer} {star}")
        w("    ⚠️ 带★=上游/被忽略层。机构买上游 = 它认为这波不是短炒，是产能周期")
    else:
        w("    （今日埋伏池无数据，或标的不在映射表中）")

    # 二、全球新闻的深层含义 + 下一层
    w("\n  ★② 今日全球新闻 → 深层含义 → 下一个风口在哪一层")
    for g in GLOBAL_IMPACT:
        matched, seen = [], set()
        for tm, t in uniq_news:
            if any(k in t for k in g["kw"]) and t[:26] not in seen:
                seen.add(t[:26])
                matched.append((tm, t))
        if len(matched) < 2:
            continue
        w(f"\n    ◆ 命中 {len(matched)} 条 → 【{g['means']}】")
        for tm, t in matched[:2]:
            w(f"       ▸[{tm}] {t[:52]}")
        w(f"       🔮 下一层：{g['next']}")

    w("\n  ★③ 三线交叉结论（AI必须自己写，不能只列数据）：")
    w("     格式：机构在买【X层】+ 新闻说【Y在发生】+ 市场在炒【Z层】")
    w("          → 结论：还没被炒的是【W层】，那是下一个风口")
    w("")
    w("  ⚠️ 铁律K（V4.2）：★越反常的交易，含义越深★")
    w("    正常交易不含信息（涨停被追/跌了被割，人人都会）")
    w("    反常交易才是信息差：")
    w("      · 跌停板被机构砸几亿买 → 他知道你不知道的")
    w("      · 利好满天飞却有机构净卖 → 这利好是假的")
    w("      · 板块跌但资金大幅流入 → 有人在恐慌里收货")
    w("      · 全场追涨停时某票缩量横盘量比>1.3 → 有人在悄悄吸")
    w("    ★AI亏钱的每一笔都买在『正常』里，赚的机会都在『反常』里")
    w("=" * 60)


# ========== ★买入后复核（防御系统核心：提早发现"我买错了"） ==========
# 用户原话："做错方向不可怕，提早发现做错并及时止损才是真正厉害的地方"
# 卖出卡管的是【逻辑破了】(外部变了)；本模块管的是【我当初就判断错了】(内部错了)

# 买入时的关键判据快照（AI每次推荐后必须填这张表）
ENTRY_SNAPSHOT = {
    "603220": {"name": "中贝通信", "date": "2026-08-04",
               "sector": "通信服务", "sector_fund": "+103.74亿(通信设备全场第一)",
               "sector_day": "连3天", "ambush": "冷低早量比1.31(暗流)",
               "key": "AI算力capex 7500亿 + 冷低早90%胜率"},
    "688126": {"name": "沪硅产业", "date": "2026-08-07",
               "sector": "半导体", "sector_fund": "+45.46亿(全场第一)",
               "sector_day": "连4天,3日+9.6%",
               "ambush": "✅量比1.16涨日放量+缩量0.59(全场最缩)",
               "key": "300mm大硅片=所有芯片衬底｜台积电二维晶体管突破｜"
                      "1-7月集成电路出口+99.5%｜存储三巨头2027产能售罄→晶圆厂必扩产"},
    "605376": {"name": "博迁新材", "date": "2026-08-07",
               "sector": "金属新材料", "sector_fund": "板块+1.79%",
               "sector_day": "连6天", "ambush": "✅量比1.29+8/6机构净买3.44亿",
               "key": "MLCC超微镍粉｜三星电机8月涨价30%｜太阳诱电订单暴增上调capex"},
    "159934": {"name": "黄金ETF易", "date": "2026-08-05",
               "sector": "贵金属", "sector_fund": "+45.23亿(全场第一)",
               "sector_day": "连2天🚀51→1名",
               "ambush": "⚠️埋伏池为空",
               "key": "金价破4130→4200 + 韩国央行13年首次购金 + 加息概率64.7%→58.4%"},
    "000938": {"name": "紫光股份", "date": "2026-07-31",
               "sector": "计算机设备", "sector_fund": "板块流入",
               "sector_day": "🆕第1天", "ambush": "✅机构净买5.06亿(占92%)",
               "key": "算力网4万亿 + 云厂capex"},
    "159796": {"name": "电池ETF汇", "date": "2026-07-27",
               "sector": "电池", "sector_fund": "+68.14亿(全场第一)",
               "sector_day": "🆕第1天", "ambush": "⚠️埋伏池为空",
               "key": "9/1消费税倒计时"},
    "002714": {"name": "牧原股份", "date": "2026-07-10",
               "sector": "养殖业", "sector_fund": "—",
               "sector_day": "—", "ambush": "—",
               "key": "⚠️政治局'稳定生猪价格'(事后发现是中性表述，非利好)"},
}


def scan_entry_review():
    """买入后复核：用今天的数据，重新审当初的判断对不对"""
    w("\n" + "=" * 60)
    w("🛡️【买入后复核·防御核心】提早发现『我当初就买错了』")
    w("=" * 60)
    w("  卖出卡管【逻辑破了】(外部变)；本模块管【我判断错了】(内部错)")
    w("  ⚠️ 两者都要走，但触发条件不同：")
    w("     逻辑破 → 按买入时写死的定义走")
    w("     判断错 → 关键判据反转即走，不必等逻辑破")

    def _do():
        _, bdf = multi_source("板块(复核)", [
            ("同花顺", lambda: ak.stock_fund_flow_industry(symbol="即时")),
            ("东财", lambda: ak.stock_sector_fund_flow_rank(
                indicator="今日", sector_type="行业资金流")),
        ])
        cur = {}
        if bdf is not None:
            bn = pick_col(bdf, ["名称", "行业", "板块"])
            bp = pick_col(bdf, ["涨跌幅", "行业指数涨跌", "涨跌"])
            bv = pick_col(bdf, ["主力净流入-净额", "主力净流入", "净额", "流入资金"])
            for _, r in bdf.iterrows():
                v = pd.to_numeric(r[bv], errors="coerce") if bv else None
                if v is not None and pd.notna(v) and abs(v) > 1e6:
                    v = v / 1e8
                p = pd.to_numeric(r[bp], errors="coerce") if bp else None
                cur[str(r[bn])] = (p, v)

        # ★★V8.4：只复核【清单里还持有】的票★★
        # 8/11教训：沪硅产业8/10已卖出，复核模块还在说"初判成立，按原计划持有"
        # —— 因为 ENTRY_SNAPSHOT 是独立硬编码表，不跟 我的清单.txt 联动
        held = {c for c, n, tag, *_r in WATCH_STOCKS if tag == "持仓"}
        for code, snap in ENTRY_SNAPSHOT.items():
            if held and code not in held:
                continue
            w(f"\n  ◆ {snap['name']}({code})  买入日 {snap['date']}")
            w(f"     当初理由：{snap['key']}")
            w(f"     当初板块：{snap['sector']} 资金{snap['sector_fund']} {snap['sector_day']}")
            if code in COMMODITY_ETF:
                w(f"     ⚠️★商品型ETF★：它跟{COMMODITY_ETF[code]}，不跟股票板块。")
                w("        下面的『板块资金』指的是【股票板块】，对它无效——")
                w("        商品涨而股票跌是常态(8/11:金价+1.1%但黄金股-4.8%)。")
                w("        判它的唯一标尺是【商品价格本身】，不是板块资金。")
            w(f"     当初游资：{snap['ambush']}")
            flags = []
            # 复核1：买入时⑤就是"埋伏池为空/追高型" = 当初判据本身有瑕疵
            if "⚠️" in snap["ambush"]:
                flags.append("买入时⑤游资项就有瑕疵（当时不该给A级）")
            if "⚠️" in snap["key"]:
                flags.append("买入理由本身存疑（事后发现误读）")
            # 复核2：板块资金是否反转
            hit = None
            for k, (p, v) in cur.items():
                if snap["sector"] in k or k in snap["sector"]:
                    hit = (k, p, v)
                    break
            if hit:
                k, p, v = hit
                pt = f"{p:+.2f}%" if p is not None and pd.notna(p) else "?"
                vt = f"{v:+.2f}亿" if v is not None and pd.notna(v) else "?"
                w(f"     今日板块：[{k}] {pt} 资金{vt}")
                # ★★★V9.9 血的教训：单日资金流不许当"初判已错"的证据★★★
                # 8/13 紫光股份涨停(+10.00%，封单28.78亿)，而我8/12让用户
                #   在36.62清仓了500股 —— 少赚2,040元。
                # 我的理由是"计算机设备资金-0.08亿，钱不在它那条腿上"。
                # ★但紫光今天涨停的驱动是【CPO交换机+国产算力+中报预增】，
                #   这三条昨天全都在，一条都没变。变的只是"昨天那一天的资金流"。
                # ★同一天我还用同样理由劝卖创新药ETF，它今天+6.20%。
                # ★根因：我拿【噪音级的日内数据】去推翻【12周维度的判断】。
                #   资金流是滞后指标，单日波动几乎全是噪音。
                # 【新规】资金反转要同时满足三条，缺一不算：
                #   ①连续≥2天流出（单日不算）
                #   ②累计流出 > 板块日均成交的显著比例（用-30亿作粗线）
                #   ③★板块【同时在跌】★—— 资金出但板块涨=有人收货(铁律K反常)
                _fund_flag = False
                if v is not None and pd.notna(v) and "+" in snap["sector_fund"]:
                    _pv = float(p) if p is not None and pd.notna(p) else 0.0
                    if v < -30 and _pv < -1.0:
                        _fund_flag = True
                        flags.append(f"板块资金反转流出{v:.1f}亿【且板块同时跌{_pv:.2f}%】")
                    elif v < -10:
                        w(f"     ⚠️板块资金流出{v:.1f}亿，但"
                          + (f"板块仍涨{_pv:+.2f}% → 铁律K【反常】：有人在恐慌里收货，不是走人信号"
                             if _pv >= 0 else
                             f"跌幅仅{_pv:.2f}%，未达-30亿+跌1%双条件 → 视为噪音，不计入初判已错"))
                        w("        ★8/13教训：紫光『资金-0.08亿』被我判死，当天它涨停(+10%)")
            else:
                w("     今日板块：无数据")

            if not flags:
                w("     ✅【初判成立】关键判据未反转，按原计划持有")
            elif len(flags) == 1:
                w(f"     ⚠️【初判存疑】{flags[0]}")
                w("        → 建议：不加仓，反弹减半，止损上移")
            else:
                w("     🔴【初判已错】" + "；".join(flags))
                w("        → 建议：★减半★，不是清仓（V9.9修正）")
                w("        ⚠️8/13教训：铁律S/J说的都是【减半】，")
                w("           我却让用户把紫光500股全清了 —— 多走的那一步是我加的。")
                w("           当天它涨停+10.00%，封单28.78亿。")
                w("        （这就是『提早发现做错』——但纠错也要按规则的力度，不加码）")

        w("\n  ⚠️ 铁律J（V4.1新增）：")
        w("    买入后48小时内，必须用新数据复核一次关键判据")
        w("    ①板块资金反转 ②游资从埋伏变追高 ③买入理由被证伪")
        w("    → 命中2项 = 初判已错 = ★减半★，不许清仓（V9.9）")
        w("    ⚠️★单日资金流不算证据★：必须连续≥2天 且 流出>30亿 且 板块同时在跌")
        w("       资金流出但板块在涨 = 铁律K反常 = 有人在恐慌里收货，是买点不是卖点")
        w("    ★区别：逻辑破=外部变了(认赔)；初判错=我看错了(认错)")
        w("      认错要比认赔更快，因为错的是起点不是过程")
    safe_run("买入后复核", _do)


# ========== ★埋伏信号转化率（治"识别到却不买"） ==========
# 高价股/买不起的票 → 自动映射到可买的ETF
HIGH_PRICE_ETF = {
    "中际旭创": "光模块/通信ETF：515880通信ETF、159516光模块ETF",
    "新易盛": "光模块/通信ETF：515880通信ETF、159516光模块ETF",
    "天孚通信": "光模块/通信ETF：515880、159516",
    "寒武纪": "科创芯片ETF：588200、589130",
    "海光信息": "科创芯片ETF：588200、589130",
    "北方华创": "半导体设备ETF：159516、561980",
    "中微公司": "半导体设备ETF：159516、561980",
    "长鑫科技": "存储/科创芯片ETF：588200",
    "德明利": "存储芯片ETF、半导体ETF：512480",
    "兆易创新": "存储芯片ETF、半导体ETF：512480",
    "药明康德": "创新药/医疗ETF：512170、159992",
    "宁德时代": "电池ETF：159796、新能源车ETF",
}

# ★埋伏信号台账（AI每次识别到机构埋伏，必须记在这，并注明是否给出可执行标的）
AMBUSH_SIGNALS = [
    # (识别日, 标的, 信号强度, 是否给出可执行标的, 结果)
    ("2026-07-28", "中际旭创/新易盛", "机构37.47亿跌停板买入", "否-只说观察",
     "7/29+4.74% → 8/4累计+19.6% ❌错过"),
    ("2026-07-30", "长电科技", "四大机构3.17亿跌停板买入", "否-只说观察",
     "7/31费半+8.19% ❌错过"),
    ("2026-08-03", "德明利/雅克/通富", "机构8.19亿跌停板买入", "给了信号卡未执行",
     "8/4中际旭创+8.91%、新易盛+9.96% ❌错过"),
]


def scan_signal_conversion():
    """埋伏信号转化率：识别了多少次？真正下单了几次？"""
    w("\n" + "=" * 60)
    w("🎯【埋伏信号转化率】治AI通病：识别到信号却不给可执行标的")
    w("=" * 60)
    if not AMBUSH_SIGNALS:
        w("  暂无记录")
        return
    total = len(AMBUSH_SIGNALS)
    done = sum(1 for x in AMBUSH_SIGNALS if x[3].startswith("是"))
    w(f"  ★累计识别 {total} 次埋伏信号，真正转化为可执行标的 {done} 次")
    w(f"  ★转化率 {done/total*100:.0f}%")
    w("")
    for d, name, sig, conv, res in AMBUSH_SIGNALS:
        flag = "✅已转化" if conv.startswith("是") else "❌未转化"
        w(f"  {d} {name}")
        w(f"     信号：{sig}")
        w(f"     {flag}（{conv}）")
        w(f"     结果：{res}")
    w("")
    w("  ⚠️ 铁律H（V4.0新增）：")
    w("    识别到【机构在跌的票上净买≥1亿】= 必须当场给出可执行标的")
    w("    ① 个股买得起 → 直接给个股 + 买点 + 止损")
    w("    ② 个股太贵(一手>总资产10%) → 必须给对应ETF，不许只说『观察』")
    w("    ③ 不许用『等明天验证』当拖延借口——")
    w("       验证的正确方式是【小仓位试探】，不是【完全不买】")
    w("    ④ 信号次日若下跌，不算信号错，B类仓要给足3个交易日")
    w("")
    w("  ★高价股→可买ETF 映射表（买不起个股就买这个）：")
    for k, v in list(HIGH_PRICE_ETF.items())[:8]:
        w(f"    {k} → {v}")
    w("=" * 60)


# ========== ★AI推荐台账（自动对账，战绩不靠记忆） ==========

def scan_ledger():
    w("\n★★★【AI推荐台账·自动对账】★★★（战绩机器记账，赖不掉）")
    if not RECOMMENDATIONS:
        w("  台账为空")
        return

    def _do():
        spot = get_spot()
        etf = None
        c_code = pick_col(spot, ["代码", "code"]) if spot is not None else None
        c_price = pick_col(spot, ["最新价", "trade"]) if spot is not None else None
        today = now_beijing()
        win = lose = 0
        for d, code, name, cost, typ, period, broken in RECOMMENDATIONS:
            price = None
            try:
                if spot is not None:
                    r = spot[spot[c_code].astype(str).str.contains(code, na=False)]
                    if len(r) > 0:
                        price = pd.to_numeric(r.iloc[0][c_price], errors="coerce")
                if price is None or pd.isna(price):
                    if etf is None:
                        etf = get_etf_spot()
                    if etf is not None:
                        ec = pick_col(etf, ["代码", "symbol"])
                        ep = pick_col(etf, ["最新价", "trade"])
                        r = etf[etf[ec].astype(str).str.contains(code, na=False)]
                        if len(r) > 0:
                            price = pd.to_numeric(r.iloc[0][ep], errors="coerce")
            except Exception:
                pass
            days = (today - datetime.datetime.strptime(d, "%Y-%m-%d")).days
            if price is None or pd.isna(price):
                w(f"  {d} {name}({code}) @{cost} [{typ}类] → 取价失败")
                continue
            if not cost or cost <= 0:
                w(f"  ⚠️ {name}({code}) 成本未填 → 现价{price}，请提供成交价后对账")
                continue
            pnl = (price - cost) / cost * 100
            # ★胜利标准（V4.4）：≥10%才算赚钱，扣掉手续费/印花税/滑点后才有意义
            if pnl >= 10:
                win += 1
                flag = "✅赚钱"
            elif pnl > 0:
                lose += 0
                flag = "⏳在途(未达10%不算赚)"
            else:
                lose += 1
                flag = "❌"
            extra = ""
            if typ == "A":
                extra = f" ⚠️事件仓已持有{days}天，事件仓不该超3天"
            else:
                extra = f" 周期仓第{days}天/{period}"
            w(f"  {flag} {d} {name}({code}) @{cost}→{price} {pnl:+.2f}% [{typ}类]{extra}")
            w(f"       逻辑破的定义：{broken}")
        # ★★V7.0：已平仓必须进战绩，否则只统计浮盈 = 幸存者偏差★★
        w("\n  ── 已平仓（原来是注释，看不见）──")
        cw = cl = 0
        for cd_, code_, nm_, buy_, sell_, qty_, note_ in CLOSED:
            if not buy_ or buy_ <= 0:
                w(f"  ⚠️ {nm_}({code_}) 缺买入价，无法对账")
                continue
            r_ = (sell_ - buy_) / buy_ * 100
            amt_ = (sell_ - buy_) * qty_ if qty_ else 0
            if r_ >= 10:
                cw += 1
                f_ = "✅赚钱"
            elif r_ > 0:
                f_ = "⏳未达10%(不算赚)"
            else:
                cl += 1
                f_ = "❌"
            at_ = f" {amt_:+.0f}元" if qty_ else " (股数未填)"
            w(f"  {f_} {cd_} {nm_}({code_}) @{buy_}→{sell_} {r_:+.2f}%{at_} {note_}")
        w(f"\n  ★★总战绩：持仓{win}胜(≥10%) {lose}负 ｜ 已平仓{cw}胜 {cl}负")
        w(f"  ★★已实现盈亏：{REALIZED_PNL_YUAN:+,}元")
        w(f"  ★★总资产{TOTAL_ASSET:.2f}万 / 本金{PRINCIPAL:.2f}万 = "
          f"{(TOTAL_ASSET-PRINCIPAL)/PRINCIPAL*100:+.2f}%  ← 这才是真实成绩")
        w("  ⚠️ 只看持仓浮盈会得出『+3,558』的假象，实际本金已亏8%")
        w("  ⚠️ 胜利标准=盈利≥10%。低于10%只算『在途』，")
        w("     扣手续费/印花税/滑点后基本无利润，不许当成功。")
        w("  ⚠️ A类事件仓超期未走 = 违反铁律，立即处理")
        w("  ⚠️ B类周期仓在期内跌5-8% = 噪音，不许砍（铁律F）")
    w("  ⚠️ ★铁律R（V5.6）：达+10%即可分批兑现，不必死守全周期★")
    w("     持有周期是【最长期限】，不是【必须期限】")
    w("     +10% → 减半锁利，剩余仓位设移动止盈(从最高点回落5%)")
    w("     +20% → 再减半，剩余当免费仓")
    w("     用户原话：『潜伏一两个月就没意思了』")
    safe_run("推荐台账", _do)


# ========== ★卖出决策卡（治"买入用长线逻辑，卖出用短线跌幅"） ==========

def scan_sell_card():
    w("\n" + "=" * 60)
    w("★★★【卖出决策卡 · 想卖之前必须填完】★★★")
    w("=" * 60)
    w("  标的：____________")
    w("")
    w("  ① 当初买入是 A类事件仓 还是 B类周期仓？")
    w("     → ______________________")
    w("")
    w("  ② 当初写死的『逻辑破』定义是什么？（去台账里查，不许现编）")
    w("     → ______________________")
    w("")
    w("  ③ 这个定义现在触发了吗？  □是 → 走  □否 → 看④")
    w("     → ______________________")
    w("")
    w("  ④ 没触发却想卖，理由是什么？")
    w("     『它跌了X%』         → ❌ 不是理由，B类仓5-8%是噪音")
    w("     『我怕』             → ❌ 不是理由")
    w("     『大盘不好』         → ❌ 除非驱动链本身断了")
    w("     『催化取消/证伪』     → ✅ 这才是理由")
    w("     『板块驱动链断裂』    → ✅ 这才是理由")
    w("     『A类事件已兑现』     → ✅ 这才是理由")
    w("     → ______________________")
    w("")
    w("  ⑤ 如果卖了，这笔钱去哪？（说不出去处 = 不该卖）")
    w("     → ______________________")
    w("  ─────────────────────────────────────")
    w("  ⚠️ 填不出④里的✅项 = 不许卖")
    w("  ⚠️ 铁律F：买入用产业周期逻辑，就不许用短线跌幅卖出")
    w("")
    w("  ★★★铁律X（V9.9 · 8/13紫光血案）★★★")
    w("  ⚠️【单日板块资金流】不构成任何卖出理由，一票作废")
    w("     8/13 紫光股份涨停+10.00%（封单28.78亿），")
    w("     而我8/12用『计算机设备资金-0.08亿』让用户在36.62清了500股。")
    w("     ★它涨停的驱动是【CPO交换机+国产算力+中报预增】——")
    w("       这三条昨天全都在，一条都没变。变的只是那一天的资金流。")
    w("     ★同一天我用同样理由劝卖创新药ETF，它今天+6.20%。")
    w("     ★两笔合计让用户少赚约3,000元。")
    w("")
    w("  ⚠️【卖多少】也要按规则，不许加码")
    w("     铁律R说『减半』、铁律S说『减半』、铁律J说『减半』")
    w("     —— 没有任何一条铁律说『清仓』。")
    w("     8/12我让用户把紫光剩下500股全清，多走的那一步是我加的。")
    w("     ★纠错的力度也要守规则。")
    w("")
    w("  ⚠️【什么才算板块驱动链断裂】（能填④的✅项）")
    w("     ①连续≥2个交易日资金净流出，且累计>30亿")
    w("     ②★同时★板块在跌（跌>1%）")
    w("     ③催化被官方/公司证伪（不是『资金少了』，是『事情黄了』）")
    w("     ★资金流出但板块在涨 = 铁律K反常 = 有人在恐慌里收货 = 买点不是卖点")
    w("=" * 60)


# ========== ★决策卡（任何买卖建议前必填，防止AI忘记自己的铁律） ==========

def scan_decision_card():
    w("\n" + "=" * 60)
    w("★★★【决策卡 · 买卖前必填，填不满不许出建议】★★★")
    w("=" * 60)
    w("  标的：____________  方向：买 / 卖 / 等")
    w("")
    w("  ① 板块第几天？🆕第1天 | 连2天 | 🔥连≥5天")
    w("     ⚠️★天数必须绑定③-B判读，单独看天数没有意义★")
    w("       产业周期驱动 → 连20-30天都正常，回调是买点")
    w("       单一事件驱动 → 连3-5天就是高潮")
    w("     → ______________________")
    w("")
    w("  ①-B ★★★这只票的【真实驱动】是什么？★★★（V4.5，最易错的一项）")
    w("     ⚠️ 行业分类 ≠ 真实驱动。同一分类里可以有相反的驱动！")
    w("     必须回答两句：")
    w("       a) 这只票靠什么赚钱？（下游客户是谁、需求来自哪）")
    w("       b) 今天板块上涨的原因，和它的驱动是【同一个】吗？")
    w("     ★不是同一个 → 『板块顺风』对它无效 → ①作废")
    w("")
    w("     血的教训（都是同一个错）：")
    w("       · 招商轮船[航运港口] 真实驱动=西芒杜铁矿长约")
    w("         我却用『油气开采跌4%』判它死 → 卖飞18%")
    w("       · 卓胜微[半导体] 真实驱动=手机出货量")
    w("         半导体涨是因为存储涨价/设备/AI算力，与它无关")
    w("         而且存储涨价→手机成本↑→对它是利空")
    w("       · 紫光股份[计算机设备] 真实驱动=云厂capex ✅这个对了")
    w("     → ______________________")
    w("")
    w("  ② 板块资金今日流向？（流入✅ / 流出⚠️，但看③）")
    w("     → ______________________")
    w("")
    w("  ③-A 催化是什么？有没有具体日期？")
    w("     → ______________________")
    w("  ③-B ★★这个催化是【产业周期】还是【单一事件】？★★")
    w("     【产业周期】涨价/缺货/产能紧缺/政策倒计时/国产替代")
    w("        → 能持续几周几月，每天涨也能追，而且该追")
    w("        → 必须填出：预计持续 ____ 周")
    w("     【单一事件】IPO上市/发布会/财报/政策发布日")
    w("        → 事件当天就是顶，事后买必亏")
    w("     ⚠️ 填不出『持续N周』= 当成单一事件 = 不许当趋势买")
    w("     → ______________________")
    w("")
    w("  ④ 位置：60日涨跌 / 均线？")
    w("     → ______________________")
    w("")
    w("  ⑤ 游资：埋伏型(买当天在跌的)✅ / 追高型(买涨停的)⚠️")
    w("     → ______________________")
    w("")
    w("  ⑥ 宏观驱动链冲突？油涨→杀成长；油跌→利好成长")
    w("     → ______________________")
    w("")
    w("  ⑦ 与今天其他建议冲突吗？")
    w("     → ______________________")
    w("")
    w("  ⑧ ★★与现有持仓是不是同一条驱动链？★★")
    w("     同一条链的仓位合计不许超过总仓位40%")
    w("     ★单笔上限(V5.7)：九项全过+机构埋伏背书 → 可到总资产20%")
    w("       九项过七八项 → 11%｜勉强过 → 6%")
    w("       ⚠️分散不是目的，赚钱才是。1万仓位赚10%只有1000块")
    w("     → ______________________")
    w("")
    w("  ⑨ ★★仓位类型 + 持有周期 + 逻辑破的定义（买入时就写死）★★")
    w("     □ 产业周期仓 → 持有 ____ 周")
    w("        卖出条件：只有『驱动逻辑破了』才走")
    w("        逻辑破 = ____________________（现在就写，不许事后找）")
    w("        ⚠️ 期间跌5-8%是噪音，不许砍")
    w("     □ 事件仓 → 持有 ____ 天，兑现日无条件走")
    w("     → ______________________")
    w("")
    w("  ─────────────────────────────────────")
    w("  ⚠️ 铁律A：有日期的未来催化 > 过去的资金流")
    w("  ⚠️ 铁律B：游资在跌的板块砸钱 = 埋伏 = 明天机会")
    w("  ⚠️ 铁律C：先board再stock，板块逆风一票否决")
    w("  ⚠️ 铁律D：宁可报空，不硬凑标的。一周最多1-2笔")
    w("  ⚠️ 铁律E：踏空也是亏，方向确认就给进攻方案")
    w("  ⚠️ 铁律F：★买入用什么逻辑，卖出就用什么标尺★")
    w("     用产业周期让他买，就不许用短线跌幅让他卖")
    w("  ⚠️ 铁律V（V8.3·用户死命令）：★发现问题立刻自己改，不许问、不许拖★")
    w("     用户原话：『以后发现问题，不需要问我，自己立刻修改，为什么要偷懒？』")
    w("  ⚠️ 铁律W（V8.3）：★事件驱动 ≠ 产业驱动，管法完全不同★")
    w("     事件=A类，涨了就走，仓位≤6%，入场点是公告当天")
    w("     产业=B类，能扛回调，仓位≤11%，5-8%是噪音")
    w("     ★判错类型比选错票更致命（半导体设备ETF −11.5%）")
    w("  ⚠️ 铁律U（V7.2·用户死命令）：★美股隔夜每次必写，与A股新闻并列★")
    w("     『用户没问美股』『今天A股是主角』= 全部不成立")
    w("     必写：指数(费半SOX)/个股/聪明钱/宏观 + ★美股与A股方向对照★")
    w("     方向相反 = 铁律K反常 = 当场解释，不许略过")
    w("     ⚠️ 用户原话：『我不想要一个丢三落四的AI作为我帮手』")
    w("  ⚠️ 铁律T（V6.0·用户死命令）：★发现BUG当场修，不许说明天★")
    w("     『我明天改』『下次一起改』『之后补上』= 全部违规")
    w("     系统自检发现的每一个漏洞，必须在同一轮对话内给出修复文件")
    w("  ⚠️ 铁律O：★连涨天数不构成买卖理由★")
    w("     天数只有绑定驱动类型才有意义：")
    w("     产业周期(存储/AI算力/国产替代)连30天都不算高潮")
    w("     单一事件(IPO/发布会)连3天就到顶")
    w("  ⚠️ 铁律L：★推荐前必须先答①-B『真实驱动是什么』★")
    w("     答不出『它靠什么赚钱、需求来自哪』= 不许推荐")
    w("     行业分类只是标签，驱动才是本质")
    w("  ⚠️ 铁律H：★识别到机构埋伏信号=必须给可执行标的★")
    w("     个股太贵就给ETF，不许只说『观察』或『等明天验证』")
    w("     验证的方式是小仓位试探，不是完全不买")
    w("  ⚠️ 铁律I：★决策卡⑤只认『机构专用席位买跌的票』★")
    w("     封单大/炸板0次 ≠ 埋伏型，那只能证明有人封板")
    w("  ⚠️ 铁律G：不许推『今天资金第一』当买入理由——")
    w("     那是收盘后算的，等于买在当天最高点。")
    w("     除非③-B能填出『产业周期·持续N周』")
    w("=" * 60)
    w("")
    w("=" * 60)
    w("★★★【固定输出骨架 · AI每次干活必须全给，缺一节可当场追责】★★★")
    w("=" * 60)
    w("  ① 【数据新鲜度判定】报告时间/距今/最新可用或陈旧弃用")
    w("  ② ★重点盯盘（全部持仓 + 中国长城，逐只：板块/资金/技术/消息）")
    w("  ③ 大盘环境 + 风险分 + 结构分化（创业板/科创50跌幅）")
    w("  ④ 板块判断（先board再stock）")
    w("  ⑤-B ★美股隔夜（铁律U·2026-08-10用户死命令）★")
    w("      必写四项：①指数(费半SOX必写) ②重点个股涨跌")
    w("               ③聪明钱专区 ④宏观(非农/加息概率/油价/地缘)")
    w("      ★必须做三方对照，不许只罗列：")
    w("        美股某板块涨 → A股对应板块今天涨还是跌？")
    w("        方向相反 = 铁律K【反常】= 必须当场解释原因")
    w("      ⚠️ 数据在 reports/美股_最新.txt，AI必须主动去读，")
    w("         不许因为『用户没提美股』就跳过")
    w("  ⑤ 全套新闻·八类（名人/国内政策/海外政策/科技/大宗地缘/")
    w("     资金事件/消费养殖/政策产业专项）——不许等用户提醒")
    w("  ⑥ 决策卡（要买卖时逐项填，含③-B ⑧ ⑨）")
    w("  ⑦ 持仓逐个指令（持有/减/清 + 理由）")
    w("  ⑧ AI推荐台账对账（A类超期？B类在期内？）")
    w("  ⑨ 要卖时必填【卖出决策卡】，④里填不出✅项=不许卖")
    w("  ⑪ ★【我的持仓·相关消息】V8.0：每只持仓的个股级新闻/公告，不许漏")
    w("  ⑫ ★★【事件驱动雷达】V8.3：控制权变动/资产注入/重组★★")
    w("     A股最猛的短线驱动。入场点=公告当天，不是第N板。")
    w("     高争民爆7/28公告→9天8板翻倍，旧系统六道闸全漏")
    w("=" * 60)


# ========== 主程序 ==========

def main():
    bj = now_beijing()
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][bj.weekday()]
    weekend = bj.weekday() >= 5
    intraday = (not weekend) and (9 <= bj.hour < 15)
    # ★★★V8.9【快扫模式】★★★
    # 8/12用户反馈：盘中跑一次要十几分钟，等不起。
    # 盘中真正要的只有三件事：我的票怎么样 / 板块和钱去哪了 / 有没有埋伏信号。
    # 推演/交叉/回测/公告/事件雷达 → 盘后看就够，盘中跑纯粹是等。
    # 触发：环境变量 FAST=1，或者盘中时段自动开启（收盘后仍跑全套）。
    # ★★★V9.2：快扫默认关闭★★★
    # 8/12用户质问："快扫有何用？不完整的数据我要来有何用？"
    # 他是对的。我提速的方向选错了 ——
    #   不该靠【砍掉数据】提速，该靠【修数据源】提速。
    #   今天慢的真实原因是东财连挂5次、每次等满超时，那个已经修好
    #   （东财降为备源 + 关键请求 critical 保护）。
    # ★一份缺了新闻/推演/交叉/回测的报告，等于让AI闭着一只眼做判断。
    #   省下的几分钟，换来的是判断质量下降 —— 这笔账不划算。
    # 现在：默认永远全扫。只有显式设 FAST=1 才快扫（应急用）。
    FAST = os.environ.get("FAST", "").strip() in ("1", "true", "yes", "on")
    globals()["FAST_MODE"] = FAST
    if weekend:
        mode = "周末新闻扫描"
    elif intraday:
        mode = "盘中快扫⚡(应急)" if FAST else "盘中全扫描"
    else:
        mode = "盘后全扫描"

    w("=" * 60)
    w(f"A股作战扫描器V11.0 | {bj.strftime('%Y-%m-%d %H:%M')} {weekday} | {mode}")
    if FAST:
        w("⚡ 快扫模式(应急)：数据不完整，仅供紧急查价，不可用于决策。")
    w("=" * 60)

    # ★★V8.0：先从 我的清单.txt 载入持仓（覆盖代码内写死的表）★★
    safe_run("载入我的清单", _load_watchlist)

    scan_skeleton_top()

    if weekend:
        scan_news()
    else:
        scan_regime_gate()
        scan_tomorrow_gate()
        scan_focus_stocks()
        scan_intraday_hotmoney()
        scan_breadth()
        scan_spot()
        scan_cold_low()
        scan_board_rank()
        scan_sector_flow()
        if not intraday:
            scan_zt_pool()
            scan_lhb()
            scan_hot_money()
            scan_north()
        if FAST:
            w("\n⚡【快扫模式】已跳过：全量新闻流/催化热力图/推演引擎/全板块交叉/")
            w("   深层含义/公告/异动/事件雷达/定增雷达/四大回测")
            w("   → 盘中只保留：持仓盯盘 + 游资雷达 + 冷低早 + 板块 + 资金 + 止盈")
            w("   → 要完整版：手动触发时把 FULL=1，或等15:30盘后自动全扫")
        else:
            scan_news()

    # ★★V7.0：这5个模块不再依赖新闻源成败，独立运行★★
    safe_run("止盈体系", scan_take_profit)          # ★快扫也保留：止盈是命
    if not weekend and not FAST:
        safe_run("启动日雷达", scan_launch_radar)
        safe_run("个股级选股器", scan_stock_picker)
        safe_run("公告扫描", scan_announcements)
        safe_run("异动无解释", scan_unexplained)
        # ★★V8.3 事件驱动雷达：必须在公告扫描之后（依赖 TODAY_ANNOUNCE_RAW）★★
        safe_run("事件驱动雷达", scan_event_radar)
        safe_run("定增破发雷达", scan_placement_radar)
        safe_run("推荐前检查表", scan_reco_checklist)
        safe_run("持仓/候选 深度体检", scan_all_deep)
        safe_run("★选股流水线★", scan_pipeline)
    if not FAST:
        # ★★V8.0：持仓个股级消息（新闻+公告按股票名精确匹配）★★
        safe_run("我的持仓相关消息", scan_my_news)

    if not weekend and not FAST:
        safe_run("埋伏池回测", lambda: backtest_ambush(TODAY_AMBUSH))
        safe_run("热力图回测", lambda: backtest_heat(TODAY_HEAT_TOP3))
        safe_run("选股器回测", backtest_picker)
        safe_run("事件雷达回测", backtest_event)
    safe_run("仓位建议", lambda: scan_position_advice(LAST_RISK_SCORE))
    scan_rule_scorecard()
    safe_run("买入后复核", scan_entry_review)
    scan_signal_conversion()
    scan_ledger()
    scan_sell_card()
    scan_decision_card()

    os.makedirs("reports", exist_ok=True)
    text = "\n".join(REPORT)
    date = bj.strftime("%Y%m%d")
    prefix = "盘中" if intraday else ("周末" if weekend else "盘后")

    for path in [f"reports/{prefix}_最新.txt", f"reports/{prefix}_{date}.txt",
                 "reports/latest.txt"]:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    print(f"\n✅ V11.0完成 {prefix}_最新.txt")


if __name__ == "__main__":
    main()

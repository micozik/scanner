# -*- coding: utf-8 -*-
"""
patch_mustanswer.py  ——  放仓库【根目录】  ★V2，替换掉上一版★

★上一版为什么失败（2026-09-07 实测）★
  报告里的必答清单还是只有 [1]~[5]，没有 [U][S][P]。
  原因：我用的锚点『── AI回应格式（每条都要写）──』
        是【输出文本】里的样子，源码里可能被拆在 f-string、
        w() 调用、或多行拼接里，字符不完全一致 → 匹配不上，
        补丁静默放弃（这正是 patch10 那种"装了等于没装"）。

★V2 的三道保险★
  ① 试 5 个候选锚点，任一命中即插入
  ② ★全部失败也不会白跑★：自动把源码里
     『今日必答清单』附近的真实代码写进
     reports/必答诊断_日期.txt，下一轮我照着改，一次改对
  ③ ★无论成不成功，都写一份独立文件★
     reports/必答三条_最新.txt
     —— 用户每天连它一起发给我，等于强制我回答，
        不依赖主文件改造是否成功

★这三条要强制回答什么★
  [U] 美股三方对照（铁律U · 2026-09-04血案）
      2026-09-04 AI没看美股就砍掉存储链和CPO链。
      而9/3戴尔+15.76%（原话"缺的就是DRAM"）、9/4闪迪+11%费半+3%。
      9/7 A股半导体资金+231.88亿、CPO跳378位到全场第一，
      仕佳+9.38%、佰维+3.68%。★两笔卖出少赚约2,150元★
      ★一票否决：昨夜美股该链在涨 → 今天不许给该链任何卖出建议★

  [S] 卖出三条件逐条打勾
      2026-09-04 AI卖仕佳光子，实际只成立"一条半"就清了200股。
      ①成立(-85亿) ②不成立(板块只跌0.44%) ③把下游的话读反了方向
      ★三条不全 → 最多减半，绝不清仓（铁律X：没有一条铁律说清仓）★

  [P] 死穴四问
      博云新材死在①主营（以为硬质合金=高温合金，实际78%是碳化钨基）
      中航沈飞死在②业绩（H1净利-58.37%、市盈47.77）
      润泽科技死在③主力资金（20日-7.3亿、主力浮亏3.2%）
      山东黄金死在④驱动价格（只看人民币金价日内+2.31%，
                            国际金价已跌破100日均线）

★安全性★
  · 只插文字，不动任何计算逻辑
  · 幂等；锚点不唯一就跳过该锚点，不乱插
  · 改完 compile() 语法自检，★不通过自动回滚★
  · 耗时 <1 秒
"""

import io
import os
import datetime

TARGET = "scanner_cloud.py"
OUTDIR = "reports"
MARK = "[U] 美股三方对照"

# 5个候选锚点，从最精确到最宽松
ANCHORS = [
    "── AI回应格式（每条都要写）──",
    "AI回应格式",
    "我的判断：____",
    "AI回复里必须出现",
    "共 %d 条。AI回复里",
]

ADD = """
  ══════════════════════════════════════════════════
  ★★★以下三条【每天固定必答】，与上面编号同等效力★★★
  ★用户只要看 [U][S][P] 在不在回复里，就知道AI守没守规矩★
  ══════════════════════════════════════════════════

  [U] ⑤-B 美股三方对照（铁律U · 2026-09-04血案）
      必填四个数：费半SOX ____ ｜ 美光/闪迪 ____
                 英伟达 ____ ｜ 美债10年期 ____
      再写三方对照：美股【X链】涨/跌 → A股【X链】今天怎么走？
      ★方向相反 = 铁律K反常 = 当场解释，不许略过★
      ★★一票否决：昨夜美股该链【在涨】→ 今天不许给该链任何卖出建议★★
      ⚠️ 2026-09-04 AI没看美股就砍存储链+CPO链，
         9/7 半导体资金+231.88亿、CPO跳378位全场第一，
         仕佳+9.38%、佰维+3.68%，★少赚约2,150元★

  [S] 卖出三条件（想卖任何一只，必须逐条打勾）
        ① 连续≥2天资金净流出 且 累计>30亿   □是 □否
        ② ★同时★板块在跌（跌>1%）           □是 □否
        ③ 催化被官方/公司证伪               □是 □否
      ★③必须先过【证伪四问】，否则不算数：★
        1. 说话的是谁？★它在这条链的上游还是下游？★
           下游说"供应缓解"= 上游在放量 = 对上游是【利多】
        2. 影响的是【量】还是【价】？两者常反向
        3. 有没有第二个独立来源？★一家公司一句话≠行业事实★
        4. 同链的美股/港股当天怎么走？对标在涨=我大概率读反了
      ★★三条不全 → 最多【减半】，绝不清仓★★

  [P] 死穴四问（推荐任何一只之前必须答完，答不出就要截图）
        ① 它靠什么赚钱？主营占比多少？        （博云新材死在这）
        ② 最近一期业绩，营收/净利同比？        （中航沈飞死在这）
        ③ 主力资金 3日/5日/20日，加速还是减速？（润泽科技死在这）
        ④ ★它的驱动价格此刻是涨是跌？★        （山东黄金死在这）
           —— 自己能搜/查驱动价格表，★不搜就是失职★
      ⚠️ 缺任何一问 → 不许满仓，最多小仓试探(≤6%)，
         并当场向用户要那一屏截图

  ══════════════════════════════════════════════════
"""

STANDALONE = """============================================================
📋📋【每日必答三条】机器强制 · AI漏一条=失职 📋📋
   （由 patch_mustanswer 生成，与主报告的必答清单同等效力）
============================================================
""" + ADD + """
★用法：把本文件的链接和盘中/盘后一起发给AI。
  AI的回复里必须出现 [U] [S] [P] 三个编号，缺一个当场追责。
============================================================
"""


def write_standalone(note=""):
    try:
        if not os.path.isdir(OUTDIR):
            os.makedirs(OUTDIR)
        bj = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
        txt = STANDALONE + "\n生成时间：北京 %s\n%s" % (
            bj.strftime("%Y-%m-%d %H:%M"), note)
        io.open(os.path.join(OUTDIR, "必答三条_最新.txt"),
                "w", encoding="utf-8").write(txt)
        io.open(os.path.join(OUTDIR, "必答三条_%s.txt" % bj.strftime("%Y%m%d")),
                "w", encoding="utf-8").write(txt)
        print("✅ patch_mustanswer: 已写出 reports/必答三条_最新.txt（兜底，一定成功）")
    except Exception as e:
        print("🔴 patch_mustanswer: 兜底文件写失败 %s" % e)


def diagnose(src):
    """主文件改不动时，把必答清单附近的真实代码写出来，下轮照着改"""
    try:
        lines = src.split("\n")
        hits = [i for i, ln in enumerate(lines) if "今日必答清单" in ln]
        out = ["=" * 60,
               "🔬 patch_mustanswer 诊断：5个锚点全部未命中",
               "   下面是源码里『今日必答清单』附近的真实代码，",
               "   把它发给AI，下一轮就能一次改对。",
               "=" * 60]
        if not hits:
            out.append("🔴 源码里连『今日必答清单』都找不到")
        for h in hits[:2]:
            lo = max(0, h - 5)
            hi = min(len(lines), h + 45)
            out.append("")
            out.append("===== 第 %d 行附近 =====" % (h + 1))
            for i in range(lo, hi):
                out.append("  %5d | %s" % (i + 1, lines[i]))
        bj = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
        io.open(os.path.join(OUTDIR, "必答诊断_%s.txt" % bj.strftime("%Y%m%d")),
                "w", encoding="utf-8").write("\n".join(out))
        print("🔬 patch_mustanswer: 已写出 reports/必答诊断_%s.txt"
              % bj.strftime("%Y%m%d"))
    except Exception as e:
        print("🔴 patch_mustanswer: 诊断文件写失败 %s" % e)


def run():
    # 兜底文件先写，不管主文件成不成功
    write_standalone()

    if not os.path.exists(TARGET):
        print("🔴 patch_mustanswer: 找不到 %s → 只有兜底文件" % TARGET)
        return

    src = io.open(TARGET, encoding="utf-8").read()

    if MARK in src:
        print("✅ patch_mustanswer: 主文件已安装过，跳过（幂等）")
        return

    for idx, anchor in enumerate(ANCHORS, 1):
        n = src.count(anchor)
        if n != 1:
            print("   锚点%d『%s』出现%d次，跳过" % (idx, anchor[:20], n))
            continue
        i = src.find(anchor)
        new_src = src[:i] + ADD + "  " + src[i:]
        try:
            compile(new_src, TARGET, "exec")
        except SyntaxError as e:
            print("   锚点%d 插入后语法不通过(%s)，回滚，试下一个" % (idx, e.msg))
            continue
        io.open(TARGET, "w", encoding="utf-8").write(new_src)
        print("✅ patch_mustanswer: 用锚点%d 成功插入 [U][S][P]，语法检查通过" % idx)
        return

    print("🔴 patch_mustanswer: 5个锚点全部未命中 → 主文件未改动")
    print("   已生成诊断文件，请把它发给AI")
    diagnose(src)


try:
    run()
except Exception as e:
    print("🔴 patch_mustanswer 异常，未修改任何文件：%s" % e)

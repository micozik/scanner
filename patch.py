# -*- coding: utf-8 -*-
"""V27.0 补丁 · 在跑扫描前自动修改 scanner_cloud.py
手机传不动376KB的主文件，所以改成这个小补丁。"""
import io, os

P = "scanner_cloud.py"
if not os.path.exists(P):
    print("找不到 scanner_cloud.py"); raise SystemExit(0)
s = io.open(P, encoding="utf-8").read()
n = 0

# ① 5个天天被预算挤掉的模块，加进永不跳过
old1 = '''_NEVER_SKIP = ("止盈体系", "📌推荐跟踪表", "风险监测", "仓位建议",
               "推荐台账", "规则记分卡")'''
new1 = '''_NEVER_SKIP = ("止盈体系", "📌推荐跟踪表", "风险监测", "仓位建议",
               "推荐台账", "规则记分卡",
               "我的持仓相关消息", "持仓相关消息",
               "埋伏池回测", "热力图回测", "选股器回测", "事件雷达回测",
               "买入后复核")'''
if old1 in s:
    s = s.replace(old1, new1); n += 1; print("✅ ①5个必需模块已加入永不跳过")
elif "买入后复核" in s and "_NEVER_SKIP" in s:
    print("↩️ ①已是最新")

# ② 冷低早连续2次回测为负 → 自动停用
old2 = '''            w("    ⚠️ 平均为负 → 这个筛选器当前参数在这种行情下无效，")
            w("       不要照单买，必须配合板块启动信号")'''
new2 = '''            w("    ⚠️ 平均为负 → 这个筛选器当前参数在这种行情下无效，")
            w("       不要照单买，必须配合板块启动信号")
            try:
                _cf = "reports/cold_low_verdict.json"
                _cv = {}
                if os.path.exists(_cf):
                    with open(_cf, "r", encoding="utf-8") as _f:
                        _cv = json.load(_f)
                _neg = int(_cv.get("neg_streak", 0)) + 1
                _cv["neg_streak"] = _neg
                _cv["last_avg"] = float(avg)
                os.makedirs("reports", exist_ok=True)
                with open(_cf, "w", encoding="utf-8") as _f:
                    json.dump(_cv, _f, ensure_ascii=False)
                if _neg >= 2:
                    w("")
                    w("    🔴🔴【冷低早已自动停用】连续%d次回测平均为负" % _neg)
                    w("       ★候选名单仅作记录，AI不许拿它当推荐依据")
                    w("       ★回测转正会自动恢复")
            except Exception:
                pass'''
if old2 in s and "冷低早已自动停用" not in s:
    s = s.replace(old2, new2); n += 1; print("✅ ②冷低早自动停用已加")
elif "冷低早已自动停用" in s:
    print("↩️ ②已是最新")

# ③ 冷低早输出前先看停用标记
old3 = '''    w("\\n★★★【冷低早候选·暗流吸筹】★★★（大盘闸+冷+低+缩量+涨日放量+板块闸）")'''
new3 = '''    w("\\n★★★【冷低早候选·暗流吸筹】★★★（大盘闸+冷+低+缩量+涨日放量+板块闸）")
    try:
        _cf = "reports/cold_low_verdict.json"
        if os.path.exists(_cf):
            with open(_cf, "r", encoding="utf-8") as _f:
                _cv = json.load(_f)
            if int(_cv.get("neg_streak", 0)) >= 2:
                w("  🔴🔴【本模块已自动停用】连续%d次回测平均为负(最近%+.2f%%)"
                  % (_cv.get("neg_streak", 0), _cv.get("last_avg", 0)))
                w("     ★下面的候选【仅作记录】，不许当推荐依据★")
    except Exception:
        pass'''
if old3 in s and "本模块已自动停用" not in s:
    s = s.replace(old3, new3); n += 1; print("✅ ③冷低早停用警告已加")
elif "本模块已自动停用" in s:
    print("↩️ ③已是最新")

# ④ 推荐跟踪表区分 推荐/观察/否决
old4 = '''            bo = "✅买了" if it.get("bought") else "❌没买"'''
new4 = '''            _kind = it.get("kind", "推荐")
            _km = {"推荐": "🎯推荐", "观察": "👁️观察",
                   "否决": "🚫否决"}.get(_kind, _kind)
            bo = "✅买了" if it.get("bought") else "❌没买"'''
if old4 in s and "👁️观察" not in s:
    s = s.replace(old4, new4)
    s = s.replace(
        '''w(f"  {mark} {nm}({c6}) 推荐@{p0} → 现价{px:.2f} "''',
        '''w(f"  {mark} [{_km}] {nm}({c6}) @{p0} → 现价{px:.2f} "''')
    n += 1; print("✅ ④跟踪表已区分 推荐/观察/否决")
elif "👁️观察" in s:
    print("↩️ ④已是最新")

# ⑤ 版本号
if "V26.0 |" in s:
    s = s.replace("A股作战扫描器V26.0 |", "A股作战扫描器V27.0 |")
    s = s.replace('print(f"\\n✅ V26.0完成', 'print(f"\\n✅ V27.0完成')
    n += 1

if n:
    io.open(P, "w", encoding="utf-8").write(s)
    print("★ 补丁应用完成，共 %d 处修改" % n)
else:
    print("★ 无需修改（已是最新）")

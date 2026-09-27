# -*- coding: utf-8 -*-
"""
patch42_tradedays.py —— 持仓天数改按【交易日】算，不再按自然日
2026-09-27 发现（差点让用户白砍一只票）：
  台账写『大金重工[A类] ⚠️事件仓已持有3天，事件仓不该超3天』
  而实际：9/24买入 → 9/25中秋休市 → 9/26、9/27周末
        ★真实交易日过了 0 天★
  照它执行，周一开盘就要清掉一只还没给过机会的票。
  同样问题：东方电气『周期仓第24天/20』按自然日超期，
        按交易日只有约16天，仍在周期内 → 会被误判为超期。

修法：
  ① 优先用 akshare 交易日历 tool_trade_date_hist_sina 精确计算
  ② 拿不到日历就退回【工作日 − 已知节假日表】
     2026节假日：中秋9/25、国庆10/1~10/8（含调休，宁可少算不多算）
  ③ 报告里把两个数都打出来：『交易日N天（自然日M天）』，一眼可核对
"""
import io, os, sys
MARK = "patch42_tradedays"
path = next((c for c in ["scanner_cloud.py", "scanner_cloud__1_.py"] if os.path.exists(c)), None)
if not path:
    print("!! patch42 中止：找不到 scanner_cloud.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch42 已打过"); sys.exit(0)

A = '''            days = (today - datetime.datetime.strptime(d, "%Y-%m-%d")).days'''
if A not in s:
    print("!! patch42 中止：台账天数锚点未命中"); sys.exit(0)

NEW = '''            # ''' + MARK + '''：自然日 → 交易日
            _cal_days = (today - datetime.datetime.strptime(d, "%Y-%m-%d")).days
            days = _tradedays42(d, today, _cal_days)'''
s = s.replace(A, NEW, 1)

B = '''                extra = f" ⚠️事件仓已持有{days}天，事件仓不该超3天"'''
if B in s:
    s = s.replace(B, '''                extra = (f" ⚠️事件仓已持有{days}个交易日(自然日{_cal_days}天)，"
                         f"事件仓不该超3个交易日") if days > 3 else \\
                        f" 事件仓第{days}个交易日/3(自然日{_cal_days}天)"''', 1)

C = '''                extra = f" 周期仓第{days}天/{period}"'''
if C in s:
    s = s.replace(C, '''                extra = f" 周期仓第{days}个交易日/{period}(自然日{_cal_days}天)"''', 1)

# 注入交易日计算函数
D = "def _load_ind_cache():"
if D not in s:
    print("!! patch42 中止：函数注入锚点未命中"); sys.exit(0)
FN = '''# ''' + MARK + '''：交易日计算（剔除周末与法定休市）
_HOLIDAY42 = {
    "2026-09-25",                                    # 中秋
    "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06",
    "2026-10-07", "2026-10-08",                      # 国庆（周末另计）
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18",
    "2026-02-19", "2026-02-20", "2026-04-06", "2026-05-01",
    "2026-06-19",
}


def _tradedays42(buy_str, today_dt, fallback):
    """买入日到今天之间的【交易日】数（不含买入当天）"""
    try:
        _b = datetime.datetime.strptime(buy_str, "%Y-%m-%d").date()
        _t = today_dt.date() if hasattr(today_dt, "date") else today_dt
        # 优先：akshare 交易日历
        try:
            _f = getattr(ak, "tool_trade_date_hist_sina", None)
            if _f is not None:
                _cal = globals().get("_TRADE_CAL42")
                if _cal is None:
                    _df = _f()
                    _col = _df.columns[0]
                    _cal = set(str(x)[:10] for x in _df[_col].tolist())
                    globals()["_TRADE_CAL42"] = _cal
                if _cal:
                    _n, _d = 0, _b + datetime.timedelta(days=1)
                    while _d <= _t:
                        if _d.strftime("%Y-%m-%d") in _cal:
                            _n += 1
                        _d += datetime.timedelta(days=1)
                    return _n
        except Exception:
            pass
        # 兜底：工作日 − 已知节假日
        _n, _d = 0, _b + datetime.timedelta(days=1)
        while _d <= _t:
            if _d.weekday() < 5 and _d.strftime("%Y-%m-%d") not in _HOLIDAY42:
                _n += 1
            _d += datetime.timedelta(days=1)
        return _n
    except Exception:
        return fallback


'''
s = s.replace(D, FN + D, 1)
io.open(path, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n# " + MARK + "\n")
print("OK 1: 持仓天数已改为交易日口径（报告同时打印自然日）→ " + path)

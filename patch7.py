# -*- coding: utf-8 -*-
"""V34.0 补丁 · 快照全挂时，用K线重建快照

2026-08-26 事故：
  [切换] 快照·新浪失败(CallTimeout)
  [切换] 快照·东财失败(ConnectionError)
  （跳过 同花顺：本版akshare无 stock_zh_a_spot_ths）
  🔴🔴 全部快照源失败 → 盯盘/游资/冷低早/止盈全部无法计算
  ★可信度评分 0/100，整份报告不可用于决策

★但同一份报告里：「⚡K线并发预热42只，耗时12秒」是成功的。
  K线接口通，快照接口挂 —— 两者走的是不同的服务端。
★所以：快照全挂时，用【清单里每只票的最新一根K线】重建一张迷你快照，
  至少让 盯盘/止盈/推荐跟踪表 这三个决策必需的模块能跑。

⚠️ 局限：重建的快照只覆盖【清单里的票】(约40只)，
   不能替代全市场5500只的快照，所以【冷低早】【选股器】仍然跑不了。
   但那两个模块本来就已经被判死(-2.9%和0%)，损失可接受。
"""
import io
import os

P = "scanner_cloud.py"
if not os.path.exists(P):
    print("no scanner_cloud.py")
    raise SystemExit(0)
s = io.open(P, encoding="utf-8").read()
n = 0

FUNC = '''

def _rebuild_spot_from_kline():
    """★★★V34.0：快照全挂时，用K线重建迷你快照★★★

    2026-08-26：三个快照源全挂，可信度0/100，整份报告作废。
    但K线并发预热42只是成功的 —— 两者走不同服务端。
    ★用清单里每只票的最新K线，重建一张只含清单标的的快照。
    ★这样【重点盯盘】【止盈体系】【推荐跟踪表】能继续跑。
    """
    rows = []
    try:
        codes = []
        for t in WATCH_STOCKS:
            try:
                codes.append((str(t[0])[-6:], str(t[1])))
            except Exception:
                continue
        try:
            for c6 in (_reco_load() or {}):
                codes.append((str(c6)[-6:], ""))
        except Exception:
            pass
        seen = set()
        uniq = []
        for c6, nm in codes:
            if c6 and c6 not in seen:
                seen.add(c6)
                uniq.append((c6, nm))
        if not uniq:
            return None

        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _one(c6, nm):
            try:
                k = get_kline(c6)
                if k is None or len(k) < 2:
                    return None
                last = k.iloc[-1]
                prev = k.iloc[-2]
                c_close = pick_col(k, ["收盘", "close"])
                c_amt = pick_col(k, ["成交额", "amount"])
                px = float(pd.to_numeric(last[c_close], errors="coerce"))
                pv = float(pd.to_numeric(prev[c_close], errors="coerce"))
                if px <= 0 or pv <= 0:
                    return None
                amt = 0.0
                if c_amt:
                    _a = pd.to_numeric(last[c_amt], errors="coerce")
                    if pd.notna(_a):
                        amt = float(_a)
                return {"代码": c6, "名称": nm or c6,
                        "最新价": px, "涨跌幅": (px / pv - 1) * 100,
                        "成交额": amt}
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=12) as ex:
            futs = [ex.submit(_one, c, n2) for c, n2 in uniq[:60]]
            for f in as_completed(futs, timeout=90):
                try:
                    r = f.result()
                    if r:
                        rows.append(r)
                except Exception:
                    continue
    except Exception:
        return None
    if len(rows) < 3:
        return None
    return pd.DataFrame(rows)

'''

if "_rebuild_spot_from_kline" not in s:
    anchor = "def get_spot("
    if anchor in s:
        s = s.replace(anchor, FUNC.strip() + "\n\n\ndef get_spot(", 1)
        n += 1
        print("OK 1: 重建函数已加")
    else:
        print("SKIP 1: 找不到 get_spot")
else:
    print("SKIP 1: 已存在")

A2 = '''  🔴🔴 全部快照源失败 → 盯盘/游资/冷低早/止盈全部无法计算'''
B2 = '''  🔴🔴 全部快照源失败 → 启用【K线重建】兜底'''
if A2 in s:
    s = s.replace(A2, B2)
    n += 1
    print("OK 2: 提示语已改")

A3 = '''    w("  🔴🔴 全部快照源失败 → 启用【K线重建】兜底")
    w("     这是地基级故障，本次报告不可用于决策")
    SPOT_DF = None
    return SPOT_DF'''
B3 = '''    w("  🔴🔴 全部快照源失败 → 启用【K线重建】兜底")
    try:
        _rb = _rebuild_spot_from_kline()
        if _rb is not None and len(_rb) >= 3:
            w("  ✅★V34.0 K线重建成功：%d只（只含清单标的）★" % len(_rb))
            w("     盯盘/止盈/推荐跟踪表 可以跑；")
            w("     ⚠️冷低早/选股器仍不可用（需要全市场5500只）")
            SPOT_DF = _rb
            globals()["_SPOT_REBUILT"] = True
            return SPOT_DF
    except Exception as _e:
        w("  ⚠️ K线重建也失败：%s" % type(_e).__name__)
    w("     这是地基级故障，本次报告不可用于决策")
    SPOT_DF = None
    return SPOT_DF'''
if A3 in s and "K线重建成功" not in s:
    s = s.replace(A3, B3, 1)
    n += 1
    print("OK 3: 兜底已接入")

if "V33.0 |" in s:
    s = s.replace("A股作战扫描器V33.0 |", "A股作战扫描器V34.0 |")
    n += 1

if n:
    io.open(P, "w", encoding="utf-8").write(s)
    print("DONE: %d changes" % n)
else:
    print("DONE: nothing")

# -*- coding: utf-8 -*-
"""
patch12_usa_date.py  ——  只做一件事：
修复【二、重点个股】把周五收盘价标成今天日期的BUG。

根因（scanner_usa.py 第549行）：
  _spot_one_by_one() 读的是日K的 df.iloc[-1]（周日跑=周五收盘），
  但它 return m[tk]=(px,pct) 只回两个值，日期被丢掉；
  _one() 取不到日期就补 now_beijing()，并标成"实时"
  → _stale_tag() 算出 gap=0 → 不报警
  → 指数标了⚠️距今2天，个股没标，同一份报告两套标准
  → 2026-09-04 就是这样误砍存储链

修法：新增全局 US_SPOT_DATE，逐个抓时把真实交易日存进去，
      _one() 优先用真实日期，取不到才退回今天。
"""
import io
import os
import sys

MARK = "★patch12：个股真实交易日★"
CANDIDATES = ["scanner_usa.py", "scanner_usa__1_.py"]

path = None
for c in CANDIDATES:
    if os.path.exists(c):
        path = c
        break
if path is None:
    print("跳过 patch12：找不到 scanner_usa.py")
    sys.exit(0)

with io.open(path, "r", encoding="utf-8") as f:
    s = f.read()

if MARK in s:
    print("OK 0: patch12 已打过，跳过（幂等）")
    sys.exit(0)

steps = 0

# ── 步骤1：声明全局日期表，挂在 US_QUOTE 旁边 ──
A1 = "US_QUOTE = {}"
if A1 in s:
    s = s.replace(
        A1,
        "US_QUOTE = {}\n"
        "# " + MARK + "\n"
        "US_SPOT_DATE = {}  # tk -> 'YYYY-MM-DD' 真实交易日（非今天）",
        1,
    )
    steps += 1
    print("OK 1: 已声明 US_SPOT_DATE 全局表")
else:
    print("!! 1: 锚点 US_QUOTE 未命中，patch12 中止")
    sys.exit(0)

# ── 步骤2：逐个抓时记下真实交易日 ──
A2 = (
    "                    m[tk.upper()] = "
    "(float(px), (float(px) - float(pv)) / float(pv) * 100)"
)
if A2 in s:
    s = s.replace(
        A2,
        A2 + "\n"
        "                    # " + MARK + "\n"
        "                    try:\n"
        "                        _cd = pick_col(df, [\"日期\", \"date\", \"时间\", \"time\"])\n"
        "                        if _cd:\n"
        "                            _dv = str(df.iloc[-1][_cd])[:10]\n"
        "                        else:\n"
        "                            _dv = str(df.index[-1])[:10]\n"
        "                        if len(_dv) == 10 and _dv[4] == \"-\":\n"
        "                            US_SPOT_DATE[tk.upper()] = _dv\n"
        "                    except Exception:\n"
        "                        pass",
        1,
    )
    steps += 1
    print("OK 2: 逐个抓已记录真实交易日")
else:
    print("!! 2: 锚点 m[tk.upper()] 未命中，patch12 中止")
    sys.exit(0)

# ── 步骤3：_one() 不许再盖今天的日期 ──
A3 = '                d = now_beijing().strftime("%Y-%m-%d")'
if s.count(A3) == 1:
    s = s.replace(
        A3,
        "                # " + MARK + "：优先用真实交易日，取不到才退回今天\n"
        "                d = US_SPOT_DATE.get(k) or US_SPOT_DATE.get(tk.upper()) \\\n"
        "                    or now_beijing().strftime(\"%Y-%m-%d\")",
        1,
    )
    steps += 1
    print("OK 3: _one() 已改用真实交易日")
else:
    print("!! 3: 锚点 d = now_beijing() 命中 %d 次（需恰好1次），patch12 中止"
          % s.count(A3))
    sys.exit(0)

# ── 步骤4：来源标签不许再无条件写"实时" ──
A4 = '                return px, pc, d, "", "实时"'
if A4 in s:
    s = s.replace(
        A4,
        "                # " + MARK + "：日期是补出来的就不许叫实时\n"
        "                _src = \"实时\" if (US_SPOT_DATE.get(k)\n"
        "                                  or US_SPOT_DATE.get(tk.upper())) else \"快照(日期存疑)\"\n"
        "                return px, pc, d, \"\", _src",
        1,
    )
    steps += 1
    print("OK 4: 来源标签已加存疑标记")
else:
    print("!! 4: 锚点 return px, pc, d 未命中（非致命，跳过）")

with io.open(path, "w", encoding="utf-8") as f:
    f.write(s)

print("patch12 完成，共生效 %d 步 → %s" % (steps, path))

# -*- coding: utf-8 -*-
"""
serenity_feed.py —— 白毛股神 Serenity (@aleabitoreddit) 全量信息源
2026-10-21 用户：『白毛股神的事，你要记下，想办法获取她所有信息』

为什么不再用 nitter/xcancel 镜像：
  us138 实测五个镜像全挂（410/451/ConnectionError/404），X 本身也拦抓取。
现在的数据源（按优先级）：
  ① GitHub 公开存档 yan-labs/serenity-aleabitoreddit
     —— 每天由机器人用 X API 同步，2026-10-21 时已存 6709 条全文推文
        （含回复、时间、互动数），最新一条 10-21 00:23 UTC
  ② 同一存档的 jsdelivr 镜像（raw.githubusercontent 偶发抽风时用）
  ③ 她的 Substack 长文 RSS：aleabitoreddit.substack.com/feed
输出：
  · build_section(hours) → 报告里的一节（最近N小时原创推文全文 + A股映射线索）
  · reports/白毛股神_最新.txt（单独一份，方便直接发给AI）
用法：被 patch_usa54 注入到 A股 / 美股 两个扫描器里，每次扫描都跑。
"""
import datetime
import html
import json
import os
import re

ARCHIVE_URLS = [
    "https://raw.githubusercontent.com/yan-labs/serenity-aleabitoreddit/main/data/aleabitoreddit_tweets.json",
    "https://cdn.jsdelivr.net/gh/yan-labs/serenity-aleabitoreddit@main/data/aleabitoreddit_tweets.json",
]
STATE_URL = "https://raw.githubusercontent.com/yan-labs/serenity-aleabitoreddit/main/data/sync_state.json"
SUBSTACK_RSS = "https://aleabitoreddit.substack.com/feed"

# 她常谈的主题 → A股对应环节（只是找线索的方向，买前仍要过死穴四问）
THEME_TO_A = [
    ("存储/HBM", r"\bmemory\b|HBM|DRAM|NAND|\$MU\b|\$SNDK|SK ?Hynix|\$SKHY|Samsung",
     "存储链：香农芯创300475 江波龙301308 佰维存储688525 兆易创新603986 德明利001309"),
    ("激光/光芯片/InP", r"laser|\bCW\b|EML|DFB|InP|\$LITE|\$AAOI|\$SIVE|\$AXTI|\$COHR|photonic",
     "光芯片/衬底：源杰科技688498 长光华芯688048 仕佳光子688313 云南锗业002428"),
    ("CPO/光模块", r"\bCPO\b|\bNPO\b|transceiver|pluggable|1\.6T|3\.2T",
     "光模块/CPO：中际旭创300308 新易盛300502 天孚通信300394"),
    ("人形机器人/物理AI", r"humanoid|robot|physical AI|Optimus|Unitree|Agility|\$AGLT|\$CCXI|embodied",
     "机器人链：雷赛智能002979 双环传动002472 拓普集团601689 绿的谐波688017 长盈精密300115"),
    ("激光雷达", r"LiDAR|\$AEVA|FMCW",
     "激光雷达：禾赛(美股HSAI)/速腾(港股) → A股上游看光芯片"),
    ("算力/云/数据中心", r"capex|neocloud|\$NBIS|\$CRWV|\$IREN|data ?center|\$SPCX|GPU|\$NVDA",
     "算力链：工业富联601138 浪潮信息000977 + 液冷英维克002837"),
    ("CPU/ARM", r"\bCPU\b|\$ARM\b|\$INTC|\$AMD\b",
     "CPU/接口：澜起科技688008 海光信息688041"),
    ("衬底/封装材料", r"substrate|ABF|glass|T-?glass|PCB",
     "载板/玻纤：深南电路002916 中材科技002080 凯盛科技600552"),
]


def _get(url, timeout=40):
    import requests
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r


def _load_archive(log):
    for u in ARCHIVE_URLS:
        try:
            data = _get(u, timeout=60).json()
            if isinstance(data, list) and data:
                log.append(f"  来源：{u.split('/')[2]} 公开存档（共{len(data)}条）")
                return data
        except Exception as e:
            log.append(f"  [切换] {u.split('/')[2]} 失败：{type(e).__name__}")
    return []


def _load_state():
    try:
        return _get(STATE_URL, timeout=20).json()
    except Exception:
        return {}


def _load_substack(n=5):
    out = []
    try:
        txt = _get(SUBSTACK_RSS, timeout=20).text
        for it in re.findall(r"<item>(.*?)</item>", txt, re.S)[:n]:
            t = re.search(r"<title>(.*?)</title>", it, re.S)
            d = re.search(r"<pubDate>(.*?)</pubDate>", it, re.S)
            l = re.search(r"<link>(.*?)</link>", it, re.S)
            t = html.unescape(re.sub(r"<!\[CDATA\[|\]\]>|<[^>]+>", "", t.group(1) if t else "")).strip()
            out.append(((d.group(1)[5:22] if d else "?"), t, (l.group(1).strip() if l else "")))
    except Exception:
        pass
    return out


def _bj(iso):
    try:
        dt = datetime.datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")
        return dt + datetime.timedelta(hours=8)
    except Exception:
        return None


def build_section(hours=48, max_posts=25, write_file=True):
    """返回报告行列表。绝不抛异常。"""
    L = ["", "=" * 60,
         "🐑【白毛股神 Serenity @aleabitoreddit · 全量存档】AI/半导体供应链瓶颈",
         "=" * 60]
    try:
        log = []
        data = _load_archive(log)
        L += log
        st = _load_state()
        if st:
            L.append(f"  存档最近同步：{st.get('last_update_time', '?')} UTC"
                     f"（状态 {st.get('source_health', {}).get('status', '?')}）")
        if not data:
            L.append("  🔴 存档读不到 → 请用户截图她的X主页发给AI")
            return L
        now = datetime.datetime.utcnow()
        cut = (now - datetime.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
        rec = [x for x in data if (x.get("createdAtISO") or "") >= cut
               and not x.get("isRetweet")]
        rec.sort(key=lambda x: x.get("createdAtISO") or "", reverse=True)
        orig = [x for x in rec if not x.get("isReply")]
        reps = [x for x in rec if x.get("isReply")]
        L.append(f"  最近{hours}小时：原创 {len(orig)} 条 / 回复 {len(reps)} 条（北京时间）")

        # 主题热度 + A股映射
        blob = " ".join(x.get("text", "") for x in rec)
        hits = []
        for name, pat, a in THEME_TO_A:
            n = len(re.findall(pat, blob, re.I))
            if n:
                hits.append((n, name, a))
        if hits:
            L.append("")
            L.append("  ★她这两天在讲什么（提及次数）→ A股对应环节（线索，非买入信号）")
            for n, name, a in sorted(hits, reverse=True):
                L.append(f"    {name} ×{n} → {a}")

        # 全部提到的美股代码
        tk = {}
        for x in rec:
            for t in set(re.findall(r"\$[A-Z]{1,6}\b", x.get("text", ""))):
                tk[t] = tk.get(t, 0) + 1
        if tk:
            L.append("  提到的代码：" + " ".join(f"{k}×{v}" for k, v in
                                          sorted(tk.items(), key=lambda kv: -kv[1])[:20]))

        L.append("")
        L.append("  ── 原创推文（全文，新→旧）──")
        for x in (orig + reps)[:max_posts]:
            bj = _bj(x.get("createdAtISO", ""))
            ts = bj.strftime("%m-%d %H:%M") if bj else "?"
            kind = "↩回复" if x.get("isReply") else "📝原创"
            txt = re.sub(r"https://t\.co/\S+", "", x.get("text", "")).strip()
            txt = re.sub(r"\s+", " ", txt)[:700]
            L.append(f"  [{ts}] {kind} {txt}")
            L.append(f"      https://x.com/aleabitoreddit/status/{x.get('id')}")

        sub = _load_substack()
        if sub:
            L.append("")
            L.append("  ── Substack 长文/笔记（最新5篇）──")
            for d, t, l in sub:
                L.append(f"  [{d}] {t}  {l}")

        L.append("")
        L.append("  ★AI必做：①她提到的美股环节 → 找A股同环节、还没涨的票")
        L.append("           ②她直接点名的A股当天常20cm，不追；③她的战绩无独立审计，只当雷达")
    except Exception as e:
        L.append(f"  [serenity_feed] 失败：{type(e).__name__}: {e}")
    finally:
        if write_file:
            try:
                os.makedirs("reports", exist_ok=True)
                with open("reports/白毛股神_最新.txt", "w", encoding="utf-8") as f:
                    f.write("\n".join(L))
            except Exception:
                pass
    return L


if __name__ == "__main__":
    print("\n".join(build_section(hours=int(os.environ.get("SERENITY_HOURS", "72")))))

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

v3 2026-10-30：v2两路（x.com 403、syndication 429）实测都被拦 → 加11个RSS镜像轮询 + syndication三地址退避重试，
  每路成败都写进报告，用数据找出哪条路活着。
v2 2026-10-29：存档机器人10/28后停更（最新一条10-27 16:28 UTC），
  谷歌/微软财报当晚她说了什么完全看不到。用户：『白毛的，想办法弄到资讯』。
  → 加【实时补抓层】：存档最新一条距今>6小时，就在 GitHub Actions 里直接抓：
     ④ x.com 公开主页 HTML + r.jina.ai 阅读器（用存档作者写好的解析器，
        锁定在固定 commit，不跟随对方后续改动，防供应链风险）
     ⑤ syndication.twitter.com 公开时间线（嵌入挂件用的接口，免登录）
  抓到的按 id 去重合并进存档，报告里标【🔴实时】，并写明存档停更多少小时。
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


YAN_SHA = "37fe3956de4259479d22d46ebcb22a45372a86d9"
YAN_FETCHER = ("https://raw.githubusercontent.com/yan-labs/serenity-aleabitoreddit/"
               + YAN_SHA + "/scripts/public_x_profile.py")
SYND_URL = "https://syndication.twitter.com/srv/timeline-profile/screen-name/aleabitoreddit"
X_USER, X_UID, X_NAME = "aleabitoreddit", "1940360837547565056", "Serenity"


def _live_xprofile(log):
    """x.com 公开主页 + jina 阅读器（存档作者的解析器，锁定commit）。"""
    import importlib.util
    import tempfile
    code = _get(YAN_FETCHER, timeout=30).text
    d = tempfile.mkdtemp()
    p = os.path.join(d, "public_x_profile.py")
    with open(p, "w", encoding="utf-8") as f:
        f.write(code)
    spec = importlib.util.spec_from_file_location("_sf_pxp", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    posts, diag = m.fetch_public_posts(X_USER, X_UID, X_NAME, limit=12)
    errs = diag.get("errors") or []
    log.append(f"  实时补抓④[x.com/jina]：{len(posts)}条（{diag.get('source') or diag.get('profile_source') or '?'}）"
               + (f" 错误{len(errs)}：{str(errs[0])[:80]}" if errs else ""))
    return posts


SYND_URLS = [
    "https://syndication.twitter.com/srv/timeline-profile/screen-name/aleabitoreddit",
    "https://syndication.twitter.com/srv/timeline-profile/screen-name/aleabitoreddit?showReplies=true",
    "https://syndication.twimg.com/srv/timeline-profile/screen-name/aleabitoreddit",
]


def _parse_synd(t):
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', t, re.S)
    if not m:
        return []
    j = json.loads(m.group(1))
    ents = (((j.get("props") or {}).get("pageProps") or {}).get("timeline") or {}).get("entries") or []
    out = []
    for e in ents:
        tw = ((e or {}).get("content") or {}).get("tweet") or {}
        if not tw or not tw.get("id_str"):
            continue
        try:
            dt = datetime.datetime.strptime(tw["created_at"], "%a %b %d %H:%M:%S %z %Y")
            iso = dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            continue
        out.append({"id": tw["id_str"], "text": tw.get("full_text") or tw.get("text") or "",
                    "createdAtISO": iso,
                    "isReply": bool(tw.get("in_reply_to_status_id_str")),
                    "isRetweet": bool(tw.get("retweeted_status"))})
    return out


def _live_synd(log):
    """syndication 公开时间线（网页嵌入挂件接口）。v3：三个地址轮流试，429 退避重试。"""
    import time
    for u in SYND_URLS:
        for attempt in range(2):
            try:
                r = __import__("requests").get(u, timeout=25, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
                    "Accept-Language": "en-US,en;q=0.9"})
                if r.status_code == 429:
                    time.sleep(4 + attempt * 6)
                    continue
                r.raise_for_status()
                out = _parse_synd(r.text)
                log.append(f"  实时补抓⑤[syndication] {u.split('/')[2]}：{len(out)}条")
                if out:
                    return out
                break
            except Exception as e:
                log.append(f"  实时补抓⑤[syndication] {u.split('/')[2]} 失败：{type(e).__name__}: {str(e)[:60]}")
                break
        else:
            log.append(f"  实时补抓⑤[syndication] {u.split('/')[2]}：连续429（限流）")
    return []


# v3：RSS 镜像（nitter/RSSHub 类，各家死活不定，全部轮一遍，谁活用谁）
RSS_MIRRORS = [
    "https://nitter.net/aleabitoreddit/rss",
    "https://xcancel.com/aleabitoreddit/rss",
    "https://nitter.poast.org/aleabitoreddit/rss",
    "https://nitter.privacydev.net/aleabitoreddit/rss",
    "https://nitter.tiekoetter.com/aleabitoreddit/rss",
    "https://nitter.space/aleabitoreddit/rss",
    "https://lightbrd.com/aleabitoreddit/rss",
    "https://nitter.kuuro.net/aleabitoreddit/rss",
    "https://nuku.trabun.org/aleabitoreddit/rss",
    "https://rsshub.app/twitter/user/aleabitoreddit",
    "https://rsshub.rssforever.com/twitter/user/aleabitoreddit",
]


def _live_mirrors(log):
    from email.utils import parsedate_to_datetime
    ok_src, fails = None, []
    for u in RSS_MIRRORS:
        host = u.split("/")[2]
        try:
            r = __import__("requests").get(u, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200 or "<item" not in r.text:
                fails.append(f"{host}:{r.status_code}")
                continue
            out = []
            for it in re.findall(r"<item>(.*?)</item>", r.text, re.S)[:30]:
                link = re.search(r"<link>(.*?)</link>", it, re.S)
                sid = re.search(r"/status/(\d+)", link.group(1) if link else "")
                d = re.search(r"<pubDate>(.*?)</pubDate>", it, re.S)
                ttl = re.search(r"<title>(.*?)</title>", it, re.S)
                desc = re.search(r"<description>(.*?)</description>", it, re.S)
                if not sid or not d:
                    continue
                txt = html.unescape(re.sub(r"<!\[CDATA\[|\]\]>|<[^>]+>", " ",
                                           (desc.group(1) if desc else (ttl.group(1) if ttl else "")))).strip()
                try:
                    iso = parsedate_to_datetime(d.group(1).strip()).astimezone(
                        datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                except Exception:
                    continue
                t0 = html.unescape(ttl.group(1)) if ttl else ""
                out.append({"id": sid.group(1), "text": re.sub(r"\s+", " ", txt)[:1500], "createdAtISO": iso,
                            "isReply": t0.startswith("R to @") or txt.startswith("@"),
                            "isRetweet": t0.startswith("RT by")})
            if out:
                ok_src = host
                log.append(f"  实时补抓⑥[RSS镜像] ✅{host}：{len(out)}条（其余已试失败：{'、'.join(fails) or '无'}）")
                return out
            fails.append(f"{host}:空")
        except Exception as e:
            fails.append(f"{host}:{type(e).__name__}")
    log.append("  实时补抓⑥[RSS镜像] 全部失败：" + "、".join(fails))
    return []


def _merge_live(data, log, stale_hours=6):
    """存档停更超过 stale_hours 小时 → 实时补抓并按 id 去重合并。返回(合并后, 新增条数, 存档停更小时)。"""
    latest = max((x.get("createdAtISO") or "" for x in data), default="")
    age = None
    try:
        age = (datetime.datetime.utcnow()
               - datetime.datetime.strptime(latest[:19], "%Y-%m-%dT%H:%M:%S")).total_seconds() / 3600
    except Exception:
        pass
    if age is not None and age <= stale_hours:
        return data, 0, age
    log.append(f"  ⚠️ 存档最新一条 {latest[:16]} UTC，已停更约{age:.0f}小时 → 启动实时补抓" if age is not None
               else "  ⚠️ 存档时间读不到 → 启动实时补抓")
    seen = {str(x.get("id")) for x in data}
    added = 0
    for fn in (_live_mirrors, _live_synd, _live_xprofile):
        try:
            for p in fn(log):
                pid = str(p.get("id") or "")
                if pid and pid not in seen and p.get("createdAtISO"):
                    p = dict(p)
                    p["_live"] = True
                    data.append(p)
                    seen.add(pid)
                    added += 1
        except Exception as e:
            log.append(f"  [实时补抓] {fn.__name__} 失败：{type(e).__name__}: {str(e)[:80]}")
    if not added:
        log.append("  🔴 实时补抓也没拿到新推文 → 请用户截图她X主页最新几条发给AI")
    return data, added, age


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
        live_log = []
        data, added, age = _merge_live(list(data), live_log)
        L += live_log
        if added:
            L.append(f"  ✅ 实时补抓新增 {added} 条（下面标【🔴实时】的就是存档里还没有的）")
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
            kind = ("🔴实时" if x.get("_live") else "") + ("↩回复" if x.get("isReply") else "📝原创")
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

# -*- coding: utf-8 -*-
"""
patch_usa52_serenity.py —— 美股报告加【白毛股神 Serenity(@aleabitoreddit) 最新推文】
用户 2026-10-20：『你为啥现在不查看白毛股神的x信息？』
AI 的抓取器读不了 x.com（被拦），所以让 GitHub 服务器去读 RSS 镜像。
依次尝试多个镜像，成功一个即停；全失败就在报告里写清楚是哪几个失败，不静默。
"""
import io, os, sys
MARK = "patch_usa52_serenity"
path = next((c for c in ["scanner_usa.py", "scanner_usa__1_.py"] if os.path.exists(c)), None)
if not path:
    print("跳过 patch_usa52：找不到 scanner_usa.py"); sys.exit(0)
s = io.open(path, encoding="utf-8").read()
if MARK in s:
    print("OK 0: patch_usa52 已打过"); sys.exit(0)
A = '''    os.makedirs("reports", exist_ok=True)
    text = "\\n".join(REPORT)
    date = bj.strftime("%Y%m%d")'''
if s.count(A) != 1:
    print("!! patch_usa52 中止：报告写出锚点命中 %d 次" % s.count(A)); sys.exit(0)
NEW = '''    # ===== ''' + MARK + ''' =====
    try:
        import re as _re52, html as _h52, requests as _rq52
        _srcs52 = [
            "https://nitter.net/aleabitoreddit/rss",
            "https://xcancel.com/aleabitoreddit/rss",
            "https://nitter.poast.org/aleabitoreddit/rss",
            "https://nitter.privacydev.net/aleabitoreddit/rss",
            "https://rsshub.app/twitter/user/aleabitoreddit",
        ]
        _items52, _fail52, _ok52 = [], [], ""
        for _u in _srcs52:
            try:
                _r = _rq52.get(_u, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
                if _r.status_code != 200 or "<item" not in _r.text:
                    _fail52.append(f"{_u.split('/')[2]}:{_r.status_code}")
                    continue
                for _it in _re52.findall(r"<item>(.*?)</item>", _r.text, _re52.S)[:12]:
                    _t = _re52.search(r"<title>(.*?)</title>", _it, _re52.S)
                    _d = _re52.search(r"<pubDate>(.*?)</pubDate>", _it, _re52.S)
                    _t = _h52.unescape(_re52.sub(r"<!\\[CDATA\\[|\\]\\]>|<[^>]+>", "", _t.group(1) if _t else "")).strip()
                    _items52.append(((_d.group(1)[5:22] if _d else "?"), _re52.sub(r"\\s+", " ", _t)[:220]))
                _ok52 = _u.split("/")[2]
                break
            except Exception as _e:
                _fail52.append(f"{_u.split('/')[2]}:{type(_e).__name__}")
        w("")
        w("=" * 60)
        w("🐑【白毛股神 Serenity @aleabitoreddit 最新推文】AI/半导体供应链瓶颈")
        w("=" * 60)
        if _items52:
            w(f"  来源：{_ok52}（最近{len(_items52)}条，时间为GMT）")
            for _d, _t in _items52:
                _tk = " ".join(sorted(set(_re52.findall(r"\\$[A-Z]{1,6}", _t))))
                w(f"  [{_d}] {_t}" + (f"  ⟶ 提到 {_tk}" if _tk else ""))
            w("  ★AI必做：她点名的公司 → 找A股同一供应链环节、还没涨的票；她直接点名的A股当天常20cm，不追")
        else:
            w("  ⚠️ 所有镜像都没读到：" + "；".join(_fail52))
    except Exception as _e52:
        w(f"  [patch_usa52] 白毛股神模块失败：{type(_e52).__name__}: {_e52}")
    # ===== ''' + MARK + ''' 结束 =====
''' + A
s = s.replace(A, NEW, 1)
io.open(path, "w", encoding="utf-8").write(s.rstrip("\n") + "\n\n# " + MARK + "\n")
print("OK 1: 美股报告将附带白毛股神最新推文 → " + path)

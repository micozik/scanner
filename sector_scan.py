# -*- coding: utf-8 -*-
"""
板块深扫（2026-11-05 新建）
用户："全方位分析板块里面的所有股票，再找出适合的机会" → "现在改"

流程：板块名 → 取全部成分股（新浪行业/概念 → 东财兜底，带同义词）
     → 腾讯批量行情（价/涨幅/成交额/市值/PE）→ 腾讯日K（位置/均线/量能）
     → 按"抢先"打分（低位、还没涨、资金放量、趋势转好、不追高）
     → 输出每个板块全部成分股排名 + 全场前8只 → 第二步交给 查股票 深查
输出：reports/板块深扫_最新.txt ｜ reports/_sector_top.txt（前8只代码）
"""
import os
import re
import json
import time
import datetime
import urllib.request
from concurrent.futures import ThreadPoolExecutor

T0 = time.time()
SEEDSET = set()
LOG = []
L = []


def w(s=""):
    L.append(str(s))
    print(s)


def note(s):
    LOG.append(str(s)[:120])


def bj_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=8)


# 同义词：用户说的板块名 → 新浪/东财里可能的叫法
SYN = {
    "半导体": ["半导体", "芯片", "集成电路", "电子器件", "半导体及元件"],
    "芯片": ["芯片", "半导体", "集成电路"],
    "存储": ["存储芯片", "存储器", "存储", "闪存"],
    "半导体设备": ["半导体设备", "光刻机", "半导体"],
    "光伏": ["光伏", "太阳能", "光伏设备", "HJT", "异质结", "BC电池", "钙钛矿"],
    "风电": ["风电", "风能", "风电设备"],
    "储能": ["储能", "电化学储能"],
    "电池": ["锂电池", "电池", "锂电", "固态电池", "动力电池"],
    "证券": ["证券", "券商"],
    "券商": ["证券", "券商"],
    "黄金": ["黄金", "贵金属"],
    "电力设备": ["电力设备", "电网", "特高压", "电气设备"],
    "机器人": ["机器人", "人形机器人", "减速器"],
    "AI": ["人工智能", "AI", "ChatGPT", "算力"],
    "算力": ["算力", "数据中心", "服务器", "液冷"],
    "军工": ["军工", "国防", "航天", "航空"],
    "医药": ["创新药", "医药", "生物医药", "化学制药"],
    "航空": ["航空", "民航", "机场"],
}


# ★11/05 晚：新浪概念太杂/东财限流时用的自建产业链名单（主业确认过，算"主营相关✅"）
SEED = {
    "存储": "603986,301308,688525,001309,300042,688008,300223,688110,688766,300302,000021,688416,688123,300672,300475",
    "储能": "300274,300750,300014,002074,300438,688063,002518,300068,002335,300827,688390,605117,300763,688676,002121",
    "半导体设备": "002371,688012,688072,688120,688082,300567,688037,688200,603690,688361,300316,688147,300604,688630",
    "电网设备": "600406,600089,601179,600312,000400,002028,601877,002270,688676,300001,600468,603606,600522,600487,002309",
    "光伏": "601012,600438,688223,002459,300274,603806,688599,600732,002865,300763,605117,601865,002129,300118",
    "风电": "002202,601615,603606,300129,002531,603218,300772,601016,603985,002487,688349",
    # 11/9 新增：新浪/东财成分接口限流时，这几个板块拿到0只 → 自建名单兜底
    "通信设备": "000063,600498,600522,600487,688387,000938,300308,300502,300394,002281,000988,301165,601869,688702,603083",
    "印制电路板": "002463,300476,002916,002384,002938,600183,603228,603920,001389,002913,002436,002815,688183,600601,688519",
    "电子化学品": "002409,300054,688019,300666,603650,300346,300655,300236,688268,688106,688545,688300,300398,688549,300429",
    "军工电子": "002179,000733,002049,603267,603678,688375,688002,002414,002025,300395,688385,301306,688636,300474,301050",
}
SEED["6G"] = SEED["通信设备"]
SEED["通信"] = SEED["通信设备"]
SEED["PCB"] = SEED["印制电路板"]
SEED["元件"] = SEED["印制电路板"]
SEED["电网"] = SEED["电网设备"]
SEED["芯片设备"] = SEED["半导体设备"]
SEED["存储芯片"] = SEED["存储"]


def names_for(q):
    out = [q]
    for k, v in SYN.items():
        if k in q or q in k:
            out += v
    seen = []
    for x in out:
        if x not in seen:
            seen.append(x)
    return seen


def nz(s):
    return re.sub(r"[\s（）()·\-_]", "", str(s)).replace("概念", "").replace("板块", "").replace("行业", "")


def _get(url, ref="https://finance.sina.com.cn/", timeout=8, enc=None):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": ref})
    raw = urllib.request.urlopen(req, timeout=timeout).read()
    if enc:
        return raw.decode(enc, "ignore")
    try:
        return raw.decode("utf-8")
    except Exception:
        return raw.decode("gbk", "ignore")


def code_of(x):
    d = "".join(c for c in str(x) if c.isdigit())
    return d[-6:] if len(d) >= 6 else ""


def cons_sina(ak, q):
    """新浪：stock_sector_spot 拿板块名单 → stock_sector_detail 拿成分股"""
    got = {}
    names = names_for(q)
    for ind in ("新浪行业", "概念", "行业"):
        try:
            lst = ak.stock_sector_spot(indicator=ind)
        except Exception as e:
            note("新浪%s名单失败 %s" % (ind, type(e).__name__))
            continue
        if lst is None or len(lst) == 0:
            continue
        cn = next((c for c in ("板块", "name", "板块名称") if c in lst.columns), None)
        cl = next((c for c in ("label", "板块代码", "code") if c in lst.columns), None)
        if not cn or not cl:
            note("新浪%s列名 %s" % (ind, list(lst.columns)[:5]))
            continue
        hits = []
        for _, r in lst.iterrows():
            v = nz(r[cn])
            if not v:
                continue
            for nm in names:
                t = nz(nm)
                if t and (v == t or t in v or (len(v) >= 2 and v in t)):
                    hits.append((str(r[cn]), str(r[cl])))
                    break
        for bname, lab in hits[:4]:
            try:
                df = ak.stock_sector_detail(sector=lab)
            except Exception as e:
                note("新浪成分 %s 失败 %s" % (bname, type(e).__name__))
                continue
            if df is None or len(df) == 0:
                continue
            cc = next((c for c in ("code", "symbol", "代码") if c in df.columns), None)
            cnm = next((c for c in ("name", "名称") if c in df.columns), None)
            if not cc:
                continue
            for _, r in df.iterrows():
                cd = code_of(r[cc])
                if cd:
                    got[cd] = str(r[cnm]) if cnm else cd
            note("新浪%s『%s』%d只" % (ind, bname, len(df)))
        if len(got) >= 15:
            break
    return got


def cons_em(ak, q):
    got = {}
    for nm in names_for(q)[:3]:
        for fn in (ak.stock_board_industry_cons_em, ak.stock_board_concept_cons_em):
            try:
                df = fn(symbol=nm)
            except Exception as e:
                note("东财成分 %s 失败 %s" % (nm, type(e).__name__))
                continue
            if df is None or len(df) == 0:
                continue
            cc = next((c for c in ("代码", "股票代码") if c in df.columns), None)
            cnm = next((c for c in ("名称", "股票简称") if c in df.columns), None)
            for _, r in df.iterrows():
                cd = code_of(r[cc])
                if cd:
                    got[cd] = str(r[cnm]) if cnm else cd
            if got:
                note("东财『%s』%d只" % (nm, len(got)))
                return got
    return got


def mk(code):
    return ("sh" if code.startswith(("6", "9")) and not code.startswith("92")
            else ("bj" if code[:2] in ("92", "83", "87", "43") else "sz")) + code


def tx_quote(codes):
    out = {}
    for i in range(0, len(codes), 60):
        part = codes[i:i + 60]
        try:
            txt = _get("https://qt.gtimg.cn/q=" + ",".join(mk(c) for c in part), ref="https://gu.qq.com/", enc="gbk")
        except Exception as e:
            note("腾讯行情失败 %s" % type(e).__name__)
            continue
        for line in txt.split(";"):
            if '="' not in line:
                continue
            f = line.split('="', 1)[1].rstrip('"').strip().split("~")
            if len(f) < 46:
                continue

            def fl(j):
                try:
                    return float(f[j])
                except Exception:
                    return None
            out[f[2][-6:]] = {"name": f[1].strip(), "price": fl(3), "pct": fl(32),
                              "amt": (fl(37) or 0) / 1e4, "turn": fl(38), "pe": fl(39),
                              "mcap": fl(45), "vol": fl(36)}
    return out


def tx_kline(code):
    m = mk(code)
    try:
        d = json.loads(_get("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=%s,day,,,140,qfq" % m,
                            ref="https://gu.qq.com/"))["data"][m]
        rows = d.get("qfqday") or d.get("day") or []
        return [(r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])) for r in rows]
    except Exception:
        return []


def feats(k):
    if len(k) < 65:
        return None
    c = [x[2] for x in k]
    v = [x[5] for x in k]
    last = c[-1]
    ma20 = sum(c[-20:]) / 20
    ma20p = sum(c[-25:-5]) / 20
    ma60 = sum(c[-60:]) / 60
    hi60 = max(x[3] for x in k[-60:])
    lo60 = min(x[4] for x in k[-60:])
    d5 = (last / c[-6] - 1) * 100
    d20 = (last / c[-21] - 1) * 100
    v5 = sum(v[-5:]) / 5
    v60 = sum(v[-60:]) / 60
    vt = v[-1] / (sum(v[-6:-1]) / 5) if sum(v[-6:-1]) else None
    # 近5日"涨日量/跌日量"：>1.2 = 涨的时候放量、跌的时候缩量 = 暗流吸筹
    up = sum(v[i] for i in range(-5, 0) if c[i] > c[i - 1])
    dn = sum(v[i] for i in range(-5, 0) if c[i] <= c[i - 1])
    return {"last": last, "ma20": ma20, "ma20_up": ma20 > ma20p, "ma60": ma60,
            "from_hi": (last / hi60 - 1) * 100, "from_lo": (last / lo60 - 1) * 100,
            "d5": d5, "d20": d20, "volr": v5 / v60 if v60 else None, "vt": vt,
            "udr": (up / dn) if dn else (9.9 if up else None)}


def score(q, f):
    s, why = 0, []
    pct = q.get("pct") or 0
    if -35 <= f["from_hi"] <= -10:
        s += 2; why.append("低位(距高%.0f%%)" % f["from_hi"])
    elif f["from_hi"] > -5:
        s -= 1; why.append("高位")
    elif f["from_hi"] < -45:
        s -= 1; why.append("跌太深")
    if -3 <= f["d5"] <= 5:
        s += 1; why.append("5日没大涨")
    elif f["d5"] > 12:
        s -= 2; why.append("5日已涨%.0f%%" % f["d5"])
    if f["last"] > f["ma20"] and f["ma20_up"]:
        s += 2; why.append("站上向上20日线")
    elif f["last"] > f["ma20"]:
        s += 1; why.append("站上20日线")
    elif not f["ma20_up"]:
        s -= 1; why.append("下行20日线下")
    if f["udr"] and f["udr"] >= 1.3:
        s += 2; why.append("涨放量跌缩量(吸筹%.1f)" % f["udr"])
    if 0 < pct <= 4 and f["vt"] and f["vt"] >= 1.3:
        s += 1; why.append("今日放量小涨")
    if pct > 4:
        s -= 2; why.append("今日+%.1f%%不追" % pct)
    if pct >= 9.5:
        s -= 5
    pe = q.get("pe")
    if pe is not None and 0 < pe <= 40:
        s += 1; why.append("PE%.0f" % pe)
    elif pe is not None and pe <= 0:
        s -= 1; why.append("亏损")
    if (q.get("amt") or 0) >= 3:
        s += 1; why.append("成交%.0f亿" % q["amt"])
    return s, why


def main():
    try:
        import akshare as ak
    except Exception:
        ak = None
    raw = os.environ.get("SECTORS", "").strip()
    secs = [x.strip() for x in re.split(r"[,，\s;；]+", raw) if x.strip()][:5]
    now = bj_now()
    w("=" * 72)
    w("🧭【板块深扫】北京 %s ｜ 板块：%s" % (now.strftime("%Y-%m-%d %H:%M"), "、".join(secs) or "（空）"))
    w("   打分=抢先逻辑：低位+还没大涨+站上向上均线+涨放量跌缩量(吸筹)+不追高+PE合理+有流动性")
    w("=" * 72)
    if not secs:
        w("没填板块"); return []
    pool = {}
    sec_of = {}
    for q in secs:
        got = {}
        if all(code_of(x) for x in [q]) and len(code_of(q)) == 6 and q.isdigit():
            got = {q: q}
        seed_codes = []
        for sk, sv in SEED.items():
            if sk == q or sk in q or q in sk:
                seed_codes = sv.split(",")
                break
        if not got and seed_codes and q in ("存储", "储能", "半导体设备", "芯片设备", "存储芯片", "电网", "电网设备"):
            got = {c: c for c in seed_codes}          # 新浪概念对这些板块太杂/取不到 → 只用自建名单
            note("【%s】用自建产业链名单%d只" % (q, len(got)))
        if not got and ak is not None:
            got = cons_sina(ak, q)
            if len(got) < 5:
                got.update(cons_em(ak, q))
        for c in seed_codes:
            got.setdefault(c, c)
            SEEDSET.add(c)
        w("")
        w("◆ 板块【%s】成分 %d 只（源：%s）" % (q, len(got), "；".join(LOG[-3:]) if LOG else "—"))
        _ordered = [x for x in got.items() if x[0] in SEEDSET] + [x for x in got.items() if x[0] not in SEEDSET]
        for cd, nm in _ordered[:160]:   # ★每个板块最多160只，避免前面的板块把名额吃光
            pool.setdefault(cd, nm)
            sec_of.setdefault(cd, q)
    codes = [c for c in pool if not c.startswith(("8", "4", "92"))][:800]
    qt = tx_quote(codes)
    keep = [c for c in codes if c in qt and qt[c]["price"] and "ST" not in qt[c]["name"].upper()
            and (qt[c]["amt"] or 0) >= 1.0]
    w("")
    w("行情取到 %d 只；去掉ST/停牌/成交<1亿后 %d 只" % (len(qt), len(keep)))
    with ThreadPoolExecutor(max_workers=12) as ex:
        ks = dict(zip(keep, ex.map(tx_kline, keep)))
    rows = []
    for c in keep:
        f = feats(ks.get(c) or [])
        if not f:
            continue
        s, why = score(qt[c], f)
        rows.append((s, c, qt[c], f, why))
    rows.sort(key=lambda x: -x[0])
    for q in secs:
        rs = [r for r in rows if sec_of.get(r[1]) == q]
        w("")
        w("━━ 【%s】全部 %d 只按分排名 ━━" % (q, len(rs)))
        w("  分  名称      代码    现价    今日   5日    距60日高  量比5/60 吸筹比  成交亿  PE   理由")
        for s, c, qd, f, why in rs[:40]:
            w("  %+2d %-8s %s %7.2f %+6.1f%% %+6.1f%% %+7.1f%%  %5.2f   %4.1f  %6.1f %5s  %s" % (
                s, qd["name"][:8], c, qd["price"], qd["pct"] or 0, f["d5"], f["from_hi"],
                f["volr"] or 0, f["udr"] or 0, qd["amt"] or 0,
                ("%.0f" % qd["pe"]) if qd.get("pe") else "—", "、".join(why)))
        if len(rs) > 40:
            w("  …其余 %d 只分数更低，略" % (len(rs) - 40))
    # ★主营相关性：新浪概念成分很杂（光伏概念里混进医药股）→ 每板块前15只查主营，关键词不沾边的剔掉
    rel = {}

    def _biz(c):
        try:
            df = ak.stock_zyjs_ths(symbol=c)
            if df is not None and len(df):
                return " ".join(str(x) for x in df.iloc[0].tolist())
        except Exception:
            pass
        return ""
    cand = []
    for q in secs:
        cand += [r[1] for r in [x for x in rows if sec_of.get(x[1]) == q][:15]]
    if ak is not None and cand:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for c, b in zip(cand, ex.map(_biz, cand)):
                rel[c] = b
    KW = {q: [nz(x) for x in names_for(q)] + [q] for q in secs}
    KW_EXTRA = {"光伏": ["组件", "硅片", "电池片", "逆变器", "光伏玻璃", "胶膜", "多晶硅"],
                "储能": ["储能", "电池", "逆变器", "PCS"], "存储": ["存储", "DRAM", "NAND", "NOR", "闪存", "内存"],
                "半导体设备": ["刻蚀", "薄膜沉积", "CMP", "清洗设备", "半导体设备", "晶圆", "光刻"],
                "风电": ["风电", "风机", "叶片", "塔筒", "海缆", "风力"], "半导体": ["芯片", "晶圆", "封测", "集成电路"],
                "证券": ["证券", "经纪"], "电池": ["锂电", "电池", "正极", "负极", "隔膜", "电解液"]}

    def related(c):
        if c in SEEDSET:
            return True
        q = sec_of.get(c)
        b = rel.get(c, "")
        if not b:
            return None
        ks = KW.get(q, []) + KW_EXTRA.get(q, [])
        return any(k and k in b for k in ks)
    w("")
    w("【主营相关性核对】（每板块前15只；❌=挂在概念里但主业不沾边，剔除）")
    for q in secs:
        ln = []
        for x in [r for r in rows if sec_of.get(r[1]) == q][:15]:
            rr = related(x[1])
            ln.append("%s%s" % (x[2]["name"], "✅" if rr else ("❌" if rr is False else "?")))
        w("  %s：%s" % (q, " ".join(ln)))
    top = []
    for q in secs:
        n = 0
        for r in [x for x in rows if sec_of.get(x[1]) == q]:
            if r[0] >= 4 and related(r[1]) is not False:
                top.append(r)
                n += 1
                if n >= 2:
                    break
    top = sorted(top, key=lambda x: -x[0])[:8]
    w("")
    w("★★ 每板块前2只（≥4分且主营相关）共%d只 → 自动交给查股票深查 ★★" % len(top))
    for s, c, qd, f, why in top:
        w("  %+d %s(%s) [%s] %s" % (s, qd["name"], c, sec_of.get(c), "、".join(why)))
    if not top:
        w("  无≥4分的——这些板块今天没有'低位+没涨+资金在进'的票，宁可不买")
    w("")
    w("诊断：" + " ｜ ".join(LOG[:12]))
    w("耗时 %.0f 秒" % (time.time() - T0))
    return [r[1] for r in top]


if __name__ == "__main__":
    top = []
    try:
        top = main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        w("🔴 板块深扫异常：%s" % e)
    os.makedirs("reports", exist_ok=True)
    open("reports/板块深扫_最新.txt", "w", encoding="utf-8").write("\n".join(L))
    open("reports/_sector_top.txt", "w", encoding="utf-8").write(",".join(top))

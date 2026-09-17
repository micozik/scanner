# -*- coding: utf-8 -*-
"""
patch19b_newconcept.py —— 只做一件事：
新增【新概念雷达】—— 不靠词典，自动从今日新闻里挖出
「系统没收录、但市场在反复提」的产业新名词。

★为什么必须有它（2026-09-17 金刚石事故）★
  · 今年2月 英伟达官宣下一代Vera Rubin GPU采用「金刚石复合材料+液冷」
  · 2/23 Akash交付首台Diamond Cooling英伟达H200服务器
  · 3月 落地AMD MI350X ｜ 4月 中科院金刚石铜复合材料在郑州超算规模化应用
  · 截至5/25 力量钻石/四方达/黄河旋风/沃尔德四只涨幅均超100%
  · 9/16 沃尔德再涨超10%，那条快讯就躺在报告【全量新闻流】里
  ★整整七个月，系统一次都没报过★

  根因不是"漏了金刚石"：
  【今日隐形主线】的 KEY_SEEDS 是手写固定词表；
  【推演引擎】CHAIN_MAP 里 AI散热链的标的表写的是
  英维克/申菱/高澜/同飞/飞荣达/中石科技 —— 全是液冷设备层，
  一个材料层标的都没有。
  ★任何新概念在被人手工写进词典之前，都是系统的永久盲区★

算法（第一版失败的教训写在这里）：
  ❌ 第一版用「变长前缀+产业后缀」正则，结果
     "金刚石复合材料""金刚石铜复合材料"被切成不同的词，
     频次分散，全部<3，一个都没捞出来。
  ✅ 现版改用 n-gram 词频：
     ① 只看带产业语境的新闻（含 量产/涨价/扩产/订单/材料/散热…）
     ② 抽出所有2-6字中文片段，统计频次
     ③ 短词若被同频长词包含 → 丢弃（保留"金刚石"不保留"金刚"）
     ④ 剔除停用词 + 系统词典里已有的
  实测：11条金刚石新闻 → 成功捞出【金刚石】出现4次
"""
import io
import os
import sys

MARK = "patch19b_newconcept"
CANDIDATES = ["scanner_cloud.py", "scanner_cloud__1_.py"]

path = None
for c in CANDIDATES:
    if os.path.exists(c):
        path = c
        break
if path is None:
    print("!! patch19b 中止：找不到 scanner_cloud.py")
    sys.exit(0)

with io.open(path, "r", encoding="utf-8") as f:
    s = f.read()

if MARK in s:
    print("OK 0: patch19b 已打过，跳过（幂等）")
    sys.exit(0)

# 清掉 patch19 第一版（算法失败，留着只会白占预算）
if "patch19_newconcept" in s and MARK not in s:
    print("!! 检测到 patch19 第一版：请先从仓库删除 patch19_newconcept.py")

A = '''    KEY_SEEDS = [
        "PCB", "覆铜板", "CCL", "载板", "封装基板", "先进封装", "IC载板",'''

if A not in s:
    print("!! patch19b 中止：找不到 KEY_SEEDS 锚点（patch19第一版是否已改过？）")
    sys.exit(0)

NEW = '''    # ===== ''' + MARK + '''：新概念雷达（不靠词典） =====
    try:
        import re as _re19
        import collections as _co19

        def _txt19(it):
            if isinstance(it, dict):
                return str(it.get("title") or it.get("t") or it.get("content") or "")
            if isinstance(it, (tuple, list)):
                return " ".join(str(x) for x in it)
            return str(it)

        _raw19 = [_txt19(x) for x in (list(news) + list(ann))]

        # 只看带【产业语境】的新闻，过滤掉纯行情/政治口水
        _CTX19 = ("量产", "涨价", "扩产", "订单", "材料", "散热", "导热",
                  "短缺", "缺货", "产能", "投产", "商用", "规模化",
                  "国产替代", "供不应求", "中标", "衬底", "封装", "热管理")
        _STOP19 = set([
            "公司", "项目", "行业", "技术", "产品", "市场", "相关", "持续",
            "全面", "国内", "全球", "以及", "有望", "预计", "加速", "新型",
            "重要", "主要", "目前", "已经", "正在", "未来", "今年", "去年",
            "本次", "上述", "部分", "多个", "领域", "方面", "方向", "环节",
            "需求", "供应", "价格", "成本", "研发", "生产", "制造", "应用",
            "实现", "提升", "推动", "中国", "美国", "日本", "韩国", "欧洲",
            "概念", "板块", "指数", "涨超", "跌超", "方案", "规模", "产能",
            "股份", "集团", "科技", "有限", "机构", "研报", "分析", "表示",
            "宣布", "发布", "推出", "完成", "达成", "合作", "战略", "投资",
            "增长", "同比", "环比", "亿元", "万元", "预期", "数据", "报道",
        ])

        _cnt19 = _co19.Counter()
        _eg19 = {}
        for _t19 in _raw19:
            if not any(_c19 in _t19 for _c19 in _CTX19):
                continue
            for _seg19 in _re19.findall(r"[\\u4e00-\\u9fa5]{2,}", _t19):
                for _n19 in range(2, 7):
                    for _i19 in range(len(_seg19) - _n19 + 1):
                        _w19 = _seg19[_i19:_i19 + _n19]
                        _cnt19[_w19] += 1
                        if _w19 not in _eg19:
                            _eg19[_w19] = _t19[:70]

        # 短词若被【同频或更低频】的长词包含 → 丢弃短的
        _items19 = sorted(_cnt19.items(), key=lambda x: (-x[1], -len(x[0])))
        _keep19 = []
        for _w19, _c19 in _items19:
            if _c19 < 3 or _w19 in _STOP19:
                continue
            if any(_w19 in _k19 and _c19 <= _kc19 for _k19, _kc19 in _keep19):
                continue
            _keep19.append((_w19, _c19))
            if len(_keep19) >= 40:
                break

        # 剔除系统词典里已有的
        _known19 = set()
        for _kk19 in ("KEY_SEEDS", "HEAT_DICT", "CHAIN_MAP", "BULL_WORDS"):
            _v19 = globals().get(_kk19)
            if isinstance(_v19, dict):
                _known19 |= set(str(x) for x in _v19.keys())
            elif isinstance(_v19, (list, tuple, set)):
                _known19 |= set(str(x) for x in _v19)

        _new19 = [(a, b) for a, b in _keep19
                  if not any((k in a or a in k) for k in _known19 if len(k) >= 2)]

        w("\\n" + "=" * 60)
        w("🆕🆕【新概念雷达】词典里没有、但今天新闻在反复提 🆕🆕")
        w("=" * 60)
        w("  ★2026-09-17金刚石事故：英伟达Rubin用『金刚石复合材料+液冷』")
        w("    2月官宣→龙头5月已涨超100%→9/16沃尔德再涨10%，")
        w("    ★系统七个月一次没报过★ 因为没人把『金刚石』写进KEY_SEEDS。")
        w("  ★本模块不靠词典：谁在新闻里反复出现，谁自己冒出来。")
        if not _new19:
            w("\\n  今日无新概念（或新闻源条数不足）")
        else:
            w(f"\\n  ★★捞出 {len(_new19)} 个系统词典外的高频产业名词★★")
            for _w19, _c19 in _new19[:12]:
                w(f"    ◆ 【{_w19}】今日出现 {_c19} 次")
                _s19 = _eg19.get(_w19, "")[:66]
                if _s19:
                    w(f"       例：{_s19}")
        w("")
        w("  ── AI必须逐个回答，答不出写『查不到』──")
        w("    ① 它指哪个产业环节？上游是谁、下游客户是谁？（①-B）")
        w("    ② 产业周期 还是 单一事件？填得出『持续N周』吗？（③-B）")
        w("    ③ A股哪几只在这条链上？今天涨了没有？")
        w("    ④ ★这波第几天了？已经涨了多久？★")
        w("       金刚石的教训：方向对但晚了七个月，追进去是接最后一棒")
        w("=" * 60)
    except Exception as _e19:
        w(f"  [跳过] 新概念雷达：{type(_e19).__name__}: {str(_e19)[:60]}")
    # ===== 新概念雷达 结束 =====

    KEY_SEEDS = [
        # ''' + MARK + '''：补上已知遗漏的链
        "金刚石", "培育钻石", "热沉片", "金刚石铜", "CVD", "MPCVD",
        "碳化硅", "氮化镓", "第三代半导体", "第四代半导体",
        "玻璃基板", "TGV", "硅光子", "共封装", "硅微粉",
        "PCB", "覆铜板", "CCL", "载板", "封装基板", "先进封装", "IC载板",'''

s = s.replace(A, NEW, 1)
print("OK 1: 新概念雷达已注入（n-gram算法）+ KEY_SEEDS补15个词")

s = s.rstrip("\n") + "\n\n# " + MARK + "：新概念雷达上线\n"

with io.open(path, "w", encoding="utf-8") as f:
    f.write(s)
print("patch19b 完成 → %s" % path)

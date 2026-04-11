# -*- coding: utf-8 -*-
"""Normalize and merge group names - consolidate variants into canonical names."""
import json
import sys
sys.stdout.reconfigure(encoding='utf-8')

# Merge map: old group name → canonical group name
GROUP_MERGE = {
    # ── 锐科 → 派克集团 (user confirmed) ──
    "锐科": "派克集团",

    # ── 亨斯 → 亨斯迈 ──
    "亨斯": "亨斯迈",

    # ── 珀金埃尔 → 珀金埃尔默 ──
    "珀金埃尔": "珀金埃尔默",

    # ── 三井 → 三井集团 ──
    "三井": "三井集团",

    # ── 马勒 → 马勒集团 ──
    "马勒": "马勒集团",

    # ── 莫士 → 莫仕集团 ──
    "莫士": "莫仕集团",

    # ── 优美蒂 → 优美缔 ──
    "优美蒂": "优美缔",

    # ── 赫斯 → 赫斯可 (if they're the same) ──
    # Actually 赫斯 might be Hess, 赫斯可 is Husco - keep separate
    # "赫斯": "赫斯可",

    # ── 瑞侃电子（上海）有限公司 → 泰科集团 ──
    "瑞侃电子（上海）有限公司": "泰科集团",

    # ── Company-level names → group names ──
    "格柏(上海)工业数控设备有限公司": "格柏科技",
    "格柏科技": "格柏科技",
    "上海中航光电子有限公司": "中航光电",
    "上海丹尼逊液压件有限公司": "派克集团",  # Denison = Parker subsidiary
    "上海环世捷运物流有限公司": "上海环世",
    "上海环盛": "上海环盛",
    "上海申创中小企业合作交流技术促进中心": "其他",
    "东莞创宝达电器制品有限公司": "创宝达",
    "亮讯国际贸易(上海)有限公司": "亮讯",
    "六洲酒店管理(上海)有限公司": "六州酒店",
    "六州酒店": "六州酒店",
    "勒姆研究(上海)有限公司": "勒姆研究",
    "北京华夏石化工程监理有限公司": "华夏石化",
    "博莱特(上海)贸易有限公司": "阿特拉斯",  # 博莱特 = Atlas Copco
    "卡摩速企业管理(中国)有限公司": "卡摩速",
    "友尚电子有限公司": "友尚电子",
    "夏特装饰材料(上海)有限公司": "夏特",
    "奥升德功能材料(上海)有限公司": "奥升德",
    "宝马格(中国)工程机械有限公司": "宝马格",
    "安弗施无线射频系统(上海)有限公司": "安弗施",
    "安捷伦科技(中国)有限公司": "安捷伦",
    "安智光刻电子材料(上海)有限公司": "安智光刻",
    "戴纳派克(中国)压实摊铺设备有限公司": "戴纳派克",
    "旺众商用设备(上海)有限公司": "旺众",
    "是德科技(中国)有限公司": "是德科技",
    "普利司通(中国)投资有限公司": "普利司通",
    "普尔文技术(北京)有限公司": "普尔文",
    "布鲁克斯仪器贸易(上海)有限公司": "布鲁克斯",
    "泛亚班拿国际货运代理(中国)有限公司": "泛亚班拿",
    "泛成国际货运有限公司": "泛成国际",
    "泛林半导体设备技术(上海)有限公司": "泛林半导体",
    "爱克发(无锡)印版有限公司": "爱克发",
    "牧野机床(中国)有限公司": "牧野机床",
    "特易行国际货运代理(深圳)有限公司": "特易行",
    "环捷国际货运代理(上海)有限公司": "环捷",
    "环捷": "环捷",
    "美利达自行车(中国)有限公司": "美利达",
    "美吉莱商贸(上海)有限公司": "美吉莱",
    "肯纳飞硕金属(上海)有限公司": "肯纳飞硕",
    "舒捷(上海)胶带有限公司": "舒捷",
    "艺康(中国)投资有限公司": "艺康",
    "花王(上海)化工有限公司": "花王",
    "诺马连接技术(无锡)有限公司": "诺马",
    "赛特福德(深圳)贸易有限公司": "赛特福德",
    "达能亚太(上海)管理有限公司": "达能",
    "福建聚力电机有限公司": "聚力电机",
    "钇镭科(北京)光学电子制造有限公司": "钇镭科",
    "锦海捷亚国际货运有限公司": "锦海捷亚",
    "镭富电子设备(上海)有限公司": "镭富电子",
    "高仪(上海)卫生洁具有限公司": "骊住",  # Grohe = LIXIL
    "骊住": "骊住",
    "默天旎贸易(上海)有限公司": "默天旎",
    "IMS Market Research": "艾美仕",  # IMS = IQVIA/艾美仕
    "Boston Scientific": "波士顿科学",

    # ── FlexLink → probably independent ──
    "FlexLink": "FlexLink",

    # ── 丰罗 → 保留 ──
    "丰罗": "丰罗",

    # ── 天马微电子 ──
    "天马微电子有限公司": "天马微电子",

    # ── 辽宁三友 ──
    "辽宁三友商贸有限责任公司": "三友商贸",

    # ── 达凯 ──
    "达凯(上海)电子科技有限公司": "达凯",

    # ── 科益实 ──
    "科益实": "科益实",

    # ── 中海散货 ──
    "中海散货运输有限公司": "中海散货",
}


def main():
    audit_path = "output/audit.jsonl"
    records = []
    with open(audit_path, "r", encoding="utf-8") as f:
        for line in f:
            records.append(json.loads(line))

    merged = 0
    for r in records:
        old_group = r.get("detected_group", "")
        if old_group in GROUP_MERGE:
            r["detected_group"] = GROUP_MERGE[old_group]
            merged += 1

    with open(audit_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Merged: {merged} records")

    # Count final groups
    groups = {}
    with open(audit_path, "r", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            g = r.get("detected_group", "")
            groups[g] = groups.get(g, 0) + 1

    print(f"\nFinal group count: {len(groups)} groups, {sum(groups.values())} records")
    for g in sorted(groups.keys()):
        print(f"  {groups[g]:5d}  {g}")


if __name__ == "__main__":
    main()

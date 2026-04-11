# -*- coding: utf-8 -*-
"""逐个文件夹检查PDF文件名是否和集团匹配。
对于每个集团文件夹，列出所有PDF文件名，检查文件名中的公司名/关键词
是否与该集团相符。输出疑似放错的文件。"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

OUTPUT = Path("output")

# 每个集团的预期关键词（文件名中应包含的公司名/关键词）
# 如果文件名不包含任何预期关键词，就需要人工检查
GROUP_KEYWORDS = {
    "ABB": ["ABB", "abb"],
    "DNV": ["DNV", "dnv", "挪威", "DNV GL"],
    "FlexLink": ["FlexLink", "flexlink", "弗莱克斯"],
    "万代": ["万代", "bandai", "Bandai"],
    "三井集团": ["三井", "mitsui"],
    "丰树集团": ["丰树", "mapletree", "丰华新", "丰龙", "丰跃", "嘉拓", "俊峰", "君丰",
                "星健", "翎丰", "南院", "丰航", "丰尚", "临港", "宝瓶星"],
    "丸红": ["丸红", "marubeni"],
    "丹纳赫集团": ["丹纳赫", "danaher"],
    "丽星邮轮": ["丽星", "star cruises"],
    "亚玛芬": ["亚玛芬", "amer sports"],
    "亨斯迈": ["亨斯迈", "huntsman", "亨斯"],
    "以星": ["以星", "zim"],
    "伊士曼": ["伊士曼", "eastman", "首诺"],
    "伊藤忠": ["伊藤忠", "itochu"],
    "伊顿": ["伊顿", "eaton"],
    "先正达": ["先正达", "syngenta"],
    "六州酒店": ["六州", "六洲"],
    "内部文件": ["泛纬", "莱升", "LICENSE", "license", "LSC", "lsc", "莱禾", "业升", "业信", "昇升"],
    "力运": ["力运"],
    "卡拉威": ["卡拉威", "callaway"],
    "台积电": ["台积电", "TSMC", "tsmc"],
    "哈挺": ["哈挺", "hardinge"],
    "唐纳森": ["唐纳森", "donaldson"],
    "如新": ["如新", "nu skin"],
    "山特维克": ["山特维克", "sandvik", "sandivik"],
    "帝亚吉欧": ["帝亚吉欧", "diageo", "蒂亚吉欧"],
    "庄臣": ["庄臣", "johnson"],
    "必维集团": ["必维", "bureau veritas", "BV", "毕法克", "申美", "华法", "法利", "英斯贝",
                "德利福", "inspectorate"],
    "德州仪器": ["德州仪器", "texas instruments", "TI"],
    "摩恩": ["摩恩", "moen", "富俊", "富欣", "富耐连"],
    "日本电产": ["日本电产", "nidec", "三协"],
    "松下": ["松下", "panasonic"],
    "柯尼卡": ["柯尼卡", "konica"],
    "欣阳集团": ["欣阳"],
    "泰科集团": ["泰科", "tyco", "TE ", "瑞侃", "raychem", "安普泰科", "泰克电子"],
    "派克集团": ["派克", "parker", "锐科", "丹尼逊", "太派"],
    "珀金埃尔默": ["珀金", "perkin", "铂金埃尔", "铂金挨尔", "金埃尔默"],
    "空气化工": ["air products", "AP", "空气化工"],
    "索尼": ["索尼", "sony"],
    "罗门哈斯": ["罗门哈斯", "rohm"],
    "美赞臣": ["美赞臣", "mead johnson"],
    "莫仕集团": ["莫仕", "molex", "莫士"],
    "西门子集团": ["西门子", "siemens", "MWB"],
    "阿特拉斯": ["阿特拉斯", "atlas", "博莱特", "凌格风", "纽曼泰克", "昆泰克",
                "途泰", "涂泰", "柳州泰克", "柳泰克", "安百拓", "科普柯", "埃尔特"],
    "马勒集团": ["马勒", "mahle"],
    "酩悦轩尼诗": ["酩悦", "轩尼诗", "moet", "hennessy", "熊悦"],
    "福寿园": ["福寿", "南院"],
    "第一精工": ["第一精工", "三兴精密", "三星精密", "三辉精密"],
    "骊住": ["骊住", "lixil", "高仪", "grohe"],
    "默克": ["默克", "merck"],
    "达能": ["达能", "danone"],
    "泛亚班拿": ["泛亚班拿", "panalpina"],
    "百时美施贵宝": ["百时美", "施贵宝", "bristol", "bms"],
    "艾美仕": ["艾美仕", "IMS", "ims", "IQVIA"],
    "英特尔": ["英特尔", "intel", "因特尔"],
    "赢创": ["赢创", "evonik"],
    "贺德克": ["贺德克", "hydac"],
    "飞世尔": ["飞世尔", "fisher", "thermo"],
    "阿奇": ["阿奇", "agie"],
    "新百伦": ["新百伦", "new balance"],
    "发发奇": ["发发奇", "farfetch"],
    "奥碧虹": ["奥碧虹", "orbis"],
    "爱沛": ["爱沛"],
    "普利司通": ["普利司通", "bridgestone"],
    "豪乐集团": ["豪乐"],
    "璨宇光电": ["璨宇"],
    "罗氏": ["罗氏", "roche"],
    "安德里茨": ["安德里茨", "andritz"],
    "费列罗": ["费列罗", "ferrero"],
    "长兴科技": ["长兴"],
    "泛林半导体": ["泛林", "lam research"],
    "福群": ["福群"],
    "致联": ["致联"],
    "舒尔": ["舒尔", "shure"],
    "牛津仪器": ["牛津", "oxford"],
    "托纳斯": ["托纳斯", "tornos"],
    "博阁玛": ["博阁玛", "borgwarner"],
    "安捷伦": ["安捷伦", "agilent"],
    "科比传动": ["科比传动", "KEB"],
    "涂泰": ["涂泰", "途泰", "透森"],
    "展示设备": ["展示设备"],
    "应特格": ["应特格", "entegris"],
    "先进太平洋科技": ["先进太平洋"],
    "肯纳飞硕": ["肯纳飞硕", "kennametal"],
    "狼爪": ["狼爪", "jack wolfskin"],
    "蒂森克虏伯": ["蒂森", "thyssenkrupp"],
    "惠普": ["惠普", "HP", "hp"],
    "艾默生": ["艾默生", "emerson"],
    "奇美材料": ["奇美"],
    "通用电气": ["通用电气", "GE", "东芝有机硅"],
    "环捷": ["环捷", "globe express"],
    "德勤": ["德勤", "deloitte"],
    "凯虹电子": ["凯虹"],
    "礼来": ["礼来", "eli lilly"],
}

# 不检查的集团（太杂或不需要）
SKIP_GROUPS = {"其他", "内部文件"}

issues = []
checked = 0

for group_dir in sorted(OUTPUT.iterdir()):
    if not group_dir.is_dir():
        continue
    group = group_dir.name
    if group in SKIP_GROUPS:
        continue

    keywords = GROUP_KEYWORDS.get(group, [])

    # Get all PDFs recursively
    pdfs = list(group_dir.rglob("*.pdf"))
    if not pdfs:
        continue

    for pdf in pdfs:
        fname = pdf.name.lower()
        checked += 1

        # If we have keywords, check if any match
        if keywords:
            matched = any(kw.lower() in fname for kw in keywords)
            if not matched:
                issues.append((group, pdf.name))

# Output
print(f"Checked {checked} files across {len(GROUP_KEYWORDS)} groups with keywords")
print(f"\n=== POTENTIAL MISPLACEMENTS ({len(issues)} files) ===\n")
current_group = ""
for group, fname in issues:
    if group != current_group:
        print(f"\n--- {group} ---")
        current_group = group
    print(f"  {fname}")

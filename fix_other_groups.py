# -*- coding: utf-8 -*-
"""Reclassify companies from '其他' into correct groups based on business knowledge."""
import json
import sys
import re

# Manual group assignments based on company name analysis
# Format: substring -> group name (longest match wins)
MANUAL_GROUP = {
    # ── 派克集团 (Parker Hannifin) ──
    "派克汉尼": "派克集团",
    "派克挨迪亚": "派克集团",
    "派克艾迪亚": "派克集团",
    "派克空调": "派克集团",
    "锐科": "派克集团",

    # ── 泰科集团 (TE Connectivity / Tyco) ──
    "泰科电子": "泰科集团",
    "泰克电子": "泰科集团",  # OCR variant
    "瑞侃电子": "泰科集团",  # Raychem = Tyco subsidiary
    "瑞侃电缆": "泰科集团",
    "瑞侃（上海）": "泰科集团",

    # ── 西门子集团 ──
    "西门子": "西门子集团",

    # ── 珀金埃尔默 (PerkinElmer) ──
    "珀金埃尔默": "珀金埃尔默",
    "铂金埃尔默": "珀金埃尔默",  # OCR variant
    "铂金挨尔默": "珀金埃尔默",  # OCR variant
    "金埃尔默": "珀金埃尔默",
    "perkinEhner": "珀金埃尔默",  # OCR variant
    "perkinelmer": "珀金埃尔默",

    # ── 摩恩 (Moen) ──
    "富俊汇赢": "摩恩",
    "富俊（上海）厨卫": "摩恩",
    "富欣汇鑫": "摩恩",  # OCR variant of 富俊汇赢
    "富耐连": "摩恩",  # Moen subsidiary

    # ── 丰树集团 (Mapletree) ──
    "丰树": "丰树集团",
    "丰尚仓储": "丰树集团",
    "丰航仓储": "丰树集团",  # OCR variant
    "广州丰华新": "丰树集团",
    "广州丰树华新": "丰树集团",
    "宁波俊峰房地产": "丰树集团",
    "宁波君丰房地产": "丰树集团",  # OCR variant
    "广州星健星穗": "丰树集团",
    "上海翎丰房地产": "丰树集团",
    "上海南院事业": "丰树集团",
    "Shanghai Lingfeng": "丰树集团",

    # ── 必维集团 (Bureau Veritas) ──
    "必维": "必维集团",
    "BV（必维": "必维集团",
    "毕法克": "必维集团",  # BV subsidiary
    "申美商品": "必维集团",
    "审美商品": "必维集团",  # OCR variant
    "华法商品": "必维集团",
    "法利德国际质量": "必维集团",
    "法利嘉航": "必维集团",
    "德利福认证": "必维集团",
    "英斯贝尔": "必维集团",

    # ── 阿特拉斯·科普柯 (Atlas Copco) ──
    "阿特拉": "阿特拉斯",
    "博莱特": "阿特拉斯",
    "昆山巨泰空压": "阿特拉斯",
    "上海埃尔特压缩": "阿特拉斯",

    # ── 第一精工 (Dai-ichi Seiko) ──
    "第一精工": "第一精工",
    "广州三兴精密": "第一精工",  # 三兴 = Dai-ichi Seiko Guangzhou
    "广州三星精密": "第一精工",  # OCR variant
    "蘇州精密模具": "第一精工",
    "三辉精密模具": "第一精工",
    "郭城市精模塑": "第一精工",  # OCR garbled
    "成阳精密模具": "第一精工",  # OCR variant

    # ── GE / 通用电气 ──
    "通用电气": "通用电气",
    "GE东芝": "通用电气",
    "东芝有机硅": "通用电气",  # GE Toshiba Silicones

    # ── ABB ──
    "ABB": "ABB",

    # ── 亚玛芬 (Amer Sports) ──
    "亚玛芬": "亚玛芬",

    # ── 伊顿 (Eaton) ──
    "伊顿": "伊顿",

    # ── 以星 (ZIM) ──
    "以星综合航运": "以星",

    # ── 万代 (Bandai) ──
    "万代玩具": "万代",

    # ── 亨斯迈 (Huntsman) ──
    "亨斯迈": "亨斯迈",

    # ── 东丽 (Toray) ──
    "东丽商事": "东丽",

    # ── 丸红 (Marubeni) ──
    "丸红": "丸红",

    # ── 丹佛斯 (Danfoss) ──
    "丹佛斯": "丹佛斯",

    # ── 索斯科 (Southco) ──
    "索斯科": "索斯科",

    # ── 索尼 (Sony) ──
    "索尼": "索尼",

    # ── 箭牌 (Wrigley / Mars) ──
    "箭牌糖": "箭牌",

    # ── 蒂亚吉欧 / Diageo ──
    "蒂亚吉欧": "帝亚吉欧",
    "Diageo": "帝亚吉欧",

    # ── 高仪 (Grohe) ──  骊住集团子品牌
    "高仪": "骊住",
    "LIXIL": "骊住",

    # ── 汉高 (Henkel) ──
    "汉高": "汉高",

    # ── 德勤 (Deloitte) ──
    "德勤": "德勤",

    # ── 马勒 (MAHLE) ──
    "马勒": "马勒",

    # ── 赫斯可 (Husco) ──
    "赫斯可": "赫斯可",
    "Husco": "赫斯可",

    # ── 普菲斯 (Preferred Freezer) ──
    "普菲斯": "普菲斯",

    # ── 科比传动 (KEB) ──
    "科比传动": "科比传动",

    # ── 格伯/格柏 (Gerber) ──
    "格伯（上海）": "格柏科技",
    "格柏科技": "格柏科技",

    # ── 格伦迪普莱斯 (Grundfos? / GlenDimplex) ──
    "格伦迪普莱斯": "格伦迪普莱斯",
    "格伦订普莱斯": "格伦迪普莱斯",  # OCR variant
    "钉普莱斯": "格伦迪普莱斯",

    # ── 布洛姆 (Bloom) ──
    "布洛姆燃烧器": "布洛姆",

    # ── 道麦逊 (Thomson) ──
    "道麦逊": "道麦逊",

    # ── 瑞侃 → already mapped to 泰科 above

    # ── 上贝/贝迪 (Brady) ──
    "上贝（上海）": "贝迪科技",
    "贝迪科技": "贝迪科技",

    # ── 凯虹电子 (Carsem) ──
    "凯虹电子": "凯虹电子",
    "凯虹科技电子": "凯虹电子",

    # ── 艾思毅 (ASI / Americold?) ──
    "艾思毅": "艾思毅",

    # ── 涂泰/途泰/透森/涌鑫 (Toku / Toyo) ── 同一集团OCR变体
    "涂泰工业": "涂泰",
    "途泰气动": "涂泰",
    "透森工业": "涂泰",
    "涌鑫工业": "涂泰",

    # ── 泰乐 (Tellabs) ──
    "泰乐": "泰乐",

    # ── 科锐安/科仑安 (CorningWare?) ──
    "科锐安通讯": "科锐安",
    "科仑安": "科锐安",

    # ── 广电 NEC/NBC ──
    "广电NEC": "广电NEC",
    "广电NBC": "广电NEC",
    "广电通讯": "广电NEC",

    # ── 台烨货运 ──
    "台烨货运": "台烨",

    # ── 国福龙凤 (Guofeng / CPF?) ──
    "国福龙凤": "国福龙凤",

    # ── 爱信诺航天 ──
    "爱信诺航天": "航天信息",
    "航天信息": "航天信息",

    # ── 大成美食 ──
    "大成美食": "大成",

    # ── 艾祖偌/艾祖诺/艾租 (Adecco) ──
    "艾祖偌": "艾德科",
    "艾祖诺": "艾德科",
    "艾租企业": "艾德科",
    "艾杜仕": "艾德科",

    # ── 协议/保密合同/服务合同 前缀 → 需看后面的公司名 ──
    "协议-礼来": "礼来",

    # ── 奎斯特 (Quest) ──
    "奎斯特": "奎斯特",

    # ── 台达 (Delta) ──
    "台达电子": "台达",

    # ── 瑞侃 already → 泰科

    # ── 达科电子 (Daktronics) ──
    "达科电子": "达科电子",

    # ── 三井 ──
    "三井纤维": "三井",

    # ── 冠捷 (TPV) ──
    "冠捷半导体": "冠捷",

    # ── 如新 (Nu Skin) ──
    "如新（中国）": "如新",

    # ── 圣诺技 (Sinopec?) ──
    "圣诺技": "圣诺技",

    # ── 宏衙 (Honeywell?) → probably not ──
    "宏衙": "宏衙",

    # ── 汉堡王 (Burger King) ──
    "汉堡王": "汉堡王",

    # ── 史丹利 (Stanley) ──
    "史丹利": "史丹利",

    # ── 罗氏 (Roche) ──
    "罗氏": "罗氏",

    # ── 博士 (Bose) ──
    "博士视听": "博士",

    # ── 博鲁可斯 (Brooks) ──
    "博鲁可斯": "博鲁可斯",

    # ── 惠普 (HP) ──
    "惠普": "惠普",

    # ── 英特格 (Entegris) ──
    "英特格": "英特格",

    # ── 优美蒂 (Ultimaker?) ──
    "优美蒂": "优美蒂",

    # ── 凯瑞德 (CNC Software?) ──
    "凯瑞德": "凯瑞德",

    # ── 德纳 (Dana) ──
    "德纳（无锡）": "德纳",

    # ── 新进半导体 ──
    "新进半导体": "新进半导体",

    # ── 克拉克 (Clark) ──
    "克拉克过滤器": "克拉克",

    # ── 诺发 (Novellus) ──
    "诺发系统": "诺发",

    # ── 诺日士 (Noritsu) ──
    "诺日士": "诺日士",

    # ── 兆普电子 ──
    "兆普电子": "兆普电子",

    # ── Air Products ──
    "Air Products": "空气化工",
    "AP集团": "空气化工",

    # ── Barclays ──
    "Barclays": "巴克莱",
    "BARCLAYS": "巴克莱",

    # ── 琉璃奥图 (Optoma / 中强光电) ──
    "琉璃奥图": "中强光电",
    "奥图码数码": "中强光电",

    # ── 顺普汽车 ──
    "顺普汽车": "顺普",

    # ── 莫士 (Molex) ──
    "莫士": "莫士",

    # ── 圣皮尔 (Saint-Pierre) ──
    "圣皮尔": "圣皮尔",

    # ── 宝马格 (BOMAG) ──
    "宝马格": "宝马格",

    # ── 默克 (Merck) ──
    "默克光电": "默克",
    "AZ Electronic": "默克",

    # ── 安东帕 (Anton Paar) ──
    "安东帕": "安东帕",
    "安帕（中国）": "安东帕",

    # ── 奥德升 ──
    "奥德升": "奥德升",

    # ── 优力电机 ──
    "优力电机": "优力电机",

    # ── 优尼福耐 (Unifrax) ──
    "优尼福耐": "优尼福耐",

    # ── 艾微美 ──
    "艾微美": "艾微美",

    # ── 东福电子 ──
    "东福电子": "东福电子",

    # ── Tokio Marine ──
    "Tokio Marine": "东京海上",

    # ── 志和电子 ──
    "志和电子": "志和电子",

    # ── 德又达 ──
    "德又达": "德又达",

    # ── 宁波大亿 ──
    "宁波大亿": "大亿科技",

    # ── 汽车零部件（昆山）── probably 顺普
    "汽车零部件（昆山）": "顺普",

    # ── 瑞侃电子 already mapped to 泰科

    # ── Azure Recruitment ──
    "Azure Recruitment": "Azure Recruitment",

    # ── 首诺 (Solutia / Eastman) ──
    "首诺高功": "首诺",

    # ── 马勒东炫 already mapped to 马勒

    # ── 明星邮轮 ──
    "明星邮轮": "明星邮轮",

    # ── 环捷国际 / globe express ──
    "环捷国际": "环捷",
    "globe express": "环捷",

    # ── 陆川国际 ──
    "陆川国际": "陆川",

    # ── sandivik → 山特维克 ──
    "sandivik": "山特维克",

    # ── 采埃孚 (ZF) ──
    "采埃孚": "采埃孚",

    # ── 英飞凌/英飞达 (Infineon? / Infinet?) ──
    "英飞凌网络": "英飞凌",
    "英飞达网络": "英飞凌",

    # ── 汉钟精机 ──
    "汉钟精机": "汉钟精机",

    # ── 德勤华永 already → 德勤

    # ── 瑞侃 already → 泰科

    # ── 华茂保健 ──
    "华茂": "华茂",

    # ── 克康排气 (Faurecia?) ──
    "克康（上海）": "克康",

    # ── 氢伏特 (Konecranes?) → same as 凯伏特 ──
    "氢伏特": "科尼",
    "凯伏特": "科尼",

    # ── 美利达 (Merida) ──
    "美利达": "美利达",

    # ── 观光投资 ──
    "观光投资": "观光投资",

    # ── 展华电子 ──
    "展华电子": "展华电子",

    # ── 签名电子 ──
    "签名电子": "签名电子",

    # ── 寳仕/寶仕软件 (Basware) ──
    "寳仕软件": "寳仕",
    "寶仕软件": "寳仕",

    # ── 达尔投资 ──
    "达尔（上海）投资": "达尔",

    # ── 博格玛 ──
    "博格玛": "博格玛",
}

# Prefixes to strip before matching (contract type prefixes in company names)
PREFIXES_TO_STRIP = [
    "服务合同&保密合同-",
    "租用和实施合同&保密合同-",
    "服务合同-",
    "保密合同-",
    "服务协议-",
    "采购合同-",
    "采购单-",
    "购买-",
    "协议-",
    "服务-",
    "书-",
    "咨询服务协议-",
    "合同-",
    "服务申请表-",
    "此协议列出了",
    "计划确认书-",
    "软件服务合同-",
    "项目交付报告-",
    "项目建议书&确认书-",
    "项目说明书-",
    "顺普汽车零部件-",
    "此协议列出了上海莱士信息科技有限公司",
    "许可证费用由",
    "项目说明书-",
    "项目交付报告-",
    "项目建议书&确认书-",
]


def classify_company(company_name: str) -> str | None:
    """Try to classify a company into a group. Returns group name or None."""
    if not company_name:
        return None

    name_lower = company_name.lower()

    # Try longest match first
    best_match = None
    best_len = 0
    for substr, group in MANUAL_GROUP.items():
        if substr.lower() in name_lower and len(substr) > best_len:
            best_match = group
            best_len = len(substr)

    return best_match


def clean_company_name(name: str) -> str:
    """Strip contract-type prefixes from company names."""
    for prefix in sorted(PREFIXES_TO_STRIP, key=len, reverse=True):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name.strip()


def main():
    audit_path = "output/audit.jsonl"

    # Read all records
    records = []
    with open(audit_path, "r", encoding="utf-8") as f:
        for line in f:
            records.append(json.loads(line))

    print(f"Total records: {len(records)}")

    # Count changes
    reclassified = 0
    cleaned_names = 0
    still_other = []

    for r in records:
        group = r.get("detected_group", "")
        company = r.get("detected_company", "")

        # Clean company name prefixes for ALL records (not just 其他)
        cleaned = clean_company_name(company)
        if cleaned != company:
            r["detected_company"] = cleaned
            cleaned_names += 1

        if group != "其他":
            continue

        # Try to classify
        # First try the cleaned company name
        new_group = classify_company(cleaned)

        # If no match, try the filename
        if not new_group:
            fname = r.get("source_file", "")
            new_group = classify_company(fname)

        if new_group:
            r["detected_group"] = new_group
            reclassified += 1
        else:
            still_other.append(cleaned or company)

    # Write back
    with open(audit_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Reclassified: {reclassified} records")
    print(f"Cleaned names: {cleaned_names} records")
    print(f"Still in 其他: {len(still_other)} records")

    # Show remaining unclassified
    unique_still = {}
    for c in still_other:
        unique_still[c] = unique_still.get(c, 0) + 1

    print(f"\n=== Remaining unclassified ({len(unique_still)} companies) ===")
    for c in sorted(unique_still.keys()):
        print(f"  {unique_still[c]:3d}  {c}")


if __name__ == "__main__":
    main()

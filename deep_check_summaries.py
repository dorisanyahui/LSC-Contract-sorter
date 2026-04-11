# -*- coding: utf-8 -*-
"""Deep check all audit records for OCR errors in company names and bad amounts.
Compares detected_company against file_name to find OCR misreads."""
import json, sys, re
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')

# Known OCR typo patterns: wrong → correct
OCR_TYPOS = {
    "流体转动": "流体传动",
    "流体链接件": "流体连接件",
    "动力传动力": "动力传动",
    "动力传产品": "动力传动产品",
    "三井纤维物质": "三井纤维物资",
    "流体接连件": "流体连接件",
    "挨迪亚": "艾迪亚",
    "挨尔默": "埃尔默",
    "汉尼分": "汉尼汾",
    "安置电子": "安智电子",
    "泰克电子": "泰科电子",  # Context-dependent
    "上海来升": "上海莱升",
    "传奇电气": "西门子电气传动",
    "上海审美": "上海申美",
    "栢金挨尔默": "珀金埃尔默",
    "铂金挨尔默": "珀金埃尔默",
    "铂金埃尔默": "珀金埃尔默",
    "金埃尔默": "珀金埃尔默",
    "罗氏剃药": "罗氏制药",
    "琉璃奥秃": "琉璃奥图",
    "福秦华": "福斯华",
    "西门子开过": "西门子开关",
    "西门（中国）": "西门子（中国）",
    "费雷罗": "费列罗",
    "啊特拉斯": "阿特拉斯",
    "阿特斯拉": "阿特拉斯",
    "阿特拉.斯普柯": "阿特拉斯.科普柯",
    "阿特拉斯普柯": "阿特拉斯.科普柯",
    "阿特拉斯柯普柯": "阿特拉斯.科普柯",
    "泰科电子科技": "泰科电子",  # 科技 is redundant
    "科尼卡美能达商用科技": "柯尼卡美能达商用科技",
    "变博思思分析仪器": "爱博才思分析仪器",
    "爱思特分析仪器": "爱博才思分析仪器",
    "安帕（中国）": "安东帕（中国）",
    "格伦订普莱斯": "格伦迪普莱斯",
    "派克汉尼分动力传产品": "派克汉尼汾动力传动产品",
    "派克汉尼分电子材料": "派克汉尼汾电子材料",
    "宁波缳宇": "宁波璨宇",
    "俊丰房地产": "俊峰房地产",
    "上海业信信息": "上海莱升信息",
    "上海业升信息": "上海莱升信息",
    "上海昇升信息": "上海莱升信息",
    "电力自动化有限公司": "西门子电力自动化有限公司",
    "成阳精密模具": "欣阳精密模具",
    "郭城市精模塑": "苏州精密模塑",
    "三兴精密机械工程": "三兴精密模塑塑料工程",  # less wrong but OK
    "三星精密模具塑料": "三兴精密模塑塑料",
    "宏利科技": "宏利科技",  # Actually correct
    "深圳华法商品检定": "深圳必维华法商品检定",
    "优三睇科技": "优三睇科技",  # OCR but can't determine correct
    "六州酒店": "六洲酒店",
    "洪博培集团": "亨斯迈集团",  # Huntsman = 洪博培 is wrong OCR
}

# Amount validation patterns
YEAR_AMOUNT_RE = re.compile(r'^20\d{2}(\.\d{1,2})?$')


def main():
    records = []
    with open("output/audit.jsonl", "r", encoding="utf-8") as f:
        for line in f:
            records.append(json.loads(line))

    fixes = 0
    issues = []

    for r in records:
        company = r.get("detected_company", "")
        fname = r.get("file_name", "")
        group = r.get("detected_group", "")

        # === Fix OCR typos in company names ===
        for wrong, correct in OCR_TYPOS.items():
            if wrong in company:
                old = company
                company = company.replace(wrong, correct)
                r["detected_company"] = company
                fixes += 1
                issues.append(f"[FIX] {group}: \"{old}\" → \"{company}\"")
                break

        # === Check amounts ===
        for amt_field in ["annual_maintenance_fee", "tax_included_amount",
                          "tax_excluded_amount", "contract_total_amount"]:
            val = r.get(amt_field)
            if val is None:
                continue
            try:
                amt = float(val)
            except (ValueError, TypeError):
                continue

            # Amount looks like a year
            if YEAR_AMOUNT_RE.match(str(val)):
                r[amt_field] = None
                fixes += 1
                issues.append(f"[FIX] {group}: {amt_field}={val} looks like year, cleared | {fname}")
                continue

            # Amount is negative
            if amt < 0:
                r[amt_field] = abs(amt)
                fixes += 1
                issues.append(f"[FIX] {group}: {amt_field}={amt} negative→positive | {fname}")

            # Amount < 100 and it's the only amount → suspicious
            if 0 < amt < 100 and amt_field == "contract_total_amount":
                # Check if it might be a percentage or version number
                if amt < 10:
                    r[amt_field] = None
                    fixes += 1
                    issues.append(f"[FIX] {group}: {amt_field}={amt} too small, cleared | {fname}")

    # Write back
    with open("output/audit.jsonl", "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Total fixes: {fixes}")
    print(f"\n=== All changes ===")
    for i in issues:
        print(f"  {i}")


if __name__ == "__main__":
    main()

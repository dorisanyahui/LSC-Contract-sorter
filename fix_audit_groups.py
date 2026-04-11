"""
修复 audit.jsonl 中的集团名称：
1. 将公司全名的集团名规范化为简短集团名
2. 修复空公司名（从文件名提取）
3. 修复金额疑似日期的问题
4. 修复公司名前缀噪音
"""
import json, re, sys, io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

AUDIT_PATH = Path("output/audit.jsonl")
OUTPUT_PATH = Path("output/audit.jsonl")

# ── 集团名映射 ─────────────────────────────────────
GROUP_NORMALIZE = {
    "万代玩具(深圳)有限公司": "万代",
    "上海中航光电子有限公司": "中航光电",
    "上海伊藤忠商事有限公司": "伊藤忠",
    "上海环世捷运物流有限公司": "上海环世",
    "东莞创宝达电器制品有限公司": "创宝达",
    "中海散货运输有限公司": "中海散货",
    "亚玛芬体育用品贸易(上海)有限公司": "亚玛芬",
    "亮讯国际贸易(上海)有限公司": "亮讯",
    "以星综合航运(中国)有限公司": "以星",
    "勒姆研究(上海)有限公司": "勒姆研究",
    "北京华夏石化工程监理有限公司": "华夏石化",
    "卡摩速企业管理(中国)有限公司": "卡摩速",
    "友尚电子有限公司": "友尚电子",
    "台积电(中国)有限公司": "台积电",
    "夏特装饰材料(上海)有限公司": "夏特",
    "天马微电子有限公司": "天马微电子",
    "奥升德功能材料(上海)有限公司": "奥升德",
    "奥碧虹(上海)化妆品贸易有限公司": "奥碧虹",
    "宁波璨宇光电有限公司": "璨宇光电",
    "安弗施无线射频系统(上海)有限公司": "安弗施",
    "安捷伦科技(中国)有限公司": "安捷伦",
    "安智光刻电子材料(上海)有限公司": "安智光刻",
    "宝马格(中国)工程机械有限公司": "宝马格",
    "布鲁克斯仪器贸易(上海)有限公司": "布鲁克斯",
    "戴纳派克(中国)压实摊铺设备有限公司": "戴纳派克",
    "摩迪(上海)咨询有限公司": "摩迪",
    "摩迪英联认证有限公司": "摩迪",
    "旺众商用设备(上海)有限公司": "旺众",
    "是德科技(中国)有限公司": "是德科技",
    "普利司通(中国)投资有限公司": "普利司通",
    "普尔文技术(北京)有限公司": "普尔文",
    "泛亚班拿国际货运代理(中国)有限公司": "泛亚班拿",
    "泛成国际货运有限公司": "泛成国际",
    "泛林半导体设备技术(上海)有限公司": "泛林半导体",
    "爱克发(无锡)印版有限公司": "爱克发",
    "牧野机床(中国)有限公司": "牧野机床",
    "特易行国际货运代理(深圳)有限公司": "特易行",
    "环捷国际货运代理(上海)有限公司": "环捷",
    "福建聚力电机有限公司": "聚力电机",
    "美利达自行车(中国)有限公司": "美利达",
    "美吉莱商贸(上海)有限公司": "美吉莱",
    "肯纳飞硕金属(上海)有限公司": "肯纳飞硕",
    "舒捷(上海)胶带有限公司": "舒捷",
    "艺康(中国)投资有限公司": "艺康",
    "花王(上海)化工有限公司": "花王",
    "英特尔(中国)有限公司": "英特尔",
    "英飞拉网络(上海)有限公司": "英飞拉",
    "诺马连接技术(无锡)有限公司": "诺马",
    "赛特福德(深圳)贸易有限公司": "赛特福德",
    "辽宁三友商贸有限责任公司": "三友商贸",
    "达凯(上海)电子科技有限公司": "达凯",
    "达能亚太(上海)管理有限公司": "达能",
    "钇镭科(北京)光学电子制造有限公司": "钇镭科",
    "锦海捷亚国际货运有限公司": "锦海捷亚",
    "镭富电子设备(上海)有限公司": "镭富电子",
    "默天旎贸易(上海)有限公司": "默天旎",
    # 额外：格柏科技合并
    "格柏(上海)工业数控设备有限公司": "格柏科技",
    # 额外：上海申创
    "上海申创中小企业合作交流技术促进中心": "其他",
}

# ── 从文件名提取公司名 ─────────────────────────────
_COMPANY_FROM_FN = re.compile(
    r"[_\-]([^_\-]+(?:有限公司|Co[.,]?\s*Ltd\.?|Corporation|Inc\.|GmbH))"
)

def extract_company_from_filename(fn: str) -> str:
    """从文件名提取公司名，返回空串如果提取不到。"""
    m = _COMPANY_FROM_FN.search(fn)
    if m:
        company = m.group(1).strip()
        # 排除乙方名称
        vendor_kw = ["莱升", "泛纬", "LSC", "lsc"]
        if any(kw in company for kw in vendor_kw):
            return ""
        return company
    return ""


# ── 主流程 ─────────────────────────────────────────
def main():
    records = []
    with open(AUDIT_PATH, encoding="utf-8") as f:
        for line in f:
            records.append(json.loads(line))

    changes = {
        "group_normalized": 0,
        "company_from_filename": 0,
        "amount_fixed": 0,
        "company_noise_fixed": 0,
    }

    for r in records:
        # 1. 集团名规范化
        g = r.get("detected_group", "")
        if g in GROUP_NORMALIZE:
            r["detected_group"] = GROUP_NORMALIZE[g]
            changes["group_normalized"] += 1

        # 2. 修复空公司名
        company = r.get("detected_company", "")
        if not company:
            fn = r.get("file_name", "")
            new_company = extract_company_from_filename(fn)
            if new_company:
                r["detected_company"] = new_company
                changes["company_from_filename"] += 1

        # 3. 修复金额疑似日期（2014.6 这种）
        for amt_field in ["contract_total_amount", "annual_maintenance_fee",
                          "tax_included_amount", "tax_excluded_amount"]:
            val = r.get(amt_field)
            if val:
                val_str = str(val)
                if re.match(r"^20\d{2}\.\d{1,2}$", val_str):
                    r[amt_field] = None
                    changes["amount_fixed"] += 1
                elif 2000 <= float(val) <= 2030:
                    r[amt_field] = None
                    changes["amount_fixed"] += 1

        # 4. 修复公司名前缀噪音
        company = r.get("detected_company", "")
        noise_prefixes = ["服务合同", "采购单-", "保密合同-", "维护合同-", "备案"]
        for prefix in noise_prefixes:
            if company.startswith(prefix):
                r["detected_company"] = company[len(prefix):].lstrip("-").strip()
                changes["company_noise_fixed"] += 1
                break

    # 写回
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 同步到 audit_fixed.jsonl
    import shutil
    shutil.copy(OUTPUT_PATH, "output/audit_fixed.jsonl")

    print("修复完成:")
    for k, v in changes.items():
        print(f"  {k}: {v}处")
    print(f"\n总计处理 {len(records)} 条记录")


if __name__ == "__main__":
    main()

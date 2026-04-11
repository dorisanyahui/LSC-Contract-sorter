# -*- coding: utf-8 -*-
"""Second pass: reclassify more companies from '其他' and fix internal/vendor names."""
import json
import sys
sys.stdout.reconfigure(encoding='utf-8')

# More manual group assignments
MANUAL_GROUP_2 = {
    # ── 内部文件 (莱升/泛纬 variants) ──
    "上海业信信息科技": "内部文件",
    "上海业升信息科技": "内部文件",
    "上海昇升信息科技": "内部文件",
    "泛都软件": "内部文件",
    "上海莱禾商务": "内部文件",  # 莱禾 ≈ 莱升 OCR variant

    # ── 因特尔 = 英特尔 Intel ──
    "因特尔": "英特尔",

    # ── 丰树集团 (Mapletree) more subsidiaries ──
    "佛山嘉拓置业": "丰树集团",
    "广州宝瓶星": "丰树集团",

    # ── 琉璃奥秃 = 中强光电 OCR variant ──
    "琉璃奥秃": "中强光电",

    # ── 礼来 (Eli Lilly) ──
    "礼来": "礼来",

    # ── 熊悦轩尼夏桐 (Moet Hennessy) ──
    "熊悦轩尼夏桐": "酩悦轩尼诗",

    # ── 德尔福 (Delphi) ──
    "德尔福": "德尔福",

    # ── 金宝医疗 (Kinpo/Compal) ──
    "金宝医疗": "金宝",

    # ── 阿尔派矿山 → 山特维克 ──
    "阿尔派矿山": "山特维克",

    # ── 欧亚电气 ──
    "欧亚电气": "欧亚电气",

    # ── 广州立德技术检测 → 必维集团 (Lida = BV subsidiary) ──
    "广州立德技术": "必维集团",

    # ── 福斯华/福秦华 (Foxconn?) ──
    "福斯华电器": "福斯华",
    "福秦华电器": "福斯华",

    # ── 上海汇众汽车 (Huizhong Auto / SAIC subsidiary) ──
    "上海汇众汽车": "上海汇众",

    # ── 钇镭科 (YRC?) ──
    "钇镭科": "钇镭科",

    # ── 六州酒店 ──
    "六州酒店": "六州酒店",

    # ── 前锦网络 ──
    "前锦网络": "前锦网络",

    # ── 长城国际展览 ──
    "长城国际展览": "长城国际展览",

    # ── 上海赛车场 ──
    "上海赛车场": "上海赛车场",

    # ── 上海英模特制衣 ──
    "上海英模特": "英模特",

    # ── 美迪希实验 ──
    "美迪希实验": "美迪希",
}

# Names that are garbage/noise and should stay in 其他
GARBAGE_NAMES = {
    "", "BASS集团", "Balance Sheet,Inc", "CENSE Soluare HardvareService Corp",
    "Development Co., Ltd", "Limited有限公司", "Pages Inc",
    "Shanghai） Co.,Ltd", "Solutlons （HongKong） Limited",
    "corporation普通私人股份有限公司", "影像有限公司", "设备有限公司",
    "新统有限公司", "套（集团", "服务合同",
    "上海某信息科技有限公司", "上海某某信息科技有限公司",
    "上海某某咨询有限公司", "上海某某商务咨询有限公司",
}


def classify_company(name):
    if not name or name in GARBAGE_NAMES:
        return None
    name_lower = name.lower()
    best_match = None
    best_len = 0
    for substr, group in MANUAL_GROUP_2.items():
        if substr.lower() in name_lower and len(substr) > best_len:
            best_match = group
            best_len = len(substr)
    return best_match


def main():
    audit_path = "output/audit.jsonl"
    records = []
    with open(audit_path, "r", encoding="utf-8") as f:
        for line in f:
            records.append(json.loads(line))

    reclassified = 0
    for r in records:
        if r.get("detected_group") != "其他":
            continue
        company = r.get("detected_company", "")
        new_group = classify_company(company)
        if new_group:
            r["detected_group"] = new_group
            reclassified += 1

    with open(audit_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Reclassified: {reclassified} more records")

    # Show final count
    others = {}
    for r in records:
        if r.get("detected_group") == "其他":
            c = r.get("detected_company", "")
            others[c] = others.get(c, 0) + 1

    print(f"Remaining in 其他: {sum(others.values())} records, {len(others)} companies")
    for c in sorted(others.keys()):
        if c:
            print(f"  {others[c]:3d}  {c}")
    empty_count = others.get("", 0)
    print(f"  {empty_count:3d}  (empty company name)")


if __name__ == "__main__":
    main()

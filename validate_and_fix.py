"""
validate_and_fix.py — 校验 audit.jsonl 并自动修复可修复的问题

问题分类：
  1. "关于" 前缀   — detected_company/group 以"关于"开头，strip 后重新映射
  2. 乙方误识别   — 我方公司名（莱升/LSC/泛纬）被识别为甲方
  3. OCR 噪音     — 公司名是句子片段、prompt 模板文字等
  4. 无集团映射   — 真实客户但不在 mapping 文件中（输出 Excel 供手动添加）
  5. 空公司名     — detected_company 为空，尝试从文件名提取

运行：
  python validate_and_fix.py [--apply]   加 --apply 才写入修复结果
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from collections import defaultdict

# ── 常量 ──────────────────────────────────────────────────────────────────────

AUDIT_FILE = Path("output/audit.jsonl")
FIXED_FILE = Path("output/audit_fixed.jsonl")
REPORT_FILE = Path("output/validation_report.xlsx")

VENDOR_BLOCKLIST = [
    "莱升", "泛纬", "lsc", "laisheng", "fanwei",
    "license consulting", "license software", "license-solution",
    "formware", "上海莱升",
]

# 明显不是公司名的特征
NOISE_PATTERNS = [
    re.compile(r"^(关于|regarding|re:)\s*", re.IGNORECASE),
    re.compile(r"(认为|必要时|任何|委托|甲方|乙方|注意|提示|请|该|依照|注册并存在)"),
    re.compile(r"(Grand Total|Excl\.|Prepared by|annual maintenance|Tax Fee|RMB\s*\d)", re.IGNORECASE),
    re.compile(r"^\s*(for|by|to|from)\s+", re.IGNORECASE),
    re.compile(r"\)\s*\("),           # ") (" 残缺括号组合
    re.compile(r"^[^a-zA-Z\u4e00-\u9fff]*$"),  # 纯符号/数字，无文字
    re.compile(r"^corporation\b", re.IGNORECASE),  # "corporation普通私人..."
    re.compile(r"^Holding\b.*Co\.Ltd$", re.IGNORECASE),  # "Holding(China) Co.Ltd"
    re.compile(r"^[)）]"),             # 以反括号开头（OCR截断残片）
    re.compile(r"^(就|特)(甲方|乙方|双方)"),  # "就甲方为乙方之..."/"特甲方..."合同条款
    re.compile(r"^(乙方欲|甲方欲|甲方提供|双方同意|兹委托|本合同|鉴于)"),
    re.compile(r"(为乙方之|为乙方提供)"),
]

# OCR 把我方公司名误读的变体（不在 blocklist 的）
VENDOR_OCR_VARIANTS = re.compile(
    r"(ENsE|L\.ICENsE|LlCENSE|Lleense|CENSE|LlCENsE|LICENsE)\s+Software",
    re.IGNORECASE
)

# ── 工具函数 ──────────────────────────────────────────────────────────────────

def is_vendor(name: str) -> bool:
    """检测是否是我方公司名（乙方）"""
    nl = name.lower()
    if VENDOR_OCR_VARIANTS.search(name):
        return True
    return any(v in nl for v in VENDOR_BLOCKLIST)


def is_noise(name: str) -> bool:
    """检测是否是噪音文字（句子片段、模板文字等）"""
    if len(name) > 60:
        return True
    return any(p.search(name) for p in NOISE_PATTERNS)


def strip_guan_yu(name: str) -> str:
    """去掉"关于"前缀"""
    return re.sub(r"^关于\s*", "", name).strip()


def looks_like_real_company(name: str) -> bool:
    """判断是否像真实公司名（用于识别值得手动映射的记录）"""
    if not name or len(name) < 4:
        return False
    if is_noise(name) or is_vendor(name):
        return False
    # 包含公司常见后缀
    company_markers = ["有限公司", "有限责任", "股份", "Co.", "Ltd", "Inc", "Corp",
                       "集团", "控股", "贸易", "科技", "电子", "工业", "化工"]
    return any(m in name for m in company_markers)


def infer_group_from_company(company: str, mapper) -> str | None:
    """尝试用 mapper 重新映射（去关于前缀后）"""
    cleaned = strip_guan_yu(company)
    if cleaned != company:
        result = mapper.map(cleaned)
        if result and result != cleaned:
            return result, cleaned
    return None, company


# ── 主校验逻辑 ─────────────────────────────────────────────────────────────────

def validate(records: list[dict], mapper) -> tuple[list[dict], dict]:
    """
    校验所有记录，返回 (fixed_records, stats)
    stats 包含各类问题的统计和样本
    """
    stats = defaultdict(list)
    fixed = []

    for r in records:
        r = dict(r)  # 浅拷贝
        company = r.get("detected_company", "") or ""
        group = r.get("detected_group", "") or ""
        fname = r.get("file_name", "")

        fixes_applied = []

        # ── 问题1：乙方（莱升/LSC/泛纬）出现 → 归入"内部文件" ────────────
        if is_vendor(company) or is_vendor(group):
            stats["internal_file"].append(fname)
            r["detected_group"] = "内部文件"
            fixes_applied.append("moved_to_internal")

        # ── 问题2："关于"前缀（公司名或集团名）──────────────────────────
        elif company.startswith("关于") or group.startswith("关于"):
            cleaned_company = strip_guan_yu(company)
            cleaned_group = strip_guan_yu(group)
            stats["guan_yu_prefix"].append((fname, company, cleaned_company))
            r["detected_company"] = cleaned_company
            # 尝试重新映射集团
            new_group = mapper.map(cleaned_company) if cleaned_company else None
            if new_group and new_group != cleaned_company:
                r["detected_group"] = new_group
            else:
                # 映射不到集团，归入"其他"
                r["detected_group"] = "其他"
            fixes_applied.append("stripped_guan_yu")

        # ── 问题3：OCR 噪音公司名 ──────────────────────────────────────────
        elif company and is_noise(company):
            stats["noise_company"].append((fname, company))
            r["detected_company"] = ""
            r["detected_group"] = "未分组"
            fixes_applied.append("cleared_noise_company")

        # ── 问题4：公司名当集团名 → 只有当它不是有效集团名时才归入"其他"──
        elif group and group == company:
            # 先检查该公司名是否本身就是 mapping 中合法的集团名
            remapped = mapper.map(company)
            if remapped and remapped != company:
                # 找到了上级集团，更新
                r["detected_group"] = remapped
                fixes_applied.append(f"remapped_to:{remapped}")
            elif not mapper.map(company):
                # 既不是集团名也没有上级映射，归入"其他"
                stats["company_used_as_group"].append((fname, company))
                r["detected_group"] = "其他"
                fixes_applied.append("moved_to_other")
            # else: company 本身就是有效集团名，保留不动

        # ── 问题0：集团名强制重命名（mapping 合并时使用）────────────────────
        GROUP_RENAMES = {
            "三协集团":           "日本电产",
            "摩迪(上海)咨询有限公司": "摩迪",
            "摩迪英联认证有限公司":    "摩迪",
            "力运集团":           "力运",
            "上海挪威":           "DNV",
        }
        current = r.get("detected_group", "") or ""
        if current in GROUP_RENAMES:
            r["detected_group"] = GROUP_RENAMES[current]
            fixes_applied.append(f"renamed_group:{current}->{GROUP_RENAMES[current]}")

        # ── 问题4c：已有集团名 → 重新过 mapper，防止 mapping 更新后不同步 ──
        current_group = r.get("detected_group", "") or ""
        if current_group and current_group not in ("其他", "未分组", "内部文件", ""):
            company_now = r.get("detected_company", "") or ""
            remapped = mapper.map(company_now) if company_now else None
            if remapped and remapped != current_group:
                r["detected_group"] = remapped
                fixes_applied.append(f"remapped:{current_group}->{remapped}")
            elif not remapped and company_now and company_now != current_group:
                # 公司名无法映射到当前集团 → 用文件名再确认，否则重置为"其他"再由4b处理
                fname_group = mapper.map_by_filename(fname) if fname else None
                if fname_group:
                    r["detected_group"] = fname_group
                    fixes_applied.append(f"reconfirmed_by_filename:{fname_group}")
                else:
                    r["detected_group"] = "其他"
                    fixes_applied.append(f"reset_unverifiable:{current_group}")

        # ── 问题4b：未分组/其他 → 尝试重新映射，映射不到才留"其他" ───────
        if r.get("detected_group") in ("未分组", "其他", "", None):
            company_now = r.get("detected_company", "") or ""
            remapped = mapper.map(company_now) if company_now else None
            if remapped and remapped != company_now:
                r["detected_group"] = remapped
                fixes_applied.append(f"rescued_from_other:{remapped}")
                stats["rescued_from_other"].append((fname, company_now, remapped))
            else:
                # 公司名映射失败 → 用文件名再试一次（处理乙方名误识别的情况）
                remapped_by_fname = mapper.map_by_filename(fname) if fname else None
                if remapped_by_fname:
                    r["detected_group"] = remapped_by_fname
                    fixes_applied.append(f"rescued_by_filename:{remapped_by_fname}")
                    stats["rescued_from_other"].append((fname, company_now, remapped_by_fname))
                else:
                    r["detected_group"] = "其他"
                    fixes_applied.append("unmapped_to_other")

        # ── 问题5：空公司名 ───────────────────────────────────────────────
        if not r.get("detected_company"):
            stats["empty_company"].append(fname)

        if fixes_applied:
            r["_fixes"] = fixes_applied
            stats["total_fixed"].append(fname)

        fixed.append(r)

    return fixed, dict(stats)


# ── 报告生成 ──────────────────────────────────────────────────────────────────

def build_unmapped_report(records: list[dict]) -> list[dict]:
    """
    找出真实客户但没有集团映射的公司，输出供手动添加到 mapping 文件
    """
    # 统计每个集团/公司出现次数
    group_counts = defaultdict(int)
    group_companies = defaultdict(set)
    for r in records:
        g = r.get("detected_group", "") or "未分组"
        c = r.get("detected_company", "") or ""
        group_counts[g] += 1
        if c:
            group_companies[g].add(c)

    rows = []
    for group, count in sorted(group_counts.items(), key=lambda x: -x[1]):
        if group in ("未分组", ""):
            continue
        companies = group_companies[group]
        # 只有当集团名 == 公司名（mapper 回落到公司名）时才需要手动映射
        for c in companies:
            if group == c and looks_like_real_company(c):
                rows.append({
                    "公司名称": c,
                    "当前集团": group,
                    "文件数": count,
                    "建议集团名": "",   # 人工填写
                    "备注": "",
                })
                break

    return sorted(rows, key=lambda x: -x["文件数"])


def print_summary(stats: dict, records: list[dict]) -> None:
    total = len(records)
    print(f"\n{'='*60}")
    print(f"  校验结果汇总  （共 {total} 条记录）")
    print(f"{'='*60}")

    categories = [
        ("vendor_misidentified", "乙方被误识别为甲方（公司名）"),
        ("vendor_as_group",      "乙方被误识别为集团名"),
        ("guan_yu_prefix",       '"关于" 前缀 → 已自动修复'),
        ("noise_company",        "OCR噪音公司名 → 已清空"),
        ("company_used_as_group","公司名当集团名（无集团映射）"),
        ("empty_company",        "公司名为空"),
        ("total_fixed",          "本次自动修复"),
    ]

    for key, label in categories:
        cnt = len(stats.get(key, []))
        if cnt:
            print(f"  {label:35s} {cnt:4d} 条")

    # 集团分布
    group_counts = defaultdict(int)
    for r in records:
        g = r.get("detected_group") or "未分组"
        group_counts[g] += 1

    real_groups = sum(1 for g, c in group_counts.items() if c >= 5 and g != "未分组")
    singleton_groups = sum(1 for g, c in group_counts.items() if c == 1 and g != "未分组")
    print(f"\n  ≥5个文件的集团:   {real_groups}")
    print(f"  仅1个文件的分组:  {singleton_groups}（建议手动添加到mapping文件）")
    print(f"  未分组:           {group_counts.get('未分组', 0)}")
    print(f"{'='*60}\n")


# ── 入口 ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="校验并修复 audit.jsonl")
    parser.add_argument("--apply", action="store_true",
                        help="写入修复后的 audit_fixed.jsonl（不加此参数只输出报告）")
    args = parser.parse_args()

    if not AUDIT_FILE.exists():
        print(f"[ERROR] 找不到 {AUDIT_FILE}")
        sys.exit(1)

    # 加载 mapper
    from src.config import get_settings
    from src.mapping.company_mapper import CompanyMapper
    settings = get_settings()
    mapper = CompanyMapper()
    mapper.load(settings.mapping_file)

    # 包装 mapper.map 供使用
    class MapperWrapper:
        def __init__(self, m): self._m = m
        def map(self, name: str) -> str | None:
            r = self._m.map_to_group(name)
            return r if r and r != name else None
        def map_by_filename(self, fname: str) -> str | None:
            r = self._m.map_by_filename(fname)
            return r if r else None

    mw = MapperWrapper(mapper)

    # 读取记录（去重）
    seen = set()
    records = []
    for line in AUDIT_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        key = r.get("file_md5") or r.get("file_name")
        if key in seen:
            continue
        seen.add(key)
        records.append(r)

    print(f"读取 {len(records)} 条记录（已去重）")

    # 校验
    fixed_records, stats = validate(records, mw)
    print_summary(stats, fixed_records)

    # 生成待手动映射的报告
    unmapped = build_unmapped_report(fixed_records)
    print(f"需要手动映射到集团的公司: {len(unmapped)} 个")

    if unmapped:
        try:
            import pandas as pd
            df = pd.DataFrame(unmapped)
            df.to_excel(REPORT_FILE, index=False)
            print(f"已生成: {REPORT_FILE}")
            print("  → 请在 '建议集团名' 列填入集团名，然后添加到 mapping 文件")
        except Exception as e:
            print(f"[WARN] 无法生成 Excel 报告: {e}")
            for row in unmapped[:20]:
                print(f"  [{row['文件数']}] {row['公司名称']}")

    # 写入修复结果
    if args.apply:
        # 移除内部 _fixes 字段
        for r in fixed_records:
            r.pop("_fixes", None)
        FIXED_FILE.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in fixed_records),
            encoding="utf-8"
        )
        print(f"\n已写入修复结果: {FIXED_FILE}")
        print("如满意，运行以下命令替换原文件并重新生成汇总表：")
        print("  copy output\\audit_fixed.jsonl output\\audit.jsonl")
        print("  python generate_client_summary.py")
    else:
        print("\n加 --apply 参数可写入修复结果（当前为只读模式）")


if __name__ == "__main__":
    main()

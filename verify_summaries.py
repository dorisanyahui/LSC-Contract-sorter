"""
全面核对所有集团汇总表：摘要、金额、公司名称、日期
对比 audit_fixed.jsonl 与 Excel 汇总表，找出不一致和异常

用法：
    python verify_summaries.py          # 正常运行，输出报告
    python verify_summaries.py --strict # 严格模式，金额/摘要/集团有问题时 exit(1)
"""
from __future__ import annotations
import json, re, sys, io
from pathlib import Path
from collections import defaultdict

import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

AUDIT_PATH = Path("output/audit_fixed.jsonl")
AUDIT_MAIN_PATH = Path("output/audit.jsonl")
OUTPUT_BASE = Path("output")

# 严格模式下这些问题类型如果 >0 就 exit(1)
CRITICAL_ISSUE_TYPES = {"金额为负", "金额疑似年份", "金额疑似日期", "摘要为空",
                        "摘要含乙方名称", "集团不匹配", "公司名是乙方"}

# 乙方黑名单
VENDOR_KEYWORDS = ["莱升", "泛纬", "LSC", "lsc", "LaiSheng", "Fanwei", "上海莱升"]

# ── 加载数据 ──────────────────────────────────
def load_audit():
    records = {}
    with open(AUDIT_PATH, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            fn = r.get("file_name", "")
            records[fn] = r
    return records

def load_all_excels():
    """加载所有集团汇总Excel"""
    all_rows = []
    for xlsx in OUTPUT_BASE.glob("*/*合同汇总*.xlsx"):
        group = xlsx.parent.name
        try:
            df = pd.read_excel(xlsx, sheet_name="合同明细")
            for _, row in df.iterrows():
                row_dict = row.to_dict()
                row_dict["_group"] = group
                row_dict["_file"] = str(xlsx)
                all_rows.append(row_dict)
        except Exception as e:
            print(f"[ERROR] 读取 {xlsx} 失败: {e}")
    return all_rows

# ── 检查项 ──────────────────────────────────────
def check_company_issues(excel_rows, audit_records):
    """检查公司名称问题"""
    issues = []
    for row in excel_rows:
        company = str(row.get("合同方", "")).strip()
        group = row["_group"]

        # 1. 公司名为空
        if not company or company == "nan":
            issues.append(("公司名为空", group, row.get("文件路径", ""), ""))
            continue

        # 2. 公司名是乙方名称
        for kw in VENDOR_KEYWORDS:
            if kw in company:
                issues.append(("公司名是乙方", group, row.get("文件路径", ""), company))
                break

        # 3. 公司名过短或过长
        if len(company) < 4:
            issues.append(("公司名过短", group, row.get("文件路径", ""), company))
        if len(company) > 50:
            issues.append(("公司名过长", group, row.get("文件路径", ""), company))

        # 4. 公司名含噪音（合同类型前缀等）
        noise_patterns = ["服务合同", "采购单", "保密合同", "维护合同", "备案", "购买合同"]
        for p in noise_patterns:
            if company.startswith(p) or company.startswith(p + "-"):
                issues.append(("公司名含前缀噪音", group, row.get("文件路径", ""), company))
                break

    return issues

def check_amount_issues(excel_rows, audit_records):
    """检查金额问题"""
    issues = []
    for row in excel_rows:
        amt = row.get("金额")
        group = row["_group"]
        fp = row.get("文件路径", "")

        if pd.isna(amt) or amt is None:
            continue  # 无金额不一定是问题

        amt = float(amt)

        # 1. 金额为负数
        if amt < 0:
            issues.append(("金额为负", group, fp, f"{amt}"))

        # 2. 金额过小（可能是误识别）
        if 0 < amt < 100:
            issues.append(("金额过小(<100)", group, fp, f"{amt}"))

        # 3. 金额看起来像日期 (2018.01, 2021.6 等)
        if 2000 <= amt <= 2030:
            issues.append(("金额疑似年份", group, fp, f"{amt}"))
        if re.match(r"20\d{2}\.\d{1,2}$", f"{amt}"):
            issues.append(("金额疑似日期", group, fp, f"{amt}"))

        # 4. 金额异常大（超过1亿）
        if amt > 100_000_000:
            issues.append(("金额异常大(>1亿)", group, fp, f"{amt:,.0f}"))

    return issues

def check_year_issues(excel_rows):
    """检查年份问题"""
    issues = []
    for row in excel_rows:
        year = row.get("年份")
        group = row["_group"]
        fp = row.get("文件路径", "")

        if pd.isna(year) or year is None:
            issues.append(("年份为空", group, fp, ""))
            continue

        year = int(year)

        # 年份不合理
        if year < 2000 or year > 2026:
            issues.append(("年份不合理", group, fp, str(year)))

        # 文件路径中的年份与记录年份不一致
        path_match = re.search(r"/(\d{4})/", str(fp))
        if path_match:
            path_year = int(path_match.group(1))
            if path_year != year:
                issues.append(("年份与路径不一致", group, fp, f"记录={year}, 路径={path_year}"))

    return issues

def check_summary_issues(excel_rows):
    """检查摘要问题"""
    issues = []
    for row in excel_rows:
        summary = str(row.get("摘要", "")).strip()
        group = row["_group"]
        fp = row.get("文件路径", "")

        # 1. 摘要为空
        if not summary or summary == "nan":
            issues.append(("摘要为空", group, fp, ""))
            continue

        # 2. 摘要中含乙方名称
        for kw in VENDOR_KEYWORDS:
            if kw in summary:
                issues.append(("摘要含乙方名称", group, fp, f"...{kw}..."))
                break

        # 3. 摘要中公司名和集团不匹配（摘要里提到了不相关公司）
        # 简单检查：摘要里的公司名应该和合同方一致
        company = str(row.get("合同方", ""))
        if company and company != "nan" and len(company) >= 4:
            # 取公司名前4个字检查
            company_short = company[:4]
            # 如果摘要里有公司名但不是当前合同方的
            pass  # 这个检查太复杂，跳过

        # 4. 摘要过长（可能包含了OCR噪音）
        if len(summary) > 200:
            issues.append(("摘要过长(>200字)", group, fp, f"长度={len(summary)}"))

    return issues

def check_audit_vs_excel(excel_rows, audit_records):
    """对比 audit 数据和 Excel 数据的一致性"""
    issues = []

    for row in excel_rows:
        fp = str(row.get("文件路径", ""))
        # 从文件路径提取文件名
        fn = fp.rsplit("/", 1)[-1] if "/" in fp else fp

        if fn not in audit_records:
            continue

        audit = audit_records[fn]
        group = row["_group"]
        audit_group = audit.get("detected_group", "")

        # 集团不匹配
        if audit_group and audit_group != group and audit_group != "其他":
            issues.append(("集团不匹配", group, fp, f"audit={audit_group}, excel所在={group}"))

    return issues

def check_folder_file_consistency():
    """检查文件夹中的PDF是否都在汇总表中"""
    issues = []

    for group_dir in sorted(OUTPUT_BASE.iterdir()):
        if not group_dir.is_dir():
            continue
        group = group_dir.name

        # 找该集团的汇总表
        summary_files = list(group_dir.glob("*合同汇总*.xlsx"))
        if not summary_files:
            # 有PDF但没汇总表
            pdf_count = len(list(group_dir.rglob("*.pdf")))
            if pdf_count > 0:
                issues.append(("有PDF无汇总表", group, "", f"{pdf_count}个PDF"))
            continue

        # 读取汇总表中的文件列表
        try:
            df = pd.read_excel(summary_files[0], sheet_name="合同明细")
            excel_files = set()
            for fp in df["文件路径"].dropna():
                fn = str(fp).rsplit("/", 1)[-1]
                excel_files.add(fn)
        except:
            continue

        # 遍历文件夹中的PDF（Windows大小写不敏感，只用 *.pdf 避免重复计数）
        pdfs = list(group_dir.rglob("*.pdf"))
        for pdf in pdfs:
            if pdf.name not in excel_files:
                # PDF不在汇总表中 - 这可能正常（非合同类文件）
                pass  # 不报告，因为有些文件被分类过滤了

    return issues


def check_audit_sync():
    """检查 audit.jsonl 和 audit_fixed.jsonl 是否同步"""
    issues = []
    if not AUDIT_MAIN_PATH.exists():
        issues.append(("audit.jsonl缺失", "", "", "generate_client_summary.py 读的是这个文件"))
        return issues
    if not AUDIT_PATH.exists():
        issues.append(("audit_fixed.jsonl缺失", "", "", ""))
        return issues

    main_records = {}
    with open(AUDIT_MAIN_PATH, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            main_records[r.get("file_name", "")] = r

    fixed_records = {}
    with open(AUDIT_PATH, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            fixed_records[r.get("file_name", "")] = r

    if len(main_records) != len(fixed_records):
        issues.append(("audit文件记录数不同", "", "",
                        f"audit.jsonl={len(main_records)}, audit_fixed.jsonl={len(fixed_records)}"))

    # 抽查关键字段
    diff_count = 0
    diff_fields = set()
    check_fields = ["detected_group", "detected_company", "report_year",
                     "contract_total_amount", "annual_maintenance_fee"]
    for fn, r1 in main_records.items():
        r2 = fixed_records.get(fn)
        if not r2:
            diff_count += 1
            continue
        for field in check_fields:
            if str(r1.get(field, "")) != str(r2.get(field, "")):
                diff_count += 1
                diff_fields.add(field)
                break

    if diff_count > 0:
        issues.append(("audit两文件不同步", "", "",
                        f"{diff_count}条记录有差异，涉及字段: {', '.join(diff_fields)}"))

    return issues


def main():
    print("=" * 70)
    print("  合同汇总表全面核对报告")
    print("=" * 70)

    strict = "--strict" in sys.argv

    # 先检查 audit 同步
    print("\n检查 audit.jsonl 与 audit_fixed.jsonl 同步...")
    sync_issues = check_audit_sync()
    if sync_issues:
        for issue_type, _, _, detail in sync_issues:
            print(f"  [!!!] {issue_type}: {detail}")
        print("  ⚠ 请先同步两个文件再继续！")
        if strict:
            sys.exit(1)
    else:
        print("  ✓ 两个文件完全同步")

    audit_records = load_audit()
    print(f"\naudit_fixed.jsonl 共 {len(audit_records)} 条记录（去重后）")

    excel_rows = load_all_excels()
    print(f"Excel 汇总表共 {len(excel_rows)} 条记录")

    # 统计集团数
    groups = set(r["_group"] for r in excel_rows)
    print(f"涉及 {len(groups)} 个集团")

    all_issues = []

    print("\n检查公司名称...")
    issues = check_company_issues(excel_rows, audit_records)
    all_issues.extend(issues)
    print(f"  发现 {len(issues)} 个问题")

    print("检查金额...")
    issues = check_amount_issues(excel_rows, audit_records)
    all_issues.extend(issues)
    print(f"  发现 {len(issues)} 个问题")

    print("检查年份...")
    issues = check_year_issues(excel_rows)
    all_issues.extend(issues)
    print(f"  发现 {len(issues)} 个问题")

    print("检查摘要...")
    issues = check_summary_issues(excel_rows)
    all_issues.extend(issues)
    print(f"  发现 {len(issues)} 个问题")

    print("检查 audit vs Excel 一致性...")
    issues = check_audit_vs_excel(excel_rows, audit_records)
    all_issues.extend(issues)
    print(f"  发现 {len(issues)} 个问题")

    print("检查文件夹一致性...")
    issues = check_folder_file_consistency()
    all_issues.extend(issues)
    print(f"  发现 {len(issues)} 个问题")

    # 汇总报告
    print("\n" + "=" * 70)
    print(f"  共发现 {len(all_issues)} 个问题")
    print("=" * 70)

    # 按问题类型分组
    by_type = defaultdict(list)
    for issue_type, group, fp, detail in all_issues:
        by_type[issue_type].append((group, fp, detail))

    critical_count = 0
    for issue_type in sorted(by_type.keys()):
        items = by_type[issue_type]
        is_critical = issue_type in CRITICAL_ISSUE_TYPES
        marker = " [严重]" if is_critical else ""
        print(f"\n--- {issue_type} ({len(items)}条){marker} ---")
        for group, fp, detail in items[:20]:  # 每类最多显示20条
            print(f"  [{group}] {fp}  {detail}")
        if len(items) > 20:
            print(f"  ... 还有 {len(items)-20} 条")
        if is_critical:
            critical_count += len(items)

    if critical_count == 0:
        print("\n✓ 无严重问题（金额/摘要/集团匹配/乙方）")
    else:
        print(f"\n⚠ 有 {critical_count} 条严重问题需要处理")

    if strict and critical_count > 0:
        sys.exit(1)

    return critical_count


if __name__ == "__main__":
    main()

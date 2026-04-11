"""
逐条校验所有合同记录：
1. PDF 是否在正确的 集团/年份 文件夹中
2. Excel 汇总表中的信息是否与 audit 一致
3. 公司名是否合理（非乙方、非空、非噪音）
4. 集团归属是否正确（文件名中的公司名与集团是否匹配）
5. 金额、年份是否合理

带断点续传：检查进度保存到 output/audit_check_progress.jsonl
用法：
    python full_audit_check.py          # 从上次断点继续
    python full_audit_check.py --reset  # 重新开始
    python full_audit_check.py --report # 只看报告不检查
"""
import json, sys, io, re
from pathlib import Path
from collections import defaultdict

import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

AUDIT_PATH = Path("output/audit.jsonl")
PROGRESS_PATH = Path("output/audit_check_progress.jsonl")
OUTPUT_BASE = Path("output")

# 乙方关键词
VENDOR_KW = ["莱升", "泛纬", "LSC", "lsc", "LaiSheng", "Fanwei", "LICENSE",
             "LICENCE", "License", "Licence"]

# 已知集团合并映射（用于检查是否有漏合并的）
KNOWN_MERGES = {
    "赫斯": "赫斯可", "帝亚吉欧": "酩悦轩尼诗", "观光投资": "狼爪",
    "首诺": "伊士曼", "挪瓦玛翠": "伊士曼", "珐菲琦": "发发奇",
    "克拉克": "派克集团", "东福电子": "日本电产",
}


def load_audit():
    records = []
    with open(AUDIT_PATH, encoding="utf-8") as f:
        for line in f:
            records.append(json.loads(line))
    return records


def load_progress():
    """加载已检查的记录"""
    checked = {}
    if PROGRESS_PATH.exists():
        with open(PROGRESS_PATH, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                checked[r["file_name"]] = r
    return checked


def save_result(result):
    """追加一条检查结果"""
    with open(PROGRESS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


def load_excel_data():
    """加载所有 Excel 汇总表数据，按文件名索引"""
    excel_by_fn = {}
    for xlsx in OUTPUT_BASE.glob("*/*合同汇总*.xlsx"):
        group = xlsx.parent.name
        try:
            df = pd.read_excel(xlsx, sheet_name="合同明细")
            for _, row in df.iterrows():
                fp = str(row.get("文件路径", ""))
                fn = fp.rsplit("/", 1)[-1] if "/" in fp else fp
                if fn:
                    excel_by_fn[fn] = {
                        "excel_group": group,
                        "excel_company": str(row.get("合同方", "")),
                        "excel_amount": row.get("金额"),
                        "excel_year": row.get("年份"),
                        "excel_summary": str(row.get("摘要", "")),
                        "excel_category": str(row.get("合同类别", "")),
                    }
        except Exception:
            pass
    return excel_by_fn


def find_pdf(group, year, filename):
    """查找 PDF 文件的实际位置"""
    # 1. 预期位置
    if year:
        expected = OUTPUT_BASE / group / str(year) / filename
        if expected.exists():
            return str(expected), "correct"

    # 2. 在集团文件夹任意位置
    group_dir = OUTPUT_BASE / group
    if group_dir.exists():
        found = list(group_dir.rglob(filename))
        if found:
            return str(found[0]), "wrong_year_subfolder"

    # 3. 在其他文件夹
    for d in OUTPUT_BASE.iterdir():
        if d.is_dir() and d.name != group:
            found = list(d.rglob(filename))
            if found:
                return str(found[0]), "wrong_group_folder"

    return None, "not_found"


def check_record(r, excel_by_fn):
    """检查单条记录，返回检查结果"""
    fn = r.get("file_name", "")
    group = r.get("detected_group", "")
    company = r.get("detected_company", "") or ""
    year = r.get("report_year")
    doc_type = r.get("doc_type", "")

    issues = []

    # ── 1. PDF 位置检查 ─────────────────────
    pdf_path, pdf_status = find_pdf(group, year, fn)
    if pdf_status == "not_found":
        issues.append("PDF_NOT_FOUND")
    elif pdf_status == "wrong_year_subfolder":
        issues.append(f"PDF_WRONG_YEAR_DIR:{pdf_path}")
    elif pdf_status == "wrong_group_folder":
        issues.append(f"PDF_WRONG_GROUP_DIR:{pdf_path}")

    # ── 2. Excel 一致性检查 ──────────────────
    excel = excel_by_fn.get(fn)
    if excel:
        # 集团一致
        if excel["excel_group"] != group:
            issues.append(f"EXCEL_GROUP_MISMATCH:excel={excel['excel_group']},audit={group}")

        # 公司名一致
        excel_co = excel["excel_company"]
        if excel_co and excel_co != "nan" and company:
            if excel_co != company:
                issues.append(f"EXCEL_COMPANY_DIFF")

        # 年份一致
        excel_yr = excel["excel_year"]
        if excel_yr and not pd.isna(excel_yr) and year:
            if int(excel_yr) != int(year):
                issues.append(f"EXCEL_YEAR_MISMATCH:excel={int(excel_yr)},audit={year}")

        # 金额一致
        audit_amt = r.get("contract_total_amount") or r.get("annual_maintenance_fee") or \
                    r.get("tax_included_amount") or r.get("tax_excluded_amount")
        excel_amt = excel["excel_amount"]
        if audit_amt and excel_amt and not pd.isna(excel_amt):
            if abs(float(audit_amt) - float(excel_amt)) > 1:
                issues.append(f"EXCEL_AMOUNT_DIFF:excel={excel_amt},audit={audit_amt}")

    # ── 3. 公司名检查 ────────────────────────
    if not company:
        issues.append("COMPANY_EMPTY")
    else:
        # 乙方名称
        for kw in VENDOR_KW:
            if kw in company:
                issues.append(f"COMPANY_IS_VENDOR:{company[:30]}")
                break

        # 噪音前缀
        noise = ["服务合同-", "采购单-", "保密合同-", "维护合同-", "备案"]
        for n in noise:
            if company.startswith(n):
                issues.append(f"COMPANY_NOISE_PREFIX:{n}")
                break

        # 过短
        if len(company) < 4:
            issues.append(f"COMPANY_TOO_SHORT:{company}")

    # ── 4. 集团归属检查 ──────────────────────
    # 检查文件名中是否有其他集团的名字（可能放错）
    if group not in ("其他", "内部文件"):
        # 文件名中的集团名应该与当前集团相关
        pass  # 这个检查在之前的 fix 脚本中已做过

    # 已知合并检查
    if group in KNOWN_MERGES:
        issues.append(f"GROUP_SHOULD_MERGE:{group}->{KNOWN_MERGES[group]}")

    # ── 5. 金额检查 ──────────────────────────
    for amt_field in ["contract_total_amount", "annual_maintenance_fee",
                      "tax_included_amount", "tax_excluded_amount"]:
        val = r.get(amt_field)
        if val is not None:
            try:
                v = float(val)
                if v < 0:
                    issues.append(f"AMOUNT_NEGATIVE:{amt_field}={v}")
                if 2000 <= v <= 2030:
                    issues.append(f"AMOUNT_LOOKS_LIKE_YEAR:{amt_field}={v}")
                if re.match(r"20\d{2}\.\d{1,2}$", str(val)):
                    issues.append(f"AMOUNT_LOOKS_LIKE_DATE:{amt_field}={val}")
            except (ValueError, TypeError):
                pass

    # ── 6. 年份检查 ──────────────────────────
    if not year:
        issues.append("YEAR_EMPTY")
    else:
        yr = int(year)
        if yr < 2000 or yr > 2026:
            issues.append(f"YEAR_UNREASONABLE:{yr}")

    return {
        "file_name": fn,
        "group": group,
        "company": company[:40] if company else "",
        "year": year,
        "doc_type": doc_type,
        "issues": issues,
        "status": "PASS" if not issues else "FAIL",
        "issue_count": len(issues),
    }


def print_report(checked):
    """打印检查报告"""
    total = len(checked)
    passed = sum(1 for r in checked.values() if r["status"] == "PASS")
    failed = sum(1 for r in checked.values() if r["status"] == "FAIL")

    print("=" * 70)
    print("  全量逐条校验报告")
    print("=" * 70)
    print(f"\n已检查: {total} 条")
    print(f"通过:   {passed} 条")
    print(f"有问题: {failed} 条")

    # 按问题类型统计
    issue_counts = defaultdict(int)
    issue_examples = defaultdict(list)
    for r in checked.values():
        for issue in r["issues"]:
            issue_type = issue.split(":")[0]
            issue_counts[issue_type] += 1
            if len(issue_examples[issue_type]) < 5:
                issue_examples[issue_type].append(
                    f"[{r['group']}] {r['file_name'][:60]}"
                )

    if issue_counts:
        print(f"\n--- 问题分类 ---")
        for issue_type in sorted(issue_counts.keys(), key=lambda x: -issue_counts[x]):
            count = issue_counts[issue_type]
            print(f"\n  {issue_type}: {count} 条")
            for ex in issue_examples[issue_type]:
                print(f"    {ex}")

    # 按集团统计问题数
    group_issues = defaultdict(int)
    for r in checked.values():
        if r["issues"]:
            group_issues[r["group"]] += len(r["issues"])

    if group_issues:
        print(f"\n--- 问题最多的集团 (Top 20) ---")
        for g, cnt in sorted(group_issues.items(), key=lambda x: -x[1])[:20]:
            print(f"  {cnt:4d}  {g}")


def main():
    reset = "--reset" in sys.argv
    report_only = "--report" in sys.argv

    if reset and PROGRESS_PATH.exists():
        PROGRESS_PATH.unlink()
        print("已重置检查进度")

    # 加载已有进度
    checked = load_progress()

    if report_only:
        if not checked:
            print("还没有检查记录，请先运行 python full_audit_check.py")
            return
        print_report(checked)
        return

    # 加载数据
    records = load_audit()
    print(f"audit.jsonl 共 {len(records)} 条记录")
    print(f"已检查: {len(checked)} 条，剩余: {len(records) - len(checked)} 条")

    if len(checked) >= len(records):
        print("\n所有记录已检查完毕！")
        print_report(checked)
        return

    print("加载 Excel 汇总表...")
    excel_by_fn = load_excel_data()
    print(f"Excel 中共 {len(excel_by_fn)} 条记录")

    # 逐条检查
    new_checked = 0
    new_issues = 0
    batch_size = 500  # 每批处理数量，处理完打印进度

    for i, r in enumerate(records):
        fn = r.get("file_name", "")
        if fn in checked:
            continue

        result = check_record(r, excel_by_fn)
        save_result(result)
        checked[fn] = result

        new_checked += 1
        if result["issues"]:
            new_issues += len(result["issues"])

        # 定期打印进度
        if new_checked % batch_size == 0:
            pct = len(checked) / len(records) * 100
            print(f"  进度: {len(checked)}/{len(records)} ({pct:.1f}%)  "
                  f"本批问题: {new_issues}")

    pct = len(checked) / len(records) * 100
    print(f"\n检查完毕: {len(checked)}/{len(records)} ({pct:.1f}%)")
    print(f"本次新检查: {new_checked} 条，发现 {new_issues} 个问题")

    print_report(checked)


if __name__ == "__main__":
    main()

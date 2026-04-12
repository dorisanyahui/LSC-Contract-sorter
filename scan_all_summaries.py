"""Scan all {group}_合同汇总.xlsx files, categorize data quality issues, dump JSON report."""
import glob, json, re, sys, io
from collections import defaultdict, Counter
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# vendor (乙方) name fragments — if present in company_name or summary (beyond the template "与X签订"), it's a leak
VENDOR_PATTERNS = [
    r'莱升', r'跃升', r'莱斯(?!特)', r'泛纬', r'LSC',
    r'Shanghai\s*LICENSE', r'LICENSE\s*Information', r'Leisheng', r'Lai\s*Sheng',
]
VENDOR_RE = re.compile('|'.join(VENDOR_PATTERNS), re.IGNORECASE)

# English VAT/OCR noise fragments that got captured as company name or bled into summary
NOISE_PATTERNS = [
    r'Excluding\s*VAT', r'Excl\.\s*VAT', r'Including\s*VAT', r'Incl\.\s*VAT',
    r'\(Inc(?!\w)', r'VAT\)',
]
NOISE_RE = re.compile('|'.join(NOISE_PATTERNS), re.IGNORECASE)

# Contract type keyword leak in company name
CTYPE_PREFIX_RE = re.compile(r'^(服务合同|维护合同|采购合同|购买合同|保密合同|项目合同|升级合同|SRF|报价单|采购订单)[-_\s]*')

# Mostly-English detection
def mostly_english(s):
    if not s: return False
    s = str(s).strip()
    if len(s) < 3: return False
    ascii_count = sum(1 for c in s if ord(c) < 128 and c.isalnum())
    return ascii_count / max(len(s), 1) > 0.7

# Suspicious summary templates
TEMPLATE_SUMMARY_RE = re.compile(r'^.{0,40}的\d{4}年服务需求表[^（]{0,3}$')  # too generic

def is_nan(v):
    return v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == ''

def check_row(group, row):
    issues = []
    company = str(row.get('合同方', '') or '').strip()
    summary = str(row.get('摘要', '') or '').strip()
    year = row.get('年份', '')
    version = str(row.get('版本号', '') or '').strip()
    amount = row.get('金额', '')
    ctype = str(row.get('合同类型', '') or '').strip()
    path = str(row.get('文件路径', '') or '').strip()

    # 1. Vendor leak in company name
    if company and VENDOR_RE.search(company):
        issues.append(('VENDOR_IN_COMPANY', company))

    # 2. Vendor leak in summary (but allow the template "与<vendor>" if it's the group name only)
    if summary and VENDOR_RE.search(summary):
        issues.append(('VENDOR_IN_SUMMARY', summary[:80]))

    # 3. OCR noise in company name
    if company and NOISE_RE.search(company):
        issues.append(('NOISE_IN_COMPANY', company))

    # 4. OCR noise in summary
    if summary and NOISE_RE.search(summary):
        issues.append(('NOISE_IN_SUMMARY', summary[:80]))

    # 5. Empty company
    if is_nan(company):
        issues.append(('COMPANY_EMPTY', path))

    # 6. Contract type prefix in company name
    if company and CTYPE_PREFIX_RE.match(company):
        issues.append(('CTYPE_PREFIX_IN_COMPANY', company))

    # 7. Group name used as company (company equals group name literally, suspicious for SRF/contract)
    if company and (company == group or company == f'{group}集团'):
        issues.append(('COMPANY_IS_GROUP', company))

    # 8. English-only company name
    if company and mostly_english(company):
        issues.append(('COMPANY_ENGLISH', company))

    # 9. Version timeline anomaly
    try:
        y = int(year) if not is_nan(year) else 0
    except: y = 0
    if version and y > 0:
        vm = re.match(r'V?(\d+)', version)
        if vm:
            maj = int(vm.group(1))
            if maj == 7 and y < 2017:
                issues.append(('VERSION_V7_PRE2017', f'{version} @ {y}'))
            if maj == 8 and y < 2023:
                issues.append(('VERSION_V8_PRE2023', f'{version} @ {y}'))

    # 10. Empty amount (not for OTHER types)
    if is_nan(amount):
        issues.append(('AMOUNT_EMPTY', f'{ctype} {path}'))

    # 11. Empty summary
    if is_nan(summary):
        issues.append(('SUMMARY_EMPTY', path))

    # 12. Summary year mismatch with report year
    if summary and y > 0:
        m = re.search(r'(\d{4})年', summary)
        if m:
            sy = int(m.group(1))
            if abs(sy - y) >= 2:  # allow ±1 for cross-year SRF
                issues.append(('SUMMARY_YEAR_MISMATCH', f'summary={sy} year={y}'))

    # 13. Suspicious low amount for maintenance-type contract
    if ctype in ('维护合同', '升级合同', '项目合同', 'SRF') and not is_nan(amount):
        try:
            a = float(amount)
            if 0 < a < 1000:
                issues.append(('AMOUNT_SUSPICIOUS_LOW', f'{ctype} ¥{a}'))
        except: pass

    return issues


def main():
    files = sorted(glob.glob('output/*/*_合同汇总.xlsx'))
    print(f'Found {len(files)} summary files', file=sys.stderr)

    # category -> list of (group, row_idx, detail)
    by_cat = defaultdict(list)
    total_rows = 0
    total_issues = 0
    per_group = Counter()

    for f in files:
        group = f.split('/')[-2] if '/' in f else f.split('\\')[-2]
        try:
            df = pd.read_excel(f)
        except Exception as e:
            print(f'FAIL {group}: {e}', file=sys.stderr)
            continue
        total_rows += len(df)
        for idx, row in df.iterrows():
            for cat, detail in check_row(group, row):
                by_cat[cat].append((group, int(idx), detail))
                per_group[group] += 1
                total_issues += 1

    # Dump full report JSON
    out = {
        'total_files': len(files),
        'total_rows': total_rows,
        'total_issues': total_issues,
        'category_counts': {k: len(v) for k, v in sorted(by_cat.items(), key=lambda x: -len(x[1]))},
        'top_problem_groups': dict(per_group.most_common(20)),
        'samples_per_category': {
            k: [{'group': g, 'row': i, 'detail': d} for g, i, d in v[:8]]
            for k, v in by_cat.items()
        },
        'all_issues_by_category': {
            k: [{'group': g, 'row': i, 'detail': d} for g, i, d in v]
            for k, v in by_cat.items()
        },
    }
    with open('output/summary_quality_report.json', 'w', encoding='utf-8') as fo:
        json.dump(out, fo, ensure_ascii=False, indent=2)

    # Print compact summary to stdout
    print(f'\n=== Summary Quality Report ===')
    print(f'Files: {len(files)}  Rows: {total_rows}  Issues: {total_issues}')
    print(f'\nCategory counts (sorted):')
    for k, v in sorted(out['category_counts'].items(), key=lambda x: -x[1]):
        print(f'  {k:30s} {v:5d}')
    print(f'\nTop 15 problem groups:')
    for g, c in per_group.most_common(15):
        print(f'  {g:30s} {c:4d}')
    print(f'\nFull report written to output/summary_quality_report.json')


if __name__ == '__main__':
    main()

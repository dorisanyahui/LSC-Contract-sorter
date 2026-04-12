"""Phase 1 data quality cleanup: fix audit.jsonl in place.

Fixes:
  1. SUMMARY_YEAR_MISMATCH  → replace templated year with report_year
  2. VENDOR_IN_SUMMARY      → replace vendor English name with detected_company
  3. NOISE_IN_SUMMARY       → strip English VAT/OCR noise fragments
  4. COMPANY_IS_GROUP       → re-extract company from filename

Backs up audit.jsonl before writing. Reports per-category change counts.
"""
import json, re, shutil, sys, io
from collections import Counter
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

AUDIT = 'output/audit.jsonl'
BACKUP = f'output/audit.backup.{datetime.now():%Y%m%d_%H%M%S}.jsonl'

# Strict vendor match (avoid "普莱斯" false positive): require "莱升" literal, or english "LICENSE" vendor variants
VENDOR_TOKEN_RE = re.compile(
    r'莱升|跃升(?!电)|泛纬|LSC'
    r'|(?:Shanghai\s*)?LICENSE\s*(?:Information|Sofi?ware|Hardwure|Hardware)[^，,。]*?(?:Ltd\.?|Corporation|Corp\.?|Co\.?,?\s*Ltd\.?)?',
    re.IGNORECASE
)

# "与...签订" patterns with vendor inside — replace the X with company_name
VENDOR_IN_COUNTERPARTY_RE = re.compile(
    r'与\s*(?:Shanghai\s*)?LICENSE[^签]{0,80}?签订',
    re.IGNORECASE
)
# Vendor as subject in "YYYY年 VENDOR 采购订单..." pattern
VENDOR_AS_SUBJECT_RE = re.compile(
    r'(20\d{2}年)\s*(?:Shanghai\s*)?LICENSE[^，,。]{0,80}?(?=\s*采购|\s*订单)',
    re.IGNORECASE
)
# Bracket vendor prefix "[上海莱升] " / "[莱升] "
BRACKET_VENDOR_PREFIX_RE = re.compile(r'^\s*\[[^\]]*(?:莱升|LICENSE)[^\]]*\]\s*', re.IGNORECASE)

# OCR noise fragments
NOISE_FRAGMENT_RES = [
    re.compile(r'Excluding\s*VAT\)?\s*\(?\s*Inc?\.?', re.IGNORECASE),
    re.compile(r'Excl\.?\s*VAT\)?\s*\(?\s*Inc?\.?', re.IGNORECASE),
    re.compile(r'Including\s*VAT\)?', re.IGNORECASE),
    re.compile(r'Incl\.?\s*VAT\)?', re.IGNORECASE),
    re.compile(r'The\s*annual\s*maintenance\s*fee\s*is\s*RMB\s*[\d,.]+\s*\(?\s*Inc?\.?', re.IGNORECASE),
    re.compile(r'\(Inc\b', re.IGNORECASE),
]

# Templated year in summary
TEMPLATED_YEAR_RE = re.compile(r'(的)(\d{4})(年度服务合同|年服务需求表|年[^0-9]{0,8}服务)')
SUBJECT_YEAR_RE = re.compile(r'^(\d{4})(年[^0-9])')

# Extract company name from filename
FN_COMPANY_RES = [
    # 维护合同_三井物产（上海）贸易有限公司_2021.pdf
    re.compile(r'(?:维护合同|维护服务合同|服务合同|合作协议|服务协议|采购合同|购买合同|项目合同|升级合同|SRF|软件升级|泛纬软件维护服务合同|泛纬软件升级合同)[_\-]+([^_\-]+?(?:有限公司|股份公司|股份有限公司|Co\.?,?Ltd\.?))', re.IGNORECASE),
    # 力运货运代理（上海）有限公司-全电 SRF 20230609
    re.compile(r'^([^_\-]+?(?:有限公司|股份公司|股份有限公司))'),
]

def extract_company_from_filename(fn):
    for pat in FN_COMPANY_RES:
        m = pat.search(fn)
        if m:
            name = m.group(1).strip()
            if len(name) >= 4 and not VENDOR_TOKEN_RE.search(name):
                return name
    return None


def fix_record(rec, stats):
    changed = []
    summary = rec.get('summary') or ''
    company = rec.get('detected_company') or ''
    counterparty = rec.get('detected_counterparty') or ''
    group = rec.get('detected_group') or ''
    year = rec.get('report_year')
    fn = rec.get('file_name') or ''

    # Fix 4: COMPANY_IS_GROUP — re-extract from filename
    if company and (company == group or company == f'{group}集团' or company.endswith('集团')):
        new_co = extract_company_from_filename(fn)
        if new_co and new_co != company:
            rec['detected_company'] = new_co
            company = new_co
            changed.append('COMPANY_IS_GROUP')
            stats['COMPANY_IS_GROUP'] += 1

    if not summary:
        return changed

    original = summary

    # Fix 3 first: strip OCR noise fragments
    noise_hit = False
    for pat in NOISE_FRAGMENT_RES:
        if pat.search(summary):
            summary = pat.sub('', summary)
            noise_hit = True
    if noise_hit:
        # Clean up leftover punctuation
        summary = re.sub(r'\s{2,}', ' ', summary).strip()
        summary = re.sub(r'^[)\s、，,.]+', '', summary)
        changed.append('NOISE_IN_SUMMARY')
        stats['NOISE_IN_SUMMARY'] += 1

    # Fix 2: strip bracket vendor prefix
    if BRACKET_VENDOR_PREFIX_RE.match(summary):
        summary = BRACKET_VENDOR_PREFIX_RE.sub('', summary)
        if 'BRACKET_VENDOR' not in changed:
            changed.append('BRACKET_VENDOR_PREFIX')
            stats['BRACKET_VENDOR_PREFIX'] += 1

    # Fix 2: replace "与VENDOR签订" with "与{company}签订"
    if VENDOR_IN_COUNTERPARTY_RE.search(summary):
        replacement_name = company if company and not VENDOR_TOKEN_RE.search(company) else \
                           (extract_company_from_filename(fn) or group or '客户')
        summary = VENDOR_IN_COUNTERPARTY_RE.sub(f'与{replacement_name}签订', summary)
        changed.append('VENDOR_IN_SUMMARY')
        stats['VENDOR_IN_SUMMARY'] += 1

    # Fix 2b: "YYYY年 VENDOR 采购订单" → "YYYY年 {company} 采购订单"
    if VENDOR_AS_SUBJECT_RE.search(summary):
        replacement_name = company if company and not VENDOR_TOKEN_RE.search(company) else \
                           (extract_company_from_filename(fn) or group or '客户')
        summary = VENDOR_AS_SUBJECT_RE.sub(f'\\1 {replacement_name}', summary)
        if 'VENDOR_IN_SUMMARY' not in changed:
            changed.append('VENDOR_IN_SUMMARY')
            stats['VENDOR_IN_SUMMARY'] += 1

    # Fix 1: templated year mismatch
    if year:
        def _repl(m):
            if int(m.group(2)) != year:
                return f'{m.group(1)}{year}{m.group(3)}'
            return m.group(0)
        summary, n = TEMPLATED_YEAR_RE.subn(_repl, summary)
        if n:
            changed.append('SUMMARY_YEAR_MISMATCH')
            stats['SUMMARY_YEAR_MISMATCH'] += 1

    # Stub check: if summary became empty or junk after noise strip, rebuild
    if not summary or len(summary) < 8:
        if company and year:
            doc_type = rec.get('doc_type', '')
            if doc_type == 'SRF':
                summary = f'{company} 的{year}年服务需求表（系统维护）'
            else:
                summary = f'与{company}签订的{year}年度服务合同'
            changed.append('SUMMARY_REBUILT')
            stats['SUMMARY_REBUILT'] += 1

    if summary != original:
        rec['summary'] = summary

    return changed


def main():
    shutil.copy(AUDIT, BACKUP)
    print(f'Backup: {BACKUP}')

    stats = Counter()
    total = 0
    touched = 0
    out_lines = []
    affected_groups = set()

    with open(AUDIT, encoding='utf-8') as f:
        for line in f:
            total += 1
            rec = json.loads(line)
            changes = fix_record(rec, stats)
            if changes:
                touched += 1
                affected_groups.add(rec.get('detected_group') or '')
            out_lines.append(json.dumps(rec, ensure_ascii=False))

    with open(AUDIT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out_lines) + '\n')

    # Sync to audit_fixed.jsonl per project rule
    shutil.copy(AUDIT, 'output/audit_fixed.jsonl')

    print(f'\n=== Cleanup Report ===')
    print(f'Total records: {total}')
    print(f'Records touched: {touched}')
    print(f'Affected groups: {len(affected_groups)}')
    print(f'\nFix counts:')
    for k, v in stats.most_common():
        print(f'  {k:30s} {v:5d}')
    print(f'\nAffected groups (will regenerate Excel for all):')
    print('  ' + ', '.join(sorted(g for g in affected_groups if g)))

    # Write affected groups file for next step
    with open('output/_affected_groups.txt', 'w', encoding='utf-8') as f:
        for g in sorted(affected_groups):
            if g: f.write(g + '\n')


if __name__ == '__main__':
    main()

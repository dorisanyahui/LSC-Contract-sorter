"""One-shot cross-validation: filename vs audit.jsonl.

Outputs cross_validation_conflicts.jsonl sorted by group size desc.
Each conflict record contains what filename says vs what audit says,
so the reviewer (Claude Vision) can prioritize which PDFs to open.
"""
import json, re, sys, io
from collections import Counter, defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

AUDIT = 'output/audit.jsonl'
OUT_CONFLICTS = 'output/cross_validation_conflicts.jsonl'
OUT_PROGRESS  = 'output/cross_validation_progress.json'

# ─── Filename parsing ─────────────────────────────────────
# Company name patterns from filename
CTYPE_PREFIXES = (
    '维护合同', '维护服务合同', '服务合同', '合作协议', '服务协议',
    '采购合同', '购买合同', '项目合同', '升级合同', '软件升级',
    '泛纬软件维护服务合同', '泛纬软件升级合同', '泛纬软件服务合同',
    '泛纬软件维护', '泛纬软件购买合同', '范纬软件维护服务合同',
    '范纬软件服务合同', 'SRF', '服务需求表', '报价单', '报价书',
    '保密合同', '保密协议',
)
# Compile one regex alternation ordered by length desc (longest match first)
_PREFIX_ALT = '|'.join(sorted(map(re.escape, CTYPE_PREFIXES), key=len, reverse=True))
PREFIX_STRIP_RE = re.compile(rf'^(?:{_PREFIX_ALT})(?:[_\-\s&]+(?:{_PREFIX_ALT}))*[_\-\s]*')

# Company name ends with these suffixes
# CJK-first: prefer a Chinese company (allows ASCII space inside parens like "( 上海）")
CJK_COMPANY_RE = re.compile(
    r'([\u4e00-\u9fa5][\u4e00-\u9fa5（）()\.．\s]{2,48}?(?:有限公司|股份有限公司|股份公司))'
)
COMPANY_SUFFIX_RE = re.compile(
    r'([^\s_\-&]+?(?:有限公司|股份公司|股份有限公司|公司|Co\.?,?\s*Ltd\.?|Corp\.?|Corporation|Inc\.?|GmbH|Ltd\.?))',
    re.IGNORECASE
)
# Generic: anything between prefix and date/year/end
DATE_TAIL_RE = re.compile(r'(?:\d{4}[.\-_]?\d{1,2}[.\-_]?\d{1,2}.*|维护期.*|有效期.*|\d{4}[年.\-_].*|_cn|_en|\.pdf)$', re.IGNORECASE)

# Year patterns
YEAR_RE = re.compile(r'(20\d{2})')

# Version in filename
VERSION_FN_RES = [
    re.compile(r'V(\d+\.\d+)', re.IGNORECASE),
    re.compile(r'FW(\d+\.?\d*)', re.IGNORECASE),
    re.compile(r'升级[_\s]*(\d+\.?\d*)'),
    re.compile(r'(\d+\.\d+)[_\s]*升级'),
]

# Vendor (乙方) blocklist — if filename-extracted name matches, we must not use it
VENDOR_BLOCKLIST_RE = re.compile(
    r'莱升|跃升|莱禾|莱茵|来升|泛纬|LSC|LICENSE\s*(?:Information|Software|Sofi?ware)',
    re.IGNORECASE
)


def strip_tail(name: str) -> str:
    """Remove trailing date/period tokens."""
    for _ in range(3):
        new = DATE_TAIL_RE.sub('', name).strip(' _-&.')
        if new == name: break
        name = new
    return name


def extract_company_from_filename(fn: str) -> str | None:
    """Try to extract the counterparty company name from filename."""
    stem = fn.rsplit('.', 1)[0]

    # Strategy 0: prefer CJK company (handles spaces inside parens like "( 上海）")
    body = PREFIX_STRIP_RE.sub('', stem).strip(' _-&')
    for text in (body, stem):
        for m in CJK_COMPANY_RE.finditer(text):
            name = m.group(1).strip(' _-&.')
            if len(name) >= 5 and not VENDOR_BLOCKLIST_RE.search(name):
                return name

    # Strategy 1: strip known prefix, then find 有限公司/Co.Ltd
    m = COMPANY_SUFFIX_RE.search(body)
    if m:
        name = m.group(1).strip()
        # Drop if it's a vendor
        if VENDOR_BLOCKLIST_RE.search(name):
            return None
        # Drop obvious fragments (pure ASCII suffix-only)
        if re.match(r'^[\)\s_\-&,.]*Co\.?,?\s*Ltd\.?$', name, re.IGNORECASE):
            return None
        if len(name) >= 4:
            return name

    # Strategy 2: find first 有限公司 anywhere in full stem
    m = COMPANY_SUFFIX_RE.search(stem)
    if m:
        name = m.group(1).strip()
        if VENDOR_BLOCKLIST_RE.search(name):
            return None
        if re.match(r'^[\)\s_\-&,.]*Co\.?,?\s*Ltd\.?$', name, re.IGNORECASE):
            return None
        if len(name) >= 4:
            return name

    return None


def extract_year_from_filename(fn: str) -> int | None:
    years = YEAR_RE.findall(fn)
    if not years: return None
    # Prefer the first reasonable one (2000-2030)
    for y in years:
        yi = int(y)
        if 2000 <= yi <= 2030:
            return yi
    return None


def extract_version_from_filename(fn: str) -> str | None:
    for pat in VERSION_FN_RES:
        m = pat.search(fn)
        if m:
            v = m.group(1)
            if '.' not in v and len(v) >= 2:
                v = f'{v[0]}.{v[1]}'
            return f'V{v}'
    return None


# ─── Name similarity (for soft match) ─────────────────────
def char_similarity(a: str, b: str) -> float:
    if not a or not b: return 0.0
    a, b = a.strip(), b.strip()
    if a == b: return 1.0
    # Normalize brackets
    a = a.replace('（', '(').replace('）', ')')
    b = b.replace('（', '(').replace('）', ')')
    if a == b: return 1.0
    # Char-set Jaccard + longest common substring hint
    sa, sb = set(a), set(b)
    if not sa or not sb: return 0.0
    jaccard = len(sa & sb) / len(sa | sb)
    return jaccard


# ─── Main ─────────────────────────────────────────────────
def main():
    records = []
    with open(AUDIT, encoding='utf-8') as f:
        for line in f:
            r = json.loads(line)
            records.append(r)

    # Count records per group
    group_counts = Counter(r.get('detected_group', '') for r in records)

    conflicts = []
    stats = Counter()

    for r in records:
        fn = r.get('file_name', '') or ''
        group = r.get('detected_group', '') or ''
        audit_co = (r.get('detected_company', '') or '').strip()
        audit_year = r.get('report_year')
        audit_ver = (r.get('software_version', '') or '').strip()

        issues = []
        fn_co = extract_company_from_filename(fn)
        fn_year = extract_year_from_filename(fn)
        fn_ver = extract_version_from_filename(fn)

        # Company conflict
        if fn_co and audit_co:
            sim = char_similarity(fn_co, audit_co)
            if sim < 0.5:
                issues.append({
                    'type': 'COMPANY_MISMATCH',
                    'filename_says': fn_co,
                    'audit_says': audit_co,
                    'similarity': round(sim, 2),
                })
                stats['COMPANY_MISMATCH'] += 1
        elif not audit_co and fn_co:
            issues.append({
                'type': 'COMPANY_MISSING_IN_AUDIT',
                'filename_says': fn_co,
                'audit_says': '',
            })
            stats['COMPANY_MISSING_IN_AUDIT'] += 1
        elif audit_co and not fn_co and VENDOR_BLOCKLIST_RE.search(audit_co):
            # audit has vendor name, filename has nothing identifiable
            issues.append({
                'type': 'VENDOR_IN_AUDIT',
                'filename_says': None,
                'audit_says': audit_co,
            })
            stats['VENDOR_IN_AUDIT'] += 1

        # Version conflict
        if fn_ver and audit_ver and fn_ver != audit_ver:
            issues.append({
                'type': 'VERSION_MISMATCH',
                'filename_says': fn_ver,
                'audit_says': audit_ver,
            })
            stats['VERSION_MISMATCH'] += 1

        # Amount missing (still LOW priority but flagged)
        amt = (r.get('annual_maintenance_fee') or r.get('tax_included_amount')
               or r.get('tax_excluded_amount') or r.get('contract_total_amount'))
        if not amt:
            issues.append({'type': 'AMOUNT_EMPTY'})
            stats['AMOUNT_EMPTY'] += 1

        if issues:
            conflicts.append({
                'file_md5': r.get('file_md5'),
                'group': group,
                'group_size': group_counts[group],
                'file_name': fn,
                'file_path': r.get('file_path'),
                'report_year': audit_year,
                'current': {
                    'detected_company': audit_co,
                    'software_version': audit_ver,
                    'annual_maintenance_fee': r.get('annual_maintenance_fee'),
                    'tax_included_amount': r.get('tax_included_amount'),
                    'tax_excluded_amount': r.get('tax_excluded_amount'),
                    'contract_total_amount': r.get('contract_total_amount'),
                    'summary': r.get('summary'),
                },
                'issues': issues,
            })

    # Sort: group size desc, then group name, then file_name
    conflicts.sort(key=lambda c: (-c['group_size'], c['group'], c['file_name']))

    # Write conflict list
    with open(OUT_CONFLICTS, 'w', encoding='utf-8') as f:
        for c in conflicts:
            f.write(json.dumps(c, ensure_ascii=False) + '\n')

    # Build ordered group list
    groups_in_order = []
    seen = set()
    for c in conflicts:
        if c['group'] not in seen:
            groups_in_order.append(c['group'])
            seen.add(c['group'])

    # Initial progress file (only if doesn't already exist)
    import os
    if not os.path.exists(OUT_PROGRESS):
        progress = {
            'total_conflicts': len(conflicts),
            'groups_order': groups_in_order,
            'current_group_idx': 0,
            'current_record_idx_in_group': 0,
            'stats': {
                'reviewed': 0,
                'fixed': 0,
                'confirmed_ok': 0,
                'skipped': 0,
                'pending': len(conflicts),
            },
            'last_updated': None,
        }
        with open(OUT_PROGRESS, 'w', encoding='utf-8') as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)

    # Report
    print(f'=== Cross-validation Summary ===')
    print(f'Total records: {len(records)}')
    print(f'Total conflicts: {len(conflicts)}')
    print(f'\nConflict types:')
    for k, v in stats.most_common():
        print(f'  {k:30s} {v:5d}')
    print(f'\nTop 15 conflict groups (by group size):')
    group_conflict_counts = Counter(c['group'] for c in conflicts)
    for g in groups_in_order[:15]:
        total = group_counts[g]
        confs = group_conflict_counts[g]
        print(f'  {g:20s} {confs:4d} conflicts / {total:4d} total records')
    print(f'\nWritten:')
    print(f'  {OUT_CONFLICTS}')
    print(f'  {OUT_PROGRESS}')


if __name__ == '__main__':
    main()

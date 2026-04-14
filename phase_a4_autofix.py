"""Phase A4: trust filename when it contains a valid CJK company and audit differs.

Rationale: verified via PDF rendering that for the remaining 66 COMPANY_MISMATCH
cases, the human-curated filename is consistently correct and audit is OCR noise
from the PDF text layer (often picking up addresses or unrelated text).

Rule M: filename_says starts with CJK, is a full company name (≥6 chars, has 有限公司
        suffix, not a vendor variant), and audit_says is materially different (not a
        substring, and vice versa). Trust filename.

Safety filters:
  - Skip if filename_says doesn't start with CJK character
  - Skip if filename_says contains '新增公司' or similar placeholder
  - Skip if filename_says is a substring of audit_says (audit has fuller info)
  - Skip if audit_says is a substring of filename_says (filename has fuller info, but then audit is fine)
  - Skip known vendor patterns
"""
import json, re, shutil, sys, io
from collections import Counter
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

AUDIT = 'output/audit.jsonl'
CONFLICTS = 'output/cross_validation_conflicts.jsonl'
BACKUP = f'output/audit.backup.{datetime.now():%Y%m%d_%H%M%S}.jsonl'

CJK_RE = re.compile(r'[\u4e00-\u9fa5]')
COMPANY_SUFFIX_RE = re.compile(r'(有限公司|股份有限公司|股份公司)$')
VENDOR_RE = re.compile(
    r'莱升|跃升|莱禾|莱茵|来升|来开|昇升|业升|业开|药升|荣升|泛维|泛纬|泛昇|泛升|'
    r'顺升|东升|东禾|菜升|欣升|顾升|智开|三维信息|美术信息|业达信息|泛开|'
    r'LSC|LICENSE', re.IGNORECASE
)
PLACEHOLDER_RE = re.compile(r'新增公司|新增\d家|xx|XX|某某')


def is_valid_cjk_company(name: str) -> bool:
    if not name or len(name) < 6:
        return False
    if not CJK_RE.match(name):  # must start with CJK
        return False
    if not COMPANY_SUFFIX_RE.search(name):
        return False
    if VENDOR_RE.search(name):
        return False
    if PLACEHOLDER_RE.search(name):
        return False
    return True


def main():
    # Load conflicts → build md5 → filename_says lookup
    fn_lookup = {}
    with open(CONFLICTS, encoding='utf-8') as f:
        for line in f:
            c = json.loads(line)
            md5 = c.get('file_md5')
            for iss in c.get('issues', []):
                if iss.get('type') == 'COMPANY_MISMATCH':
                    fn_lookup[md5] = iss.get('filename_says')
                    break

    print(f'Loaded {len(fn_lookup)} COMPANY_MISMATCH records')

    shutil.copy(AUDIT, BACKUP)
    print(f'Backup: {BACKUP}')

    stats = Counter()
    examples = []
    changes_by_group = Counter()

    lines = []
    with open(AUDIT, encoding='utf-8') as f:
        for line in f:
            r = json.loads(line)
            md5 = r.get('file_md5')
            co = (r.get('detected_company') or '').strip()
            group = r.get('detected_group') or ''
            fn = r.get('file_name') or ''

            new_co = None
            fn_says = fn_lookup.get(md5)
            if fn_says and co and fn_says != co:
                if is_valid_cjk_company(fn_says):
                    # Skip if filename is subset of audit (audit has fuller info)
                    if fn_says in co:
                        stats['SKIP_FN_SUBSET'] += 1
                    elif co in fn_says:
                        # audit is subset of filename → filename is richer, trust it
                        new_co = fn_says
                        stats['M_AUDIT_SUBSET'] += 1
                    else:
                        new_co = fn_says
                        stats['M_DISTINCT'] += 1
                else:
                    stats['SKIP_FN_INVALID'] += 1

            if new_co:
                old_co = co
                r['detected_company'] = new_co
                s = r.get('summary') or ''
                if old_co and old_co in s:
                    s = s.replace(old_co, new_co)
                    r['summary'] = s
                changes_by_group[group] += 1
                if len(examples) < 20:
                    examples.append((group, old_co, new_co, fn[:70]))
            lines.append(json.dumps(r, ensure_ascii=False))

    with open(AUDIT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    shutil.copy(AUDIT, 'output/audit_fixed.jsonl')

    print(f'\n=== Phase A4 Report ===')
    total_fix = stats['M_DISTINCT'] + stats['M_AUDIT_SUBSET']
    print(f'Total fixes: {total_fix}')
    print(f'\nBy rule:')
    for k, v in stats.most_common():
        print(f'  {k:20s} {v}')
    print(f'\nTop groups:')
    for g, c in changes_by_group.most_common(15):
        print(f'  {g:18s} {c}')
    print(f'\nSamples:')
    for g, old, new, fn in examples:
        print(f'  [{g}]')
        print(f'    old: {old}')
        print(f'    new: {new}')
        print(f'    fn:  {fn}')


if __name__ == '__main__':
    main()

"""Phase A auto-fix: replace vendor-shaped OCR variants with filename company.

Two targets:
  A1. detected_company matches extended vendor shape → use filename company
  A2. detected_company is mostly English + filename has valid Chinese → use filename Chinese

Safety: only rewrite when filename extraction yields a distinct valid Chinese company name.
"""
import json, re, shutil, sys, io
from collections import Counter
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

AUDIT = 'output/audit.jsonl'
BACKUP = f'output/audit.backup.{datetime.now():%Y%m%d_%H%M%S}.jsonl'

# Extended vendor shape — catches the 74 variants found
VENDOR_SHAPE_RE = re.compile(
    r'^(?:上海|Shanghai)[^，,。]{1,6}(升|维|纬|禾|茵|开|达)[^，,。]{0,10}(信息|软件|科技|技术|咨询|Information|Software|Sofiware)',
    re.IGNORECASE
)
# Known literal vendor tokens
VENDOR_LITERAL_RE = re.compile(
    r'莱升|跃升|莱斯(?!特)|莱茵|莱禾|来升|来开|昇升|业升|业开|药升|荣升|泛维|泛纬|'
    r'LSC|LICENSE\s*(?:Information|Software|Sofi?ware|Hardw[ua]re)',
    re.IGNORECASE
)

# ─── Filename company extraction (same as cross_validate.py) ──
CTYPE_PREFIXES = (
    '维护合同', '维护服务合同', '服务合同', '合作协议', '服务协议',
    '采购合同', '购买合同', '项目合同', '升级合同', '软件升级',
    '泛纬软件维护服务合同', '泛纬软件升级合同', '泛纬软件服务合同',
    '泛纬软件维护', '泛纬软件购买合同', '范纬软件维护服务合同',
    '范纬软件服务合同', 'SRF', '服务需求表', '报价单', '报价书',
    '保密合同', '保密协议', '合同修订协议', '补充协议',
)
_PREFIX_ALT = '|'.join(sorted(map(re.escape, CTYPE_PREFIXES), key=len, reverse=True))
PREFIX_STRIP_RE = re.compile(rf'^(?:{_PREFIX_ALT})(?:[_\-\s&]+(?:{_PREFIX_ALT}))*[_\-\s]*')
COMPANY_SUFFIX_RE = re.compile(
    r'([^\s_&]+?(?:有限公司|股份有限公司|股份公司))',
)


def extract_company_from_filename(fn: str) -> str | None:
    stem = fn.rsplit('.', 1)[0]
    body = PREFIX_STRIP_RE.sub('', stem).strip(' _-&')
    m = COMPANY_SUFFIX_RE.search(body)
    if not m:
        m = COMPANY_SUFFIX_RE.search(stem)
    if not m:
        return None
    name = m.group(1).strip()
    # Clean leading noise like "en_", "-", "_"
    name = re.sub(r'^(?:en_|cn_|_|-|\s)+', '', name)
    if len(name) < 4:
        return None
    if VENDOR_LITERAL_RE.search(name) or VENDOR_SHAPE_RE.search(name):
        return None
    return name


def mostly_english(s: str) -> bool:
    if not s: return False
    ascii_alnum = sum(1 for c in s if ord(c) < 128 and c.isalnum())
    return ascii_alnum / max(len(s.strip()), 1) > 0.65


def is_vendor_shaped(s: str) -> bool:
    return bool(VENDOR_SHAPE_RE.search(s) or VENDOR_LITERAL_RE.search(s))


def main():
    shutil.copy(AUDIT, BACKUP)
    print(f'Backup: {BACKUP}')

    stats = Counter()
    changes_by_group = Counter()
    examples = []

    lines = []
    with open(AUDIT, encoding='utf-8') as f:
        for line in f:
            r = json.loads(line)
            co = (r.get('detected_company') or '').strip()
            fn = r.get('file_name') or ''
            group = r.get('detected_group') or ''

            new_co = None
            reason = None

            # A1: vendor-shaped audit → use filename
            if co and is_vendor_shaped(co):
                fn_co = extract_company_from_filename(fn)
                if fn_co and fn_co != co:
                    new_co = fn_co
                    reason = 'VENDOR_SHAPE'

            # A2: mostly-English audit → use filename Chinese if available
            elif co and mostly_english(co):
                fn_co = extract_company_from_filename(fn)
                if fn_co and not mostly_english(fn_co):
                    # Extra safety: both should share a token or belong to same group
                    new_co = fn_co
                    reason = 'EN_TO_CN'

            # A3: empty audit + filename valid → fill in
            elif not co:
                fn_co = extract_company_from_filename(fn)
                if fn_co:
                    new_co = fn_co
                    reason = 'FILL_EMPTY'

            if new_co:
                old_co = co
                r['detected_company'] = new_co
                # Fix summary if it contained the old company name
                s = r.get('summary') or ''
                if old_co and old_co in s:
                    s = s.replace(old_co, new_co)
                    r['summary'] = s
                elif s:
                    # Some summaries have "与{company}签订" where company is empty or vendor shape
                    # Rebuild minimally
                    if reason == 'VENDOR_SHAPE' or reason == 'FILL_EMPTY':
                        import re as _re
                        # Replace "与XXX签订" where XXX is vendor-shaped
                        s = _re.sub(r'与[^签]{2,40}签订', f'与{new_co}签订', s, count=1)
                        r['summary'] = s
                stats[reason] += 1
                changes_by_group[group] += 1
                if len(examples) < 20:
                    examples.append((reason, group, old_co, new_co, fn[:80]))
            lines.append(json.dumps(r, ensure_ascii=False))

    with open(AUDIT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    shutil.copy(AUDIT, 'output/audit_fixed.jsonl')

    print(f'\n=== Phase A Report ===')
    print(f'Total fixes: {sum(stats.values())}')
    print(f'\nBy reason:')
    for k, v in stats.most_common():
        print(f'  {k:15s} {v}')
    print(f'\nTop 15 affected groups:')
    for g, c in changes_by_group.most_common(15):
        print(f'  {g:20s} {c}')
    print(f'\nSample fixes:')
    for reason, g, old, new, fn in examples:
        print(f'  [{reason}][{g}]')
        print(f'    old: {old}')
        print(f'    new: {new}')
        print(f'    fn:  {fn}')


if __name__ == '__main__':
    main()

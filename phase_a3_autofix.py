"""Phase A3: final auto-fix pass.

Rule K: filename extracts a valid Chinese company whose name contains the
        group's core keyword, while audit has a completely different company
        → trust filename (group folder placement is already validated).
        This catches OCR cross-references where audit captured some unrelated
        company from the PDF text.

Also fixes extractor bug where filename mixed EN+CN returned only English fragment.
"""
import json, re, shutil, sys, io
from collections import Counter
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

AUDIT = 'output/audit.jsonl'
BACKUP = f'output/audit.backup.{datetime.now():%Y%m%d_%H%M%S}.jsonl'

CTYPE_PREFIXES = (
    '维护合同', '维护服务合同', '服务合同', '合作协议', '服务协议', '外包服务合同',
    '采购合同', '购买合同', '项目合同', '升级合同', '软件升级',
    '泛纬软件维护服务合同', '泛纬软件升级合同', '泛纬软件服务合同',
    '泛纬软件维护', '泛纬软件购买合同', '范纬软件维护服务合同',
    '范纬软件服务合同', 'SRF', '服务需求表', '服务申请表', '报价单', '报价书',
    '保密合同', '保密协议', '合同修订协议', '补充协议', '需求确认书',
    '无客户章', '授权和保证书', '项目建议书', '备案合同', '实施合同', '财政信用等级评定申请服务表',
    '测试报告', '项目交接报告', '【英】服务申请表',
)
_PREFIX_ALT = '|'.join(sorted(map(re.escape, CTYPE_PREFIXES), key=len, reverse=True))
PREFIX_STRIP_RE = re.compile(rf'^(?:{_PREFIX_ALT})(?:[_\-\s&]+(?:{_PREFIX_ALT}))*[_\-\s]*')

# CJK-only company: must have Chinese characters before the suffix
CJK_COMPANY_RE = re.compile(r'([\u4e00-\u9fa5][\u4e00-\u9fa5（）()\.．\s]{2,48}?(?:有限公司|股份有限公司|股份公司))')


def extract_cjk_company(fn: str) -> str | None:
    stem = fn.rsplit('.', 1)[0]
    body = PREFIX_STRIP_RE.sub('', stem).strip(' _-&')
    for text in (body, stem):
        matches = CJK_COMPANY_RE.findall(text)
        for name in matches:
            name = name.strip(' _-&.')
            if len(name) >= 5 and not re.search(r'莱升|跃升|业升|药升|荣升|泛维|泛纬|泛昇|莱禾|莱茵|来升|昇升|业开|来邦|药业|某某|某科技|蜀玛|泛微|薄膜科技|LSC', name):
                return name
    return None


def group_tokens(group: str) -> list[str]:
    """Return distinctive tokens from group name for filename matching."""
    if not group: return []
    # Strip "集团" suffix, handle 2-4 char cores
    core = group.replace('集团', '').strip()
    tokens = [core]
    # For short cores, also add variants
    return [t for t in tokens if len(t) >= 2]


def main():
    shutil.copy(AUDIT, BACKUP)
    print(f'Backup: {BACKUP}')

    stats = Counter()
    examples = []
    changes_by_group = Counter()

    lines = []
    with open(AUDIT, encoding='utf-8') as f:
        for line in f:
            r = json.loads(line)
            co = (r.get('detected_company') or '').strip()
            fn = r.get('file_name') or ''
            group = r.get('detected_group') or ''

            new_co = None
            fn_co = extract_cjk_company(fn)
            tokens = group_tokens(group)

            # Rule K: filename has CJK company containing group token, and audit has different company
            if fn_co and tokens and co and fn_co != co:
                if any(t in fn_co for t in tokens) and not any(t in co for t in tokens):
                    new_co = fn_co
                    stats['K_GROUP_TOKEN_MATCH'] += 1

            if new_co:
                old_co = co
                r['detected_company'] = new_co
                s = r.get('summary') or ''
                if old_co and old_co in s:
                    s = s.replace(old_co, new_co)
                    r['summary'] = s
                changes_by_group[group] += 1
                if len(examples) < 15:
                    examples.append((group, old_co, new_co, fn[:80]))
            lines.append(json.dumps(r, ensure_ascii=False))

    with open(AUDIT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    shutil.copy(AUDIT, 'output/audit_fixed.jsonl')

    print(f'\n=== Phase A3 Report ===')
    print(f'Total fixes: {sum(stats.values())}')
    print(f'\nTop groups:')
    for g, c in changes_by_group.most_common(15):
        print(f'  {g:20s} {c}')
    print(f'\nSample fixes:')
    for g, old, new, fn in examples:
        print(f'  [{g}]')
        print(f'    old: {old}')
        print(f'    new: {new}')
        print(f'    fn:  {fn}')


if __name__ == '__main__':
    main()

"""Phase A2: second pass of auto-fixes targeting more vendor shapes + OCR noise.

Fixes:
  D. Extended vendor shapes (上海某某/美术/泛昇/etc)
  E. OCR noise/template fragments as company name
  H. Extractor bug — prefer trailing Chinese company name over leading English

Also adds a "protected" fallback: if filename extraction returns an English name
but a better Chinese name exists, skip — audit's Chinese value may be correct.
"""
import json, re, shutil, sys, io
from collections import Counter
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

AUDIT = 'output/audit.jsonl'
BACKUP = f'output/audit.backup.{datetime.now():%Y%m%d_%H%M%S}.jsonl'

# Extended vendor shape — catches more variants
VENDOR_SHAPE_RE = re.compile(
    r'^(?:上海|Shanghai)[^，,。]{1,8}(信息科技|软件咨询|信息技术|软件技术|企业管理咨询|商务咨询|信息设备|软件开发)\s*(?:有限公司|股份公司)?$|'
    r'上海(某某|美术|某某某|xx|XX)',
    re.IGNORECASE
)
VENDOR_LITERAL_RE = re.compile(
    r'莱升|跃升|莱斯(?!特)|莱茵|莱禾|来升|来开|昇升|业升|业开|药升|荣升|泛维|泛纬|泛昇|泛升|顺升|东升|东禾|菜升|欣升|顾升|智开|三维信息|美术信息|业达信息|泛开|'
    r'LSC|LICENSE\s*(?:Information|Software|Sofi?ware|Hardw[ua]re)',
    re.IGNORECASE
)
# Template/noise patterns — obviously not a company name
NOISE_COMPANY_RE = re.compile(
    r'^(作为|受托方|被告|原告|甲方|乙方|件|与|是|在|关于|本|该)|'
    r'^\d{1,2}月|'
    r'^[^有]{0,30}(某某|XX|xx)|'
    r'^[^u4e00-u9fa5]{0,5}(有限公司|咨询有限公司)$|'  # just "有限公司" with noise prefix
    r'合同约定|约束力|保密条款|业务范围'
)

# ─── Chinese-first filename company extraction ─────────
CTYPE_PREFIXES = (
    '维护合同', '维护服务合同', '服务合同', '合作协议', '服务协议', '外包服务合同',
    '采购合同', '购买合同', '项目合同', '升级合同', '软件升级',
    '泛纬软件维护服务合同', '泛纬软件升级合同', '泛纬软件服务合同',
    '泛纬软件维护', '泛纬软件购买合同', '范纬软件维护服务合同',
    '范纬软件服务合同', 'SRF', '服务需求表', '服务申请表', '报价单', '报价书',
    '保密合同', '保密协议', '合同修订协议', '补充协议', '需求确认书',
    '无客户章', '授权和保证书', '项目建议书',
)
_PREFIX_ALT = '|'.join(sorted(map(re.escape, CTYPE_PREFIXES), key=len, reverse=True))
PREFIX_STRIP_RE = re.compile(rf'^(?:{_PREFIX_ALT})(?:[_\-\s&]+(?:{_PREFIX_ALT}))*[_\-\s]*')

# Chinese company name ending with 有限公司/股份公司 — must contain CJK
CJK_COMPANY_RE = re.compile(r'([\u4e00-\u9fa5（）()\.．\s]{3,50}?(?:有限公司|股份有限公司|股份公司))')
# Fallback: any company suffix
ANY_COMPANY_RE = re.compile(r'([^\s_&]{3,60}?(?:有限公司|股份有限公司|股份公司|Co\.?,?\s*Ltd\.?))', re.IGNORECASE)


def extract_company_from_filename(fn: str) -> str | None:
    """Chinese-first extraction with vendor filtering."""
    stem = fn.rsplit('.', 1)[0]
    body = PREFIX_STRIP_RE.sub('', stem).strip(' _-&')

    # Try CJK-only first (prefer Chinese name even if English leads)
    for candidate_text in (body, stem):
        for m in CJK_COMPANY_RE.finditer(candidate_text):
            name = m.group(1).strip(' _-&.')
            name = re.sub(r'^[（(]?\d{4}[）)]?', '', name).strip()
            if len(name) >= 4 and not VENDOR_LITERAL_RE.search(name) and not VENDOR_SHAPE_RE.search(name):
                return name

    # Fallback: any company suffix
    for candidate_text in (body, stem):
        m = ANY_COMPANY_RE.search(candidate_text)
        if m:
            name = m.group(1).strip(' _-&.')
            if len(name) >= 4 and not VENDOR_LITERAL_RE.search(name) and not VENDOR_SHAPE_RE.search(name):
                return name
    return None


def is_vendor_or_noise(s: str) -> bool:
    if not s: return False
    if VENDOR_LITERAL_RE.search(s): return True
    if VENDOR_SHAPE_RE.search(s): return True
    if NOISE_COMPANY_RE.search(s): return True
    return False


def mostly_english(s: str) -> bool:
    if not s: return False
    ascii_alnum = sum(1 for c in s if ord(c) < 128 and c.isalnum())
    return ascii_alnum / max(len(s.strip()), 1) > 0.65


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
            reason = None

            if co and is_vendor_or_noise(co):
                fn_co = extract_company_from_filename(fn)
                if fn_co and fn_co != co:
                    new_co = fn_co
                    reason = 'VENDOR_OR_NOISE'
            elif co and mostly_english(co):
                fn_co = extract_company_from_filename(fn)
                if fn_co and not mostly_english(fn_co):
                    new_co = fn_co
                    reason = 'EN_TO_CN'

            if new_co:
                old_co = co
                r['detected_company'] = new_co
                s = r.get('summary') or ''
                if old_co and old_co in s:
                    s = s.replace(old_co, new_co)
                    r['summary'] = s
                stats[reason] += 1
                changes_by_group[group] += 1
                if len(examples) < 15:
                    examples.append((reason, group, old_co, new_co, fn[:80]))
            lines.append(json.dumps(r, ensure_ascii=False))

    with open(AUDIT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    shutil.copy(AUDIT, 'output/audit_fixed.jsonl')

    print(f'\n=== Phase A2 Report ===')
    print(f'Total fixes: {sum(stats.values())}')
    print(f'\nBy reason:')
    for k, v in stats.most_common():
        print(f'  {k:20s} {v}')
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

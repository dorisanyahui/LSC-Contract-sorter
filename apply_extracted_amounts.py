"""
应用 OCR 提取的金额到 audit.jsonl
- 合并 pass1 + pass2 的结果
- 剔除明显误提取（时薪/日薪/保险金额）
- 根据 tax_type 决定写入 tax_included_amount 或 tax_excluded_amount
"""
import json, sys, io, shutil
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 人工剔除清单（误提取）
REJECT = {
    # 合同方, 金额, 文件名关键词
    ('其他', 20000, '北京维汉文化传播'),           # 保险金额
    ('泰科集团', 2500, '泰科电子东莞'),             # 时薪 312元/小时
    ('泰科集团', 312, '泰科电子科技（昆山）'),       # 时薪
    ('阿特拉斯', 2500, '2007年11月27日'),          # 日薪 2500/天 (2 files)
}


def is_rejected(group, amount, file_name) -> bool:
    for g, a, kw in REJECT:
        if g == group and a == amount and kw in file_name:
            return True
    return False


def main():
    # Load extraction results
    pass1_all = []
    with open('output/amount_extraction_results.jsonl', encoding='utf-8') as f:
        for line in f:
            pass1_all.append(json.loads(line))

    pass2_all = []
    with open('output/amount_extraction_pass2.jsonl', encoding='utf-8') as f:
        for line in f:
            pass2_all.append(json.loads(line))

    # Build lookup keyed by file_name
    # Pass2 overrides pass1 for the same file
    updates = {}  # file_name -> (amount, tax_type, currency, source)
    stats = {'pass1_high': 0, 'pass2_ev_fix': 0, 'pass2_deep': 0, 'rejected': 0, 'skipped_no_amt': 0}

    # Pass 1: take only non-mismatched (high confidence, evidence matched)
    pass1_by_fn = {}
    for r in pass1_all:
        fn = r['file_name']
        if r.get('_validation') == 'evidence_mismatch':
            continue  # Will be handled by pass2
        if r.get('amount') is None:
            continue  # Will be handled by pass2 deep
        pass1_by_fn[fn] = r

    # Pass 2: evidence fixes + deep scan
    pass2_by_fn = {}
    for r in pass2_all:
        fn = r['file_name']
        if r.get('amount') is None:
            continue
        pass2_by_fn[fn] = r

    # Merge: pass2 overrides pass1
    for fn, r in pass1_by_fn.items():
        updates[fn] = r
        stats['pass1_high'] += 1

    for fn, r in pass2_by_fn.items():
        if is_rejected(r['group'], r['amount'], fn):
            stats['rejected'] += 1
            continue
        if fn in updates:
            # override
            if updates[fn].get('amount') != r.get('amount'):
                updates[fn] = r
                fix_type = r.get('_fix', 'unknown')
                if 'evidence' in fix_type:
                    stats['pass2_ev_fix'] += 1
                    stats['pass1_high'] -= 1
                else:
                    stats['pass2_deep'] += 1
                    stats['pass1_high'] -= 1
        else:
            updates[fn] = r
            fix_type = r.get('_fix', 'unknown')
            if 'evidence' in fix_type:
                stats['pass2_ev_fix'] += 1
            else:
                stats['pass2_deep'] += 1

    print(f'应用更新统计: {stats}')
    print(f'总更新数: {len(updates)}')

    # Now apply to audit.jsonl
    records = []
    applied = 0
    with open('output/audit.jsonl', encoding='utf-8') as f:
        for line in f:
            r = json.loads(line)
            fn = r.get('file_name', '')
            if fn in updates:
                u = updates[fn]
                amount = u['amount']
                tax_type = (u.get('tax_type') or '').strip()
                currency = u.get('currency') or 'CNY'

                # Write to appropriate field
                if tax_type == '含税':
                    r['tax_included_amount'] = amount
                elif tax_type == '不含税':
                    r['tax_excluded_amount'] = amount
                else:
                    # Unknown tax - use contract_total
                    r['contract_total_amount'] = amount
                r['currency'] = currency
                applied += 1
            records.append(r)

    with open('output/audit.jsonl', 'w', encoding='utf-8') as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    shutil.copy('output/audit.jsonl', 'output/audit_fixed.jsonl')
    print(f'\n已应用 {applied} 条金额更新到 audit.jsonl')


if __name__ == '__main__':
    main()

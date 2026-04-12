"""Build output/manual_review_queue.xlsx — items that need human/PDF verification."""
import json, sys, io
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

report = json.load(open('output/summary_quality_report.json', encoding='utf-8'))
audit = {}
with open('output/audit.jsonl', encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        audit.setdefault(r.get('detected_group', ''), []).append(r)

# Category → priority
PRIORITY = {
    'VERSION_V8_PRE2023':    'HIGH',   # timeline conflict
    'VERSION_V7_PRE2017':    'HIGH',
    'AMOUNT_SUSPICIOUS_LOW': 'MEDIUM',
    'AMOUNT_EMPTY':          'LOW',    # largest bucket, defer until budget
    'VENDOR_IN_SUMMARY':     'LOW',    # residual false positives / edge
    'COMPANY_IS_GROUP':      'LOW',
    'SUMMARY_YEAR_MISMATCH': 'LOW',
}
CAT_NAME = {
    'VERSION_V8_PRE2023':    '版本V8出现在2023前（可能OCR误读）',
    'VERSION_V7_PRE2017':    '版本V7出现在2017前（可能OCR误读）',
    'AMOUNT_SUSPICIOUS_LOW': '金额异常偏低（¥1000以下）',
    'AMOUNT_EMPTY':          '无金额字段',
    'VENDOR_IN_SUMMARY':     '摘要含乙方名（残留）',
    'COMPANY_IS_GROUP':      '公司名等于集团名（残留）',
    'SUMMARY_YEAR_MISMATCH': '摘要年份与报告年不符（残留）',
}

rows = []
for cat in PRIORITY:
    hits = report['all_issues_by_category'].get(cat, [])
    for h in hits:
        group = h['group']
        row_idx = h['row']
        detail = h['detail']
        rows.append({
            '优先级': PRIORITY[cat],
            '问题类型': CAT_NAME[cat],
            '集团': group,
            'Excel行号': row_idx,
            '问题详情': detail,
            '已核对': '',
            '核对结果': '',
        })

df = pd.DataFrame(rows)
priority_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
df = df.sort_values(by=['优先级', '集团'], key=lambda c: c.map(priority_order) if c.name == '优先级' else c)
df.to_excel('output/manual_review_queue.xlsx', index=False)

print(f'Rows: {len(df)}')
print()
print('By priority:')
print(df.groupby('优先级').size().to_string())
print()
print('By type:')
print(df.groupby('问题类型').size().to_string())
print()
print('Written to output/manual_review_queue.xlsx')

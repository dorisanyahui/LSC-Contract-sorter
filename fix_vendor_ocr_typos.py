"""
修复 OCR 将乙方莱升误读为跃升/莱斯导致的公司名错误
从文件名中提取真正的客户公司名
"""
import json, sys, io, re, shutil

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 手动指定每条的正确公司名（从文件名提取）
FIXES = {
    '购买合同&维护&保密协议-派克汉尼汾动力传动产品（无锡）有限公司-有效期6个月免费-20120507.pdf':
        '派克汉尼汾动力传动产品（无锡）有限公司',
    '备案合同&购买&报价单-圣诺技（中国）电源有限公司-20091228.pdf':
        '圣诺技（中国）电源有限公司',
    '备案合同&维护&服务需求表&购买-汉堡王（上海）餐饮有限公司-20110923.pdf':
        '汉堡王（上海）餐饮有限公司',
    '备案合同&购买合同&维护服务合同&保密协议&报价单-首诺国际贸易（上海）有限公司-20111101.pdf':
        '首诺国际贸易（上海）有限公司',
    '备案合同&保密协议-礼来国际贸易（上海）有限公司-20120620.pdf':
        '礼来国际贸易（上海）有限公司',
    '采购单_马勒投资（中国）有限公司_2015.9.14.pdf':
        '马勒投资（中国）有限公司',
    '项目合同&维护_阿特拉斯科普柯融资租赁有限公司2016.pdf':
        '阿特拉斯科普柯融资租赁有限公司',
    '保密和限制使用协议_凯瑞德制造软件（苏州）有限公司_.pdf':
        '凯瑞德制造软件（苏州）有限公司',
}

records = []
changes = 0
with open('output/audit.jsonl', encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        fn = r.get('file_name', '')
        if fn in FIXES:
            old = r.get('detected_company', '')
            new = FIXES[fn]
            r['detected_company'] = new
            # Also update summary
            summary = r.get('summary', '')
            if old and old in summary:
                r['summary'] = summary.replace(old, new)
            # Clear the group_conflict flag if present
            flags = r.get('flags', [])
            r['flags'] = [f for f in flags if 'group_conflict' not in f]
            changes += 1
            print(f'[{r.get("detected_group")}] {fn[:55]}')
            print(f'  {old} → {new}')
        records.append(r)

with open('output/audit.jsonl', 'w', encoding='utf-8') as f:
    for r in records:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')
shutil.copy('output/audit.jsonl', 'output/audit_fixed.jsonl')
print(f'\n共修复 {changes} 条记录')

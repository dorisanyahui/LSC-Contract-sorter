"""
第二轮提取：
1. 修复 4 个 evidence_mismatch 的低置信度记录（从 evidence 字符串重提数字）
2. 对 81 个无金额记录做二次扫描（页3-6，有些金额在后面）
"""
import os, sys, io, json, re, time
from pathlib import Path

# Load .env
_env = Path(__file__).parent / '.env'
if _env.exists():
    for line in _env.read_text(encoding='utf-8').splitlines():
        if '=' in line and not line.strip().startswith('#'):
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from openai import OpenAI
from extract_missing_amounts import extract_amount_from_pdf, render_page, EXTRACT_PROMPT

RESULTS_PATH = Path('output/amount_extraction_results.jsonl')
PASS2_PATH = Path('output/amount_extraction_pass2.jsonl')


def extract_from_evidence(ev: str) -> int | None:
    """Extract the largest number from evidence string."""
    if not ev:
        return None
    # Find number patterns like 26,500 or 10698.84 or 50000
    nums = re.findall(r'([\d,]+(?:\.\d+)?)', ev)
    candidates = []
    for n in nums:
        try:
            val = float(n.replace(',', ''))
            if 100 <= val <= 100_000_000:
                candidates.append(int(val))
        except:
            pass
    if not candidates:
        return None
    return max(candidates)


def extract_deep(client, pdf_path: Path, pages_to_try: list[int]) -> dict:
    """Try specific pages (for pass-2)."""
    results = []
    for page_no in pages_to_try:
        b64 = render_page(pdf_path, page_no)
        if b64 is None:
            continue
        for attempt in range(3):
            try:
                resp = client.chat.completions.create(
                    model='gpt-4o-mini',
                    messages=[{
                        'role': 'user',
                        'content': [
                            {'type': 'text', 'text': EXTRACT_PROMPT},
                            {'type': 'image_url', 'image_url': {
                                'url': f'data:image/jpeg;base64,{b64}',
                                'detail': 'auto',
                            }},
                        ],
                    }],
                    max_tokens=300,
                    temperature=0,
                    timeout=60,
                    response_format={'type': 'json_object'},
                )
                data = json.loads(resp.choices[0].message.content.strip())
                data['page'] = page_no + 1
                if 'main_amount' in data and data.get('main_amount') is not None:
                    data['amount'] = data['main_amount']
                amt = data.get('amount')
                ev = str(data.get('evidence', ''))
                if amt is not None:
                    digits = str(int(amt))
                    if digits in ev.replace(',', '').replace(' ', '').replace('.', ''):
                        return data
                    data['confidence'] = 'low'
                    data['_validation'] = 'evidence_mismatch'
                results.append(data)
                break
            except Exception as e:
                if '429' in str(e):
                    time.sleep(20 * (attempt + 1))
                else:
                    time.sleep(3)
    with_amt = [r for r in results if r.get('amount') is not None]
    if with_amt:
        return with_amt[0]
    return {'amount': None, 'confidence': 'low'}


def main():
    with open(RESULTS_PATH, encoding='utf-8') as f:
        all_results = [json.loads(line) for line in f]

    client = OpenAI()
    fixes = []

    # 1. Fix evidence_mismatch cases by re-extracting from evidence
    mismatches = [r for r in all_results if r.get('_validation') == 'evidence_mismatch']
    print(f'=== 修复 {len(mismatches)} 个 evidence_mismatch ===')
    for r in mismatches:
        ev = r.get('evidence', '')
        new_amt = extract_from_evidence(ev)
        print(f'  [{r["group"]}] {r["file_name"][:50]}')
        print(f'    old={r["amount"]}  evidence={ev[:60]}')
        print(f'    new={new_amt}')
        fixes.append({
            **r,
            'amount': new_amt,
            'confidence': 'medium',
            '_fix': 'extracted_from_evidence',
        })

    # 2. Second pass on no-amount files (try pages 3-5, beyond initial scan)
    no_amt = [r for r in all_results if r.get('amount') is None]
    print(f'\n=== 二次扫描 {len(no_amt)} 个无金额文件（页 4-6）===')
    for i, r in enumerate(no_amt, 1):
        pdf = Path(r['pdf_path'])
        if not pdf.exists():
            continue
        print(f'  [{i}/{len(no_amt)}] [{r["group"]}] {r["file_name"][:55]}', flush=True)
        new_r = extract_deep(client, pdf, pages_to_try=[3, 4, 5])
        new_amt = new_r.get('amount')
        if new_amt is not None:
            print(f'    → FOUND: {new_amt}  ev: {new_r.get("evidence","")[:50]}', flush=True)
        else:
            print(f'    → still no amount', flush=True)
        fixes.append({
            **r,
            **new_r,
            '_fix': 'pass2_deep',
        })

    # Save fixes
    with open(PASS2_PATH, 'w', encoding='utf-8') as f:
        for r in fixes:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    found = sum(1 for r in fixes if r.get('amount') is not None)
    print(f'\n共处理 {len(fixes)}, 找到金额 {found}')
    print(f'结果: {PASS2_PATH}')


if __name__ == '__main__':
    main()

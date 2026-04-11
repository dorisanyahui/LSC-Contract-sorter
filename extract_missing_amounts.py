"""
批量提取无金额合同的金额
- 目标：所有 维护合同/采购合同/SRF/升级合同 中 金额为空 的记录
- 方法：用 GPT-4o-mini Vision 处理前 3 页 PDF，专注提取金额
- 输出：results JSONL（供审查后应用）
"""
import os, sys, io, json, base64, time, re
from pathlib import Path
from io import BytesIO
import fitz  # PyMuPDF
from openai import OpenAI

# Load .env
_env = Path(__file__).parent / '.env'
if _env.exists():
    for line in _env.read_text(encoding='utf-8').splitlines():
        if '=' in line and not line.strip().startswith('#'):
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

RESULTS_PATH = Path("output/amount_extraction_results.jsonl")

EXTRACT_PROMPT = """You are reading a scanned page from a Chinese software maintenance/purchase/service contract. Extract ALL monetary amounts on this page, then pick the MAIN contract total.

Chinese keywords to find:
- 合同总价 / 合同总金额 / 合同价款 / 总金额 / 总价 (contract total)
- 年度维护费 / 服务费 / 维护费用 / 费用 (fees)
- 含税 / 不含税 / 税前 / 税后 (tax status)
- 人民币 RMB CNY ¥ 元 USD $

Return ONLY a JSON object:
{
  "all_amounts": ["<number + context>", ...],
  "main_amount": <number or null>,
  "currency": "CNY" or "USD" or null,
  "tax_type": "含税" or "不含税" or "unknown",
  "evidence": "<exact text showing main_amount, must include the number>",
  "confidence": "high" or "medium" or "low"
}

Rules:
1. List ALL monetary amounts you can see in `all_amounts` (e.g. ["50000 合同总价含税", "10000 首付"])
2. `main_amount` = the CONTRACT TOTAL (合同总价/总金额). If only a single "费用" is shown, use that.
3. `main_amount` MUST be a plain integer number (50000 not "50,000" or "5万")
4. 5万 = 50000, 10万 = 100000
5. `evidence` MUST contain the exact digit string of main_amount (e.g. "合同总价人民币: 50,000 元")
6. If the page shows "免费" or no amount at all, main_amount = null
7. Do NOT guess or calculate; only extract visible numbers
"""


def render_page(pdf_path: Path, page_no: int, dpi: int = 120) -> str | None:
    """Render a PDF page to base64 JPEG."""
    try:
        with fitz.open(str(pdf_path)) as doc:
            if page_no >= len(doc):
                return None
            page = doc[page_no]
            mat = fitz.Matrix(dpi/72, dpi/72)
            pix = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("jpeg", jpg_quality=80)
            return base64.b64encode(img_bytes).decode()
    except Exception as e:
        return None


def extract_amount_from_pdf(client: OpenAI, pdf_path: Path, max_pages: int = 3) -> dict:
    """Try up to max_pages of PDF. Return first HIGH-confidence result, or best low-conf fallback."""
    results = []
    for page_no in range(max_pages):
        b64 = render_page(pdf_path, page_no)
        if b64 is None:
            break

        for attempt in range(3):
            try:
                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": EXTRACT_PROMPT},
                            {"type": "image_url", "image_url": {
                                "url": f"data:image/jpeg;base64,{b64}",
                                "detail": "auto",
                            }},
                        ],
                    }],
                    max_tokens=300,
                    temperature=0,
                    timeout=60,
                    response_format={"type": "json_object"},
                )
                content = resp.choices[0].message.content.strip()
                data = json.loads(content)
                data['page'] = page_no + 1
                # Normalize key: prefer main_amount
                if 'main_amount' in data and data.get('main_amount') is not None:
                    data['amount'] = data['main_amount']

                amt = data.get('amount')
                ev = str(data.get('evidence', ''))
                if amt is not None:
                    digits = str(int(amt))
                    # Evidence must contain the digits
                    if digits in ev.replace(',', '').replace(' ', '').replace('.', ''):
                        return data  # High confidence - return immediately
                    else:
                        data['confidence'] = 'low'
                        data['_validation'] = 'evidence_mismatch'
                results.append(data)
                break
            except Exception as e:
                err = str(e)
                if "429" in err or "rate_limit" in err.lower():
                    wait = 20 * (attempt + 1)
                    print(f"    Rate limited, wait {wait}s", flush=True)
                    time.sleep(wait)
                else:
                    time.sleep(3)

    # No high-confidence result — return best low-conf result if any
    with_amount = [r for r in results if r.get('amount') is not None]
    if with_amount:
        return with_amount[0]
    return {"amount": None, "currency": None, "tax_type": None,
            "evidence": "", "confidence": "low", "page": max_pages}


def load_already_processed() -> set[str]:
    done = set()
    if RESULTS_PATH.exists():
        with open(RESULTS_PATH, encoding='utf-8') as f:
            for line in f:
                try:
                    r = json.loads(line)
                    done.add(r['pdf_path'])
                except:
                    pass
    return done


def get_targets():
    """Build list of (group, category, pdf_path, year, company) needing extraction."""
    import pandas as pd
    target_cats = {'维护合同', '采购合同', 'SRF', '升级合同'}
    targets = []
    for xlsx in Path('output').glob('*/*合同汇总*.xlsx'):
        group = xlsx.parent.name
        try:
            df = pd.read_excel(xlsx, sheet_name='合同明细')
        except:
            continue
        for _, row in df.iterrows():
            cat = row.get('合同类型', '')
            amt = row.get('金额')
            if cat not in target_cats or not (pd.isna(amt) or amt == 0):
                continue
            fp = str(row.get('文件路径', ''))
            fn = fp.rsplit('/', 1)[-1] if '/' in fp else fp
            year = row.get('年份')
            year_str = str(int(year)) if year and not __import__('pandas').isna(year) else '未知年份'
            phys = Path('output') / group / year_str / fn
            if phys.exists():
                targets.append({
                    'group': group,
                    'category': cat,
                    'year': year_str,
                    'company': str(row.get('合同方', '')),
                    'file_name': fn,
                    'pdf_path': str(phys),
                })
    return targets


def main():
    if not os.environ.get('OPENAI_API_KEY'):
        print("错误：未设置 OPENAI_API_KEY")
        sys.exit(1)

    limit = None
    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        limit = 2

    targets = get_targets()
    done = load_already_processed()
    todo = [t for t in targets if t['pdf_path'] not in done]

    if limit:
        todo = todo[:limit]

    print(f"总目标: {len(targets)}, 已完成: {len(done)}, 待处理: {len(todo)}")

    client = OpenAI()
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)

    start = time.time()
    for i, t in enumerate(todo, 1):
        pdf = Path(t['pdf_path'])
        print(f"[{i}/{len(todo)}] [{t['group']}] {t['file_name'][:60]}", flush=True)

        result = extract_amount_from_pdf(client, pdf)
        output = {**t, **result}

        with open(RESULTS_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(output, ensure_ascii=False) + '\n')

        amt = result.get('amount')
        conf = result.get('confidence')
        print(f"    → amount={amt} ({conf}) evidence='{result.get('evidence','')[:40]}'", flush=True)

        if i % 20 == 0:
            elapsed = time.time() - start
            rate = i / elapsed * 60
            remaining = (len(todo) - i) / rate if rate > 0 else 0
            print(f"  进度: {i}/{len(todo)} ({rate:.1f}/min, 预计剩余 {remaining:.1f}min)", flush=True)

    print(f"\n完成，结果写入 {RESULTS_PATH}")


if __name__ == '__main__':
    main()

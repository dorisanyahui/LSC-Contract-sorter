from __future__ import annotations

import base64
import io
import json
import time
from pathlib import Path
from typing import Any

from loguru import logger

from src.models.schema import OCRPageResult, OCRTextBlock
from src.utils.image_utils import render_page_to_image

# ── GPT-4o-mini Vision OCR ────────────────────────────────────────────
_GPT_OCR_PROMPT = (
    "以下是合同/文件的一页扫描图片。"
    "请逐行输出图片中的所有文字内容，保持原有行结构，不要添加任何解释或格式。"
    "如果某行是表格，用空格或竖线分隔列。"
)

_tpm_window: list[tuple[float, int]] = []
_TPM_BUDGET = 1_800_000    # gpt-4o-mini Tier1 限额 2M，留 10% 缓冲
_TOKENS_PER_PAGE = 2_000   # vision detail=auto, DPI=100 约 1100 image token + 900 text


def _tpm_wait(estimated: int) -> None:
    global _tpm_window
    now = time.time()
    _tpm_window = [(t, tok) for t, tok in _tpm_window if now - t < 60]
    used = sum(tok for _, tok in _tpm_window)
    if used + estimated > _TPM_BUDGET:
        if _tpm_window:
            wait = 61 - (now - _tpm_window[0][0])
            if wait > 0:
                logger.info(f"TPM budget reached, waiting {wait:.0f}s...")
                time.sleep(wait)
    _tpm_window.append((time.time(), estimated))


def _image_to_b64_jpeg(image: Any, quality: int = 80) -> str:
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _gpt_ocr_page(client: Any, image: Any, page_no: int, retries: int = 5) -> str:
    """Send one page image to GPT-4o-mini and get back the raw text."""
    b64 = _image_to_b64_jpeg(image)
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": _GPT_OCR_PROMPT},
            {"type": "image_url", "image_url": {
                "url": f"data:image/jpeg;base64,{b64}",
                "detail": "auto",
            }},
        ],
    }]
    _tpm_wait(_TOKENS_PER_PAGE)
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=1500,
                temperature=0,
                timeout=60,
            )
            actual = getattr(resp.usage, "total_tokens", _TOKENS_PER_PAGE)
            if _tpm_window:
                _tpm_window[-1] = (time.time(), actual)
            return resp.choices[0].message.content.strip()
        except Exception as e:
            err = str(e)
            if "429" in err or "rate_limit" in err.lower():
                wait = 30 * (attempt + 1)
                logger.warning(f"Rate limited page {page_no}, waiting {wait}s...")
                time.sleep(wait)
            else:
                logger.warning(f"GPT OCR failed page {page_no} attempt {attempt+1}: {e}")
                time.sleep(5)
    return ""


class OCRPipeline:
    """Handles OCR processing of PDF pages using PaddleOCR."""

    def __init__(self, settings: Any = None) -> None:
        self._settings = settings
        self._ocr = None  # lazy loaded

    def _load_ocr(self) -> Any:
        """Lazily initialize PaddleOCR (compatible with v2 and v3)."""
        if self._ocr is not None:
            return self._ocr

        try:
            import logging
            logging.disable(logging.WARNING)  # suppress paddle verbose logs

            from paddleocr import PaddleOCR

            lang = "ch"
            if self._settings and hasattr(self._settings, "ocr"):
                lang = getattr(self._settings.ocr, "lang", "ch")

            logger.info("Loading PaddleOCR...")

            # Try v3 API first (no show_log, no use_angle_cls)
            try:
                self._ocr = PaddleOCR(lang=lang)
            except TypeError:
                # Fall back to v2 API
                self._ocr = PaddleOCR(use_angle_cls=True, lang=lang, show_log=False)

            logging.disable(logging.NOTSET)
            logger.info("PaddleOCR loaded.")
        except ImportError:
            logger.error("PaddleOCR is not installed. Run: pip install paddleocr")
            raise
        except Exception as e:
            logger.error(f"Failed to load PaddleOCR: {e}")
            raise

        return self._ocr

    def _parse_ocr_results(self, results: Any, page_no: int) -> list[OCRTextBlock]:
        """Parse PaddleOCR results, handling v2 and v3 formats."""
        text_blocks: list[OCRTextBlock] = []

        if not results:
            return text_blocks

        # v3 returns list of OCRResult objects with .boxes attribute
        # v2 returns list of list of [bbox, [text, conf]]
        try:
            # Try v3 format: results is list, each item has .boxes
            for page_result in results:
                if hasattr(page_result, 'boxes'):
                    for box in page_result.boxes:
                        bbox_points = box.coordinate.tolist() if hasattr(box.coordinate, 'tolist') else box.coordinate
                        text = box.rec_text if hasattr(box, 'rec_text') else str(box)
                        conf = float(box.rec_score) if hasattr(box, 'rec_score') else 0.9
                        xs = [pt[0] for pt in bbox_points]
                        ys = [pt[1] for pt in bbox_points]
                        text_blocks.append(OCRTextBlock(
                            text=text, bbox=[min(xs), min(ys), max(xs), max(ys)],
                            confidence=conf, page=page_no
                        ))
                    return text_blocks
        except Exception:
            pass

        # v2 format: results[0] is list of [bbox_points, [text, conf]]
        try:
            page_lines = results[0] if results else []
            if page_lines is None:
                return text_blocks
            for line in page_lines:
                if not line or len(line) < 2:
                    continue
                bbox_points, text_conf = line
                if isinstance(text_conf, (list, tuple)) and len(text_conf) >= 2:
                    text, conf = text_conf[0], text_conf[1]
                else:
                    continue
                xs = [pt[0] for pt in bbox_points]
                ys = [pt[1] for pt in bbox_points]
                text_blocks.append(OCRTextBlock(
                    text=str(text), bbox=[min(xs), min(ys), max(xs), max(ys)],
                    confidence=float(conf), page=page_no
                ))
        except Exception as e:
            logger.warning(f"Failed to parse OCR results on page {page_no}: {e}")

        return text_blocks

    def ocr_page(self, image: Any, page_no: int) -> OCRPageResult:
        """Run OCR on a single PIL Image page."""
        import numpy as np

        ocr = self._load_ocr()
        width, height = image.size
        img_array = np.array(image)

        try:
            results = ocr.ocr(img_array)
        except Exception as e:
            logger.warning(f"OCR failed on page {page_no}: {e}")
            return OCRPageResult(page_no=page_no, width=width, height=height,
                                 text_blocks=[], raw_text="", confidence_avg=0.0)

        text_blocks = self._parse_ocr_results(results, page_no)
        total_conf = sum(b.confidence for b in text_blocks)
        count = len(text_blocks)
        avg_conf = total_conf / count if count > 0 else 0.0
        raw_text = "\n".join(b.text for b in text_blocks)

        return OCRPageResult(page_no=page_no, width=width, height=height,
                             text_blocks=text_blocks, raw_text=raw_text,
                             confidence_avg=avg_conf)

    def _ocr_pdf_gpt(self, pdf_path: Path, dpi: int) -> list[OCRPageResult]:
        """OCR all pages using GPT-4o-mini Vision."""
        import fitz
        from openai import OpenAI

        client = OpenAI(timeout=60)

        doc = fitz.open(str(pdf_path))
        page_count = len(doc)
        doc.close()

        logger.info(f"[GPT] OCR processing {page_count} pages of {pdf_path.name}")

        results: list[OCRPageResult] = []
        for page_no in range(page_count):
            try:
                image = render_page_to_image(pdf_path, page_no, dpi=dpi)
                raw_text = _gpt_ocr_page(client, image, page_no)
                width, height = image.size
                results.append(OCRPageResult(
                    page_no=page_no,
                    width=width,
                    height=height,
                    text_blocks=[],
                    raw_text=raw_text,
                    confidence_avg=0.95,
                ))
                logger.debug(f"  Page {page_no + 1}/{page_count}: {len(raw_text)} chars")
            except Exception as e:
                logger.warning(f"Failed to OCR page {page_no} of {pdf_path.name}: {e}")
                results.append(OCRPageResult(
                    page_no=page_no, width=0, height=0,
                    text_blocks=[], raw_text="", confidence_avg=0.0,
                ))

        return results

    def _ocr_pdf_paddle(self, pdf_path: Path, dpi: int) -> list[OCRPageResult]:
        """OCR all pages using local PaddleOCR."""
        import fitz

        doc = fitz.open(str(pdf_path))
        page_count = len(doc)
        doc.close()

        logger.info(f"[Paddle] OCR processing {page_count} pages of {pdf_path.name}")

        results: list[OCRPageResult] = []
        for page_no in range(page_count):
            try:
                image = render_page_to_image(pdf_path, page_no, dpi=dpi)
                page_result = self.ocr_page(image, page_no)
                results.append(page_result)
                logger.debug(f"  Page {page_no + 1}/{page_count}: {len(page_result.raw_text)} chars")
            except Exception as e:
                logger.warning(f"Failed to OCR page {page_no} of {pdf_path.name}: {e}")
                results.append(OCRPageResult(
                    page_no=page_no, width=0, height=0,
                    text_blocks=[], raw_text="", confidence_avg=0.0,
                ))

        return results

    def ocr_pdf(self, pdf_path: Path, dpi: int = 100) -> list[OCRPageResult]:
        """Render each page of a PDF and run OCR (engine selected by settings)."""
        engine = "gpt"
        if self._settings and hasattr(self._settings, "ocr"):
            engine = getattr(self._settings.ocr, "engine", "gpt")

        if engine == "paddleocr":
            return self._ocr_pdf_paddle(pdf_path, dpi)
        else:
            return self._ocr_pdf_gpt(pdf_path, dpi)

    def load_from_cache(self, md5: str, cache_dir: Path) -> list[OCRPageResult] | None:
        """Load OCR results from cache file."""
        cache_file = cache_dir / "ocr" / f"{md5}.json"
        if not cache_file.exists():
            return None
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [OCRPageResult(**item) for item in data]
        except Exception as e:
            logger.warning(f"Failed to load OCR cache for {md5}: {e}")
            return None

    def save_to_cache(self, md5: str, results: list[OCRPageResult], cache_dir: Path) -> None:
        """Save OCR results to cache file."""
        cache_dir_ocr = cache_dir / "ocr"
        cache_dir_ocr.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir_ocr / f"{md5}.json"
        try:
            data = [r.model_dump() for r in results]
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save OCR cache for {md5}: {e}")

    def process(self, pdf_path: Path, md5: str, force: bool = False) -> list[OCRPageResult]:
        """Process a PDF: check cache first unless force=True."""
        cache_dir = Path("cache")
        if self._settings and hasattr(self._settings, "cache_dir"):
            cache_dir = self._settings.cache_dir

        if not force:
            cached = self.load_from_cache(md5, cache_dir)
            if cached is not None:
                logger.debug(f"OCR cache hit for {pdf_path.name}")
                return cached

        dpi = 200
        if self._settings and hasattr(self._settings, "ocr"):
            dpi = getattr(self._settings.ocr, "dpi", 200)

        results = self.ocr_pdf(pdf_path, dpi=dpi)
        self.save_to_cache(md5, results, cache_dir)
        return results

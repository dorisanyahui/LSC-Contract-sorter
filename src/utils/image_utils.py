from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image as PILImage


def render_page_to_image(pdf_path: Path, page_no: int, dpi: int = 200) -> "PILImage.Image":
    """Render a single PDF page to a PIL Image using PyMuPDF."""
    import fitz  # PyMuPDF
    from PIL import Image

    doc = fitz.open(str(pdf_path))
    try:
        page = doc[page_no]
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_data = pix.tobytes("png")
        return Image.open(io.BytesIO(img_data)).convert("RGB")
    finally:
        doc.close()


def crop_bbox(image: "PILImage.Image", bbox: list[float], padding: int = 10) -> "PILImage.Image":
    """Crop an image to the given bounding box with optional padding.

    bbox format: [x0, y0, x1, y1] in pixels.
    """
    width, height = image.size
    x0 = max(0, int(bbox[0]) - padding)
    y0 = max(0, int(bbox[1]) - padding)
    x1 = min(width, int(bbox[2]) + padding)
    y1 = min(height, int(bbox[3]) + padding)
    return image.crop((x0, y0, x1, y1))


def images_to_base64(images: list["PILImage.Image"], quality: int = 80) -> list[str]:
    """Convert a list of PIL Images to base64-encoded JPEG strings."""
    result: list[str] = []
    for img in images:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        result.append(b64)
    return result

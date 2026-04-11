from __future__ import annotations

import shutil
from pathlib import Path

from src.utils.hash_utils import md5_file


def scan_pdfs(input_dir: Path) -> list[Path]:
    """Recursively scan a directory for PDF files (case-insensitive, deduped)."""
    if not input_dir.exists():
        return []
    seen: set[Path] = set()
    result: list[Path] = []
    for p in sorted(input_dir.rglob("*")):
        if p.suffix.lower() == ".pdf" and p.is_file():
            resolved = p.resolve()
            if resolved not in seen:
                seen.add(resolved)
                result.append(p)
    return result


def ensure_dir(path: Path) -> None:
    """Create directory and all parents if they do not exist."""
    path.mkdir(parents=True, exist_ok=True)


def copy_if_new(src: Path, dst_dir: Path) -> Path:
    """Copy src to dst_dir if a file with the same MD5 does not already exist there.

    Returns the destination path (whether newly copied or the existing duplicate).
    """
    ensure_dir(dst_dir)
    src_md5 = md5_file(src)

    # Check if any existing file in dst_dir has the same MD5
    for existing in dst_dir.iterdir():
        if existing.is_file() and existing.suffix.lower() == src.suffix.lower():
            try:
                if md5_file(existing) == src_md5:
                    return existing
            except OSError:
                pass

    dst = dst_dir / src.name
    # Avoid overwriting an existing file with a different name but same stem
    if dst.exists():
        stem = src.stem
        suffix = src.suffix
        counter = 1
        while dst.exists():
            dst = dst_dir / f"{stem}_{counter}{suffix}"
            counter += 1

    shutil.copy2(src, dst)
    return dst

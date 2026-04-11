import re
import shutil
from pathlib import Path


def safe_folder_name(name: str) -> str:
    if not name:
        return "未命名"
    return re.sub(r'[<>:"/\\|?*]', "_", str(name)).strip()


def clear_runtime_folders(output_dir: Path, review_dir: Path):
    """
    确保 output 和 review 文件夹存在，不自动清空。
    如需全量重跑，请手动删除这两个文件夹后再执行。
    """
    for folder in [output_dir, review_dir]:
        folder.mkdir(parents=True, exist_ok=True)


def ensure_unique_path(file_path: Path) -> Path:
    """
    如果目标文件已存在，则自动加序号避免覆盖。
    """
    if not file_path.exists():
        return file_path

    stem = file_path.stem
    suffix = file_path.suffix
    parent = file_path.parent

    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def copy_to_group_folder(output_dir: Path, src_file: Path, group_name: str, year: str) -> str:
    group_dir = output_dir / safe_folder_name(group_name) / safe_folder_name(str(year))
    group_dir.mkdir(parents=True, exist_ok=True)

    target_file = group_dir / src_file.name
    target_file = ensure_unique_path(target_file)

    shutil.copy2(src_file, target_file)
    return str(target_file)


def copy_to_review_folder(review_dir: Path, src_file: Path) -> str:
    review_dir.mkdir(parents=True, exist_ok=True)

    target_file = review_dir / src_file.name
    target_file = ensure_unique_path(target_file)

    shutil.copy2(src_file, target_file)
    return str(target_file)
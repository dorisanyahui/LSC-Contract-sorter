# -*- coding: utf-8 -*-
"""Reorganize output folders based on corrected audit.jsonl group assignments.

For each record in audit.jsonl:
1. Determine correct target folder: output/{group}/{year}/
   - For 其他 and 内部文件: output/{group}/ (no year subfolder)
   - For all other groups: output/{group}/{year}/
2. Find the physical file (check old location, then search output/)
3. Move to correct location
"""
import json
import os
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

OUTPUT_DIR = Path("output")
NO_YEAR_GROUPS = {"其他", "内部文件"}


def find_file_in_output(md5: str, filename: str) -> Path | None:
    """Find a file in the output directory by searching all subdirectories."""
    if not filename:
        return None
    # Walk all output subdirectories
    for root, dirs, files in os.walk(OUTPUT_DIR):
        for f in files:
            if f == filename:
                return Path(root) / f
    return None


def main():
    records = []
    with open("output/audit.jsonl", "r", encoding="utf-8") as f:
        for line in f:
            records.append(json.loads(line))

    moved = 0
    not_found = 0
    already_correct = 0
    errors = 0

    for r in records:
        group = r.get("detected_group", "其他") or "其他"
        year = r.get("report_year", "")
        filename = r.get("source_file", "")
        md5 = r.get("md5", "")
        output_path = r.get("output_path", "")

        if not filename:
            continue

        # Determine target directory
        if group in NO_YEAR_GROUPS:
            target_dir = OUTPUT_DIR / group
        else:
            year_str = str(year) if year else "未知年份"
            target_dir = OUTPUT_DIR / group / year_str

        target_path = target_dir / filename

        # Check if file is already at target
        if target_path.exists():
            already_correct += 1
            # Update output_path in record
            r["output_path"] = str(target_path)
            continue

        # Try to find the file
        # First check the recorded output_path
        source = None
        if output_path and Path(output_path).exists():
            source = Path(output_path)
        else:
            # Search for the file in output/
            source = find_file_in_output(md5, filename)

        if not source:
            not_found += 1
            continue

        # Move the file
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target_path))
            r["output_path"] = str(target_path)
            moved += 1
        except Exception as e:
            print(f"Error moving {filename}: {e}")
            errors += 1

    # Write updated audit.jsonl with new output_paths
    with open("output/audit.jsonl", "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Moved: {moved}")
    print(f"Already correct: {already_correct}")
    print(f"Not found: {not_found}")
    print(f"Errors: {errors}")

    # Clean up empty directories
    cleaned = 0
    for root, dirs, files in os.walk(OUTPUT_DIR, topdown=False):
        for d in dirs:
            dir_path = Path(root) / d
            try:
                if not any(dir_path.iterdir()):
                    dir_path.rmdir()
                    cleaned += 1
            except Exception:
                pass
    print(f"Cleaned empty dirs: {cleaned}")


if __name__ == "__main__":
    main()

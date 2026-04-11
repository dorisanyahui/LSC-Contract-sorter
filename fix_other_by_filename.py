# -*- coding: utf-8 -*-
"""Fix 其他 files that can be identified by filename."""
import json
import hashlib
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

OUTPUT = Path("output")

# Filename substring → group
FILENAME_GROUPS = {
    "丰树": "丰树集团",
    "丰龙仓储": "丰树集团",
    "嘉兴丰跃": "丰树集团",
    "翎丰房地产": "丰树集团",
    "纽曼泰克": "阿特拉斯",
    "柳州泰克": "阿特拉斯",
    "molex": "莫仕集团",
    "Molex": "莫仕集团",
    "Entegris": "应特格",
    "TYCO": "泰科集团",
    "Parker": "派克集团",
    "parker": "派克集团",
    "法利咨询": "必维集团",
    "法力咨询": "必维集团",
    "艾美": "艾美仕",
    "爱沛": "��沛",
    "狼爪": "狼爪",
    "福寿家": "福寿园",
    "狮城德科": "其他",  # keep in 其他 - unknown
    "珐菲琦": "其他",  # keep - unknown
    "苏州迈捷": "其他",  # keep - unknown
}


def compute_md5(filepath: Path) -> str:
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def main():
    # Build md5 → record index map
    records = []
    md5_idx = {}
    with open("output/audit.jsonl", "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            r = json.loads(line)
            records.append(r)
            md5 = r.get("file_md5", "")
            if md5:
                md5_idx[md5] = i

    # Scan 其他 folder for PDFs
    other_dir = OUTPUT / "其他"
    moved = 0
    updated = 0

    for pdf in sorted(other_dir.glob("*.pdf")):
        fname = pdf.name
        # Try to match
        best_group = None
        best_len = 0
        for substr, group in FILENAME_GROUPS.items():
            if substr.lower() in fname.lower() and len(substr) > best_len:
                best_group = group
                best_len = len(substr)

        if not best_group or best_group == "其他":
            continue

        # Compute MD5 to find audit record
        md5 = compute_md5(pdf)

        # Update audit record
        if md5 in md5_idx:
            idx = md5_idx[md5]
            records[idx]["detected_group"] = best_group
            updated += 1

        # Move file
        year = None
        if md5 in md5_idx:
            year = records[md5_idx[md5]].get("report_year", "")

        year_str = str(year) if year else "未知年份"
        target_dir = OUTPUT / best_group / year_str
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / fname
        if not target.exists():
            shutil.move(str(pdf), str(target))
            moved += 1
            print(f"Moved: {fname} → {best_group}/{year_str}/")

    # Save updated audit
    with open("output/audit.jsonl", "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\nMoved: {moved} files")
    print(f"Updated: {updated} audit records")


if __name__ == "__main__":
    main()

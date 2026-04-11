"""
将"其他"集团中可识别的记录移到正确集团：
1. 按文件名关键词匹配现有集团文件夹
2. 特殊处理：珐菲琦→发发奇、爱博才思→丹纳赫集团
3. 更新 audit.jsonl + audit_fixed.jsonl
4. 移动物理 PDF 文件
"""
import json, sys, io, shutil, re
from pathlib import Path
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

AUDIT_PATH = Path("output/audit.jsonl")
OUTPUT_BASE = Path("output")

# ── 特殊映射（文件名关键词 → 目标集团）──────────────
SPECIAL_FILENAME_MAPS = {
    "珐菲琦": "发发奇",
    "爱博才思": "丹纳赫集团",
    "东福喜": "日本电产",
    "SONY SEH": "索尼",
}

# 不应创建的新集团（没有独立文件夹的直接跳过）
# 狮城德科、苏州迈捷没有独立文件夹，保留在其他

# ── 不应自动匹配的集团名 ──────────────
SKIP_GROUPS = {"其他", "内部文件"}


def load_records():
    records = []
    with open(AUDIT_PATH, encoding="utf-8") as f:
        for line in f:
            records.append(json.loads(line))
    return records


def get_existing_groups():
    return {d.name for d in OUTPUT_BASE.iterdir() if d.is_dir()}


def match_group(filename, company, existing_groups):
    """尝试从文件名/公司名匹配到现有集团"""
    # 1. 特殊映射优先
    for keyword, target in SPECIAL_FILENAME_MAPS.items():
        if keyword in filename:
            return target

    # 2. 按集团名长度降序匹配（长名优先，避免短名误匹配）
    sorted_groups = sorted(existing_groups, key=len, reverse=True)
    for g in sorted_groups:
        if g in SKIP_GROUPS or len(g) < 2:
            continue
        if g in filename or g in company:
            return g

    return None


def fix_audit(records, existing_groups):
    """修复 audit 中其他集团的记录"""
    changes = defaultdict(list)

    for r in records:
        if r.get("detected_group") != "其他":
            continue

        fn = r.get("file_name", "")
        company = r.get("detected_company", "") or ""

        target = match_group(fn, company, existing_groups)
        if target:
            old_group = r["detected_group"]
            r["detected_group"] = target
            changes[target].append(fn)

    return changes


def move_pdfs(changes):
    """移动物理 PDF 文件到正确集团文件夹"""
    moved = 0
    errors = []

    other_dir = OUTPUT_BASE / "其他"
    if not other_dir.exists():
        return moved, errors

    for target_group, filenames in changes.items():
        for fn in filenames:
            # 在其他文件夹中查找文件（可能在子目录或根目录）
            found = list(other_dir.rglob(fn))
            if not found:
                continue

            for src in found:
                # 确定年份子目录
                rel = src.relative_to(other_dir)
                if len(rel.parts) > 1:
                    # 在年份子目录中
                    year_dir = rel.parts[0]
                    dest = OUTPUT_BASE / target_group / year_dir / fn
                else:
                    # 在根目录，尝试从文件名提取年份
                    year_match = re.search(r'(\d{4})', fn)
                    if year_match:
                        year = year_match.group(1)
                        if 2000 <= int(year) <= 2026:
                            dest = OUTPUT_BASE / target_group / year / fn
                        else:
                            dest = OUTPUT_BASE / target_group / fn
                    else:
                        dest = OUTPUT_BASE / target_group / fn

                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    try:
                        shutil.copy2(str(src), str(dest))
                        try:
                            src.unlink()
                        except PermissionError:
                            pass  # 文件被占用，复制已成功
                        moved += 1
                    except Exception as e:
                        errors.append(f"{fn}: {e}")

    return moved, errors


def main():
    records = load_records()
    existing_groups = get_existing_groups()

    # 统计修复前
    other_count = sum(1 for r in records if r.get("detected_group") == "其他")
    print(f"修复前：其他集团 {other_count} 条记录")

    # Dry run 先看匹配结果
    dry_run = "--dry-run" in sys.argv

    # 修复 audit
    changes = fix_audit(records, existing_groups)

    total_fixed = sum(len(v) for v in changes.values())
    mode = "[DRY RUN] " if dry_run else ""
    print(f"\n{mode}修复了 {total_fixed} 条记录，分配到 {len(changes)} 个集团：")
    for group in sorted(changes.keys()):
        fns = changes[group]
        print(f"  {group}: {len(fns)} 条")
        for fn in fns[:3]:
            print(f"    {fn[:70]}")
        if len(fns) > 3:
            print(f"    ... 还有 {len(fns)-3} 条")

    if dry_run:
        other_after = sum(1 for r in records if r.get("detected_group") == "其他")
        print(f"\n[DRY RUN] 其他集团将从 {other_count} 减少到 {other_after}")
        return

    # 写回 audit
    with open(AUDIT_PATH, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    shutil.copy(AUDIT_PATH, "output/audit_fixed.jsonl")
    print(f"\naudit.jsonl 和 audit_fixed.jsonl 已更新")

    # 移动 PDF
    print("\n移动 PDF 文件...")
    moved, errors = move_pdfs(changes)
    print(f"移动了 {moved} 个 PDF")
    if errors:
        print(f"{len(errors)} 个错误:")
        for e in errors[:10]:
            print(f"  {e}")

    # 统计修复后
    other_after = sum(1 for r in records if r.get("detected_group") == "其他")
    print(f"\n修复后：其他集团 {other_after} 条记录（减少 {other_count - other_after} 条）")


if __name__ == "__main__":
    main()

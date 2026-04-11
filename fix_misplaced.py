# -*- coding: utf-8 -*-
"""Fix misplaced files found during folder-by-folder check."""
import json, sys, shutil, hashlib
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

OUTPUT = Path("output")

# file_name substring → correct group
# Only fixing CLEAR misplacements, not borderline cases
FIXES = {
    # FlexLink: 富耐连 is Moen subsidiary, not FlexLink
    "富耐连自动化系统（上海）有限公司": "摩恩",

    # 万代: 深圳子希仪器 is not Bandai
    "深圳子希仪器": "其他",

    # 三井集团: 莫仕连接器 should be 莫仕集团
    "莫仕连接器（成都）": "莫仕集团",

    # 亚玛芬: 泛亚班拿 is a separate logistics company
    "泛亚班拿国际运输代理": "泛亚班拿",

    # 日本电产: 索尼电子（无锡）should be 索尼
    "索尼电子（无锡）": "索尼",

    # 索尼: 村田新能源 should be its own group or 索尼 sub? Actually Murata is independent
    "村田新能源（无锡）": "村田",

    # 英特尔: 伊顿（中国）should be 伊顿
    "伊顿（中国）投资有限公司": "伊顿",

    # 西门子: 空气化工CN30 should be 空气化工
    "空气化工CN30": "空气化工",

    # 第一精工: 三井纤维物质贸易 should be 三井集团
    "三井纤维物质贸易": "三井集团",

    # 第一精工: 狮城精密/欣阳精密/广州三新 → 欣阳集团
    "狮城精密模塑": "欣阳集团",
    "狮城精密_维护合同": "欣阳集团",
    "欣阳精密": "欣阳集团",
    "广州三新": "欣阳集团",

    # 空气化工: 慧瞻 is a separate group
    "慧瞻2家公司": "慧瞻",

    # 马勒集团: 慧瞻 should be 慧瞻
    "慧瞻CN09": "慧瞻",

    # 默克: 艾默生船用 should be 艾默生
    "艾默生船用": "艾默生",

    # 默克: 安智光剂 is AZ Electronic Materials = Merck, keep in 默克
    # "安智光剂": "默克",  # Correct! AZ EM is Merck subsidiary

    # 博阁玛: 博格玛 is the same group (OCR variant), keep
    # "博格玛采购咨询": "博阁玛",  # Same group, OK

    # 丽星邮轮: 苏州迈捷商旅 should be checked
    "苏州迈捷商旅": "其他",

    # 莫仕集团: 辉莫科技/辉科医疗/辉美医疗/世达普 - these are Koch/Molex subsidiaries, keep
    # "辉莫科技": "莫仕集团",  # Koch/Molex sub, OK

    # 丰树集团: 南院 should be 福寿园 (already fixed in audit, but files may still be wrong)
    "上海南院事业发展": "福寿园",
    "上海南院实业发展": "福寿园",
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
    # Load audit records
    records = []
    md5_map = {}
    with open("output/audit.jsonl", "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            r = json.loads(line)
            records.append(r)
            md5 = r.get("file_md5", "")
            if md5:
                md5_map[md5] = i

    # Scan all PDFs and fix misplacements
    moved = 0
    audit_fixed = 0

    for root, dirs, files in __import__('os').walk(OUTPUT):
        for fname in files:
            if not fname.lower().endswith('.pdf'):
                continue
            filepath = Path(root) / fname

            # Check if this file matches any fix rule
            new_group = None
            for substr, group in FIXES.items():
                if substr.lower() in fname.lower():
                    new_group = group
                    break

            if not new_group:
                continue

            # Get current group from folder structure
            rel = filepath.relative_to(OUTPUT)
            parts = rel.parts
            current_group = parts[0] if parts else ""

            if current_group == new_group:
                continue  # Already correct

            print(f"FIX: {fname}")
            print(f"  {current_group} → {new_group}")

            # Update audit record
            md5 = compute_md5(filepath)
            if md5 in md5_map:
                idx = md5_map[md5]
                records[idx]["detected_group"] = new_group
                audit_fixed += 1

                # Determine year
                year = records[idx].get("report_year", "")
                year_str = str(year) if year else "未知年份"
            else:
                year_str = parts[1] if len(parts) > 2 else "未知年份"

            # Move file
            if new_group in ("其他", "内部文件"):
                target_dir = OUTPUT / new_group
            else:
                target_dir = OUTPUT / new_group / year_str

            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / fname
            if not target.exists():
                shutil.move(str(filepath), str(target))
                moved += 1
                print(f"  Moved to: {new_group}/{year_str}/")
            else:
                print(f"  Target exists, skipping move")

    # Save audit
    with open("output/audit.jsonl", "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\nMoved: {moved} files")
    print(f"Audit fixed: {audit_fixed} records")


if __name__ == "__main__":
    main()

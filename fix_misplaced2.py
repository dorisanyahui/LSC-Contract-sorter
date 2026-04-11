"""
修复错误归类的文件和集团：
1. 狼爪相关文件 → 归入"狼爪"
2. 赫斯 → 合并到"赫斯可"
3. 酩悦轩尼诗 & 帝亚吉欧 → 合并到"酩悦轩尼诗"
4. 个别放错的文件修正集团
5. 观光投资文件夹清理
"""
import json, sys, io, shutil
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

AUDIT_PATH = Path("output/audit.jsonl")

# ── 集团修正规则 ─────────────────────────────────
# 按文件名关键词修正集团
FILENAME_GROUP_FIXES = {
    # 狼爪文件不应归到观光投资
    "泛纬软件维护服务-狼爪.pdf": "狼爪",
    "泛纬软件购买合同-狼爪.pdf": "狼爪",
    "狼爪框架协议.pdf": "狼爪",
    # 索尼文件不应在日本电产
    "声明（取消固定资产模块）_索尼电子（无锡）有限公司（简称SEW)_2006.8.4.pdf": "索尼",
    # 空气化工文件不应在西门子
    "HOR_空气化工CN30_20170330.pdf": "空气化工",
    # 艾默生文件不应在默克
    "泛纬软件维护服务合同_艾默生船用过过程控制系统（上海）有限公司_合同有效期2013年1月1日至2013年12月31日.pdf": "艾默生",
}

# 集团级合并：将一个集团全部合并到另一个
GROUP_MERGES = {
    "赫斯": "赫斯可",              # 同一家 Husco
    "帝亚吉欧": "酩悦轩尼诗",       # 酩悦轩尼诗帝亚吉欧是同一家公司
    "观光投资": "狼爪",             # 观光投资文件实际都是狼爪的（OCR误识别公司名）
}


def fix_audit():
    records = []
    with open(AUDIT_PATH, encoding="utf-8") as f:
        for line in f:
            records.append(json.loads(line))

    changes = {"filename_fix": 0, "group_merge": 0, "company_fix": 0}

    for r in records:
        fn = r.get("file_name", "")
        group = r.get("detected_group", "")

        # 1. 按文件名修正
        if fn in FILENAME_GROUP_FIXES:
            new_group = FILENAME_GROUP_FIXES[fn]
            if group != new_group:
                print(f"[文件名修正] {fn}: {group} -> {new_group}")
                r["detected_group"] = new_group
                changes["filename_fix"] += 1

        # 2. 集团合并
        group = r.get("detected_group", "")
        if group in GROUP_MERGES:
            new_group = GROUP_MERGES[group]
            r["detected_group"] = new_group
            changes["group_merge"] += 1

        # 3. 修复OCR错误的公司名（狼爪相关）
        if "狼爪" in fn:
            company = r.get("detected_company", "")
            bad_companies = ["观光投资", "猿人贸易", "猩尘贸易", "猎爪贸易"]
            for bad in bad_companies:
                if bad in company:
                    r["detected_company"] = "狼爪贸易（上海）有限公司"
                    changes["company_fix"] += 1
                    break

    # 写回
    with open(AUDIT_PATH, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    shutil.copy(AUDIT_PATH, "output/audit_fixed.jsonl")

    print(f"\n修复完成:")
    for k, v in changes.items():
        print(f"  {k}: {v}处")
    return changes


def move_pdfs():
    """移动物理PDF文件到正确的文件夹"""
    base = Path("output")
    moves = 0

    # 1. 移动按文件名修正的文件
    for fn, target_group in FILENAME_GROUP_FIXES.items():
        # Find this file anywhere in output
        for pdf in base.rglob(fn):
            current_group = pdf.parts[1] if len(pdf.parts) > 2 else ""
            if current_group != target_group:
                # Determine year subfolder
                year_folder = pdf.parent.name if pdf.parent.name != current_group else ""
                if year_folder and year_folder.isdigit():
                    dest = base / target_group / year_folder / fn
                else:
                    dest = base / target_group / fn
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    shutil.move(str(pdf), str(dest))
                    print(f"移动: {pdf} -> {dest}")
                    moves += 1

    # 2. 移动合并集团的所有文件
    for old_group, new_group in GROUP_MERGES.items():
        old_dir = base / old_group
        new_dir = base / new_group
        if old_dir.exists():
            for pdf in old_dir.rglob("*.pdf"):
                rel = pdf.relative_to(old_dir)
                dest = new_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    shutil.move(str(pdf), str(dest))
                    print(f"移动: {pdf} -> {dest}")
                    moves += 1

    # 3. 清理空的旧文件夹
    for old_group in GROUP_MERGES:
        old_dir = base / old_group
        if old_dir.exists():
            shutil.rmtree(old_dir)
            print(f"删除旧文件夹: {old_dir}")

    print(f"\n共移动 {moves} 个文件")


if __name__ == "__main__":
    print("=== 修复 audit 数据 ===")
    fix_audit()
    print("\n=== 移动 PDF 文件 ===")
    move_pdfs()

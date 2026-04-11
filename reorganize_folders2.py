# -*- coding: utf-8 -*-
"""Reorganize output folders to match normalized group names from audit.jsonl.

Strategy:
1. Build a map of file_md5 -> new group from audit.jsonl
2. Scan all PDF files in output/ folders
3. Move files to correct group/year folders
4. Rename old group folders to new normalized names
"""
import json
import os
import hashlib
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

OUTPUT_DIR = Path("output")
NO_YEAR_GROUPS = {"其他", "内部文件"}

# Old folder name → new group name
FOLDER_RENAMES = {
    "万代玩具(深圳)有限公司": "万代",
    "上海中航光电子有限公司": "中航光电",
    "上海丹尼逊液压件有限公司": "派克集团",
    "上海伊藤忠商事有限公司": "伊藤忠",
    "上海环世捷运物流有限公司": "上海环世",
    "上海申创中小企业合作交流技术促进中心": "其他",
    "东莞创宝达电器制品有限公司": "创宝达",
    "中海散货运输有限公司": "中海散货",
    "亚玛芬体育用品贸易(上海)有限公司": "亚玛芬",
    "亨斯": "亨斯迈",
    "亮讯国际贸易(上海)有限公司": "亮讯",
    "以星综合航运(中国)有限公司": "以星",
    "Boston Scientific": "波士顿科学",
    "IMS Market Research": "艾美仕",
    "六洲酒店管理(上海)有限公司": "六州酒店",
    "台积电(中国)有限公司": "台积电",
    "奥碧虹(上海)化妆品贸易有限公司": "奥碧虹",
    "宁波璨宇光电有限公司": "璨宇光电",
    "摩迪(上海)咨询有限公司": "摩迪",
    "摩迪英联认证有限公司": "摩迪",
    "格柏(上海)工业数控设备有限公司": "格柏科技",
    "珀金埃尔": "珀金埃尔默",
    "瑞侃电子（上海）有限公司": "泰科集团",
    "锐科": "派克集团",
    "高仪(上海)卫生洁具有限公司": "骊住",
    "英特尔(中国)有限公司": "英特尔",
    "英飞拉网络(上海)有限公司": "英飞拉",
    "博莱特(上海)贸易有限公司": "阿特拉斯",
    "卡摩速企业管理(中国)有限公司": "卡摩速",
    "友尚电子有限公司": "友尚电子",
    "勒姆研究(上海)有限公司": "勒姆研究",
    "北京华夏石化工程监理有限公司": "华夏石化",
    "夏特装饰材料(上海)有限公司": "夏特",
    "天马微电子有限公司": "天马微电子",
    "奥升德功能材料(上海)有限公司": "奥升德",
    "安弗施无线射频系统(上海)有限公司": "安弗施",
    "安捷伦科技(中国)有限公司": "安捷伦",
    "安智光刻电子材料(上海)有限公司": "安智光刻",
    "宝马格(中国)工程机械有限公司": "宝马格",
    "布鲁克斯仪器贸易(上海)有限公司": "布鲁克斯",
    "戴纳派克(中国)压实摊铺设备有限公司": "戴纳派克",
    "旺众商用设备(上海)有限公司": "旺众",
    "是德科技(中国)有限公司": "是德科技",
    "普利司通(中国)投资有限公司": "普利司通",
    "普尔文技术(北京)有限公司": "普尔文",
    "牧野机床(中国)有限公司": "牧野机床",
    "特易行国际货运代理(深圳)有限公司": "特易行",
    "环捷国际货运代理(上海)有限公司": "环捷",
    "美利达自行车(中国)有限公司": "美利达",
    "美吉莱商贸(上海)有限公司": "美吉莱",
    "肯纳飞硕金属(上海)有限公司": "肯纳飞硕",
    "舒捷(上海)胶带有限公司": "舒捷",
    "艺康(中国)投资有限公司": "艺康",
    "花王(上海)化工有限公司": "花王",
    "诺马连接技术(无锡)有限公司": "诺马",
    "赛特福德(深圳)贸易有限公司": "赛特福德",
    "达能亚太(上海)管理有限公司": "达能",
    "辽宁三友商贸有限责任公司": "三友商贸",
    "达凯(上海)电子科技有限公司": "达凯",
    "钇镭科(北京)光学电子制造有限公司": "钇镭科",
    "锦海捷亚国际货运有限公司": "锦海捷亚",
    "镭富电子设备(上海)有限公司": "镭富电子",
    "默天旎贸易(上海)有限公司": "默天旎",
    "福建聚力电机有限公司": "聚力电机",
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
    # Build md5 → {group, year, filename} map from audit.jsonl
    audit_map = {}
    with open("output/audit.jsonl", "r", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            md5 = r.get("file_md5", "")
            if md5:
                audit_map[md5] = {
                    "group": r.get("detected_group", "其他") or "其他",
                    "year": r.get("report_year", ""),
                    "filename": r.get("file_name", ""),
                }

    print(f"Loaded {len(audit_map)} records from audit.jsonl")

    # Step 1: Rename old group folders
    renamed = 0
    for old_name, new_name in FOLDER_RENAMES.items():
        old_path = OUTPUT_DIR / old_name
        if not old_path.exists():
            continue
        new_path = OUTPUT_DIR / new_name
        if old_path == new_path:
            continue
        if new_path.exists():
            # Merge: move all files from old to new
            for item in old_path.rglob("*"):
                if item.is_file():
                    rel = item.relative_to(old_path)
                    target = new_path / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.exists():
                        shutil.move(str(item), str(target))
            # Remove old dir if empty
            try:
                shutil.rmtree(str(old_path))
            except Exception:
                pass
            renamed += 1
        else:
            old_path.rename(new_path)
            renamed += 1

    print(f"Renamed/merged {renamed} folders")

    # Step 2: Scan all PDF files and check if they're in the right place
    moved = 0
    already_correct = 0
    no_match = 0

    for root, dirs, files in os.walk(OUTPUT_DIR):
        for fname in files:
            if not fname.lower().endswith('.pdf'):
                continue
            filepath = Path(root) / fname
            # Compute MD5
            md5 = compute_md5(filepath)

            if md5 not in audit_map:
                no_match += 1
                continue

            info = audit_map[md5]
            group = info["group"]
            year = info["year"]

            # Determine correct target
            if group in NO_YEAR_GROUPS:
                target_dir = OUTPUT_DIR / group
            else:
                year_str = str(year) if year else "未知年份"
                target_dir = OUTPUT_DIR / group / year_str

            target_path = target_dir / fname

            # Check if already correct
            if filepath == target_path or filepath.resolve() == target_path.resolve():
                already_correct += 1
                continue

            # Move
            target_dir.mkdir(parents=True, exist_ok=True)
            if target_path.exists():
                # File already exists at target - skip (duplicate)
                already_correct += 1
                continue

            try:
                shutil.move(str(filepath), str(target_path))
                moved += 1
            except Exception as e:
                print(f"Error moving {fname}: {e}")

    print(f"Moved: {moved}")
    print(f"Already correct: {already_correct}")
    print(f"No audit match: {no_match}")

    # Step 3: Clean up empty directories
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

import re
from pathlib import Path
import pandas as pd


def safe_folder_name(name: str) -> str:
    if not name:
        return "未命名"
    return re.sub(r'[<>:"/\\|?*]', "_", str(name)).strip()


def export_summary_reports(df: pd.DataFrame, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)

    all_report = output_dir / "合同汇总总表_v5.xlsx"
    review_report = output_dir / "待人工确认_v5.xlsx"

    df.to_excel(all_report, index=False)

    review_df = df[df["是否需人工确认"] == "是"].copy()
    review_df.to_excel(review_report, index=False)


def export_group_reports(df: pd.DataFrame, output_dir: Path):
    if "所属集团" not in df.columns:
        return

    valid_df = df[
        (df["所属集团"].fillna("") != "") &
        (df["是否需人工确认"].fillna("") == "否")
    ].copy()

    if valid_df.empty:
        return

    # 新格式列映射：DataFrame列名 → 汇总表显示列名
    NEW_FORMAT_COLS = {
        "识别年份": "年份",
        "标准公司名": "公司名称",
        "合同类型": "合同类型",
        "签字时间": "合同日期/有效期",
        "年度维护费": "年度维护金额（元）",
        "原文件名": "文件名",
    }

    for group_name, group_df in valid_df.groupby("所属集团"):
        group_dir = output_dir / safe_folder_name(str(group_name))
        group_dir.mkdir(parents=True, exist_ok=True)

        # 新格式集团汇总表（只保留目标列，按年份排序）
        available_cols = [c for c in NEW_FORMAT_COLS if c in group_df.columns]
        new_fmt_df = group_df[available_cols].rename(columns=NEW_FORMAT_COLS).copy()
        new_fmt_df = new_fmt_df.sort_values("年份", na_position="last")
        new_fmt_df["备注"] = ""   # 空列留给人工填写
        new_fmt_df.to_excel(group_dir / "集团汇总表.xlsx", index=False)

        # 保留原始全字段表供审核
        group_df.to_excel(group_dir / "集团汇总表_详细.xlsx", index=False)
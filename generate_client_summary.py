"""
客户合同年度汇总报告生成器
筛选规则：
  维护合同 = doc_type=CONTRACT，文件名含维护合同/维护服务合同/合作协议/服务协议/服务合同
  SRF      = doc_type=SRF，全部
  采购合同 = 文件名含"采购合同"或"购买合同"（客户发来的采购订单不含）
用法：python generate_client_summary.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

AUDIT_PATH  = Path("output/audit.jsonl")
OUTPUT_BASE = Path("output")

# ── 分类规则 ──────────────────────────────────────────────
MAINTENANCE_NAME_KEYWORDS = [
    "维护合同", "维护服务合同", "合作协议", "服务协议", "服务合同",
]
PURCHASE_NAME_KEYWORDS = ["采购合同", "购买合同"]
PROJECT_NAME_KEYWORDS = ["项目合同"]
UPGRADE_NAME_KEYWORDS = ["升级"]

def classify(record: dict) -> str | None:
    """返回分类名称，不属于五类则返回 None。"""
    fn = record.get("file_name", "")
    dt = record.get("doc_type", "")

    # 升级合同：文件名含"升级"（优先判断，避免被其他规则截获）
    if any(kw in fn for kw in UPGRADE_NAME_KEYWORDS):
        return "升级合同"

    # 采购合同：文件名关键词（购买合同/采购合同）
    if any(kw in fn for kw in PURCHASE_NAME_KEYWORDS):
        return "采购合同"

    # 项目合同：文件名关键词
    if any(kw in fn for kw in PROJECT_NAME_KEYWORDS):
        return "项目合同"

    # SRF：doc_type 判断
    if dt == "SRF":
        return "SRF"

    # 维护合同：doc_type=CONTRACT + 文件名关键词
    if dt == "CONTRACT" and any(kw in fn for kw in MAINTENANCE_NAME_KEYWORDS):
        return "维护合同"

    return None  # 不在五类中，跳过


# ── 金额选取 ──────────────────────────────────────────────
AMOUNT_PRIORITY = [
    ("annual_maintenance_fee", "年度维护费"),
    ("tax_excluded_amount",    "不含税金额"),
    ("tax_included_amount",    "含税金额"),
    ("contract_total_amount",  "合同总额"),
]

def best_amount(record: dict) -> tuple[float | None, str]:
    """返回 (金额, 来源字段说明)。"""
    for field, label in AMOUNT_PRIORITY:
        val = record.get(field)
        if val:
            return float(val), label
    return None, ""


# ── 文件路径格式化 ─────────────────────────────────────────
def short_path(record: dict) -> str:
    """返回 /年份/文件名 格式。"""
    year = infer_year(record)
    fn = record.get("file_name", "")
    year_str = str(year) if year else "未知年份"
    return f"/{year_str}/{fn}"


# ── 服务期从文件名解析 ────────────────────────────────────
import re as _re
from datetime import date as _date

_DATE_PATTERNS = [
    # 20110201至20120131 / 20161111-20171110
    _re.compile(r"(20\d{2})(\d{2})(\d{2})[至\-~](20\d{2})(\d{2})(\d{2})"),
    # 2013年4月1日至2014年3月31日
    _re.compile(r"(20\d{2})年(\d{1,2})月(\d{1,2})日?[至\-~到](20\d{2})年(\d{1,2})月(\d{1,2})日?"),
    # 2015.7.1-2016.6.30  /  2015.7.1至2016.6.30  /  2022.01.01_2023.12.31
    _re.compile(r"(20\d{2})[._](\d{1,2})[._](\d{1,2})[至\-~_](20\d{2})[._](\d{1,2})[._](\d{1,2})"),
]

def _parse_period_from_filename(fn: str):
    """从文件名提取 (start_date, end_date) 或 (None, None)。"""
    for pat in _DATE_PATTERNS:
        m = pat.search(fn)
        if m:
            try:
                y1,m1,d1,y2,m2,d2 = (int(x) for x in m.groups())
                return _date(y1,m1,d1), _date(y2,m2,d2)
            except ValueError:
                continue
    return None, None

def _period_label(start: _date, end: _date) -> str:
    """根据时长返回'一年'/'两年'/'X个月'等描述。"""
    days = (end - start).days
    if days >= 700:
        years = round(days / 365)
        return f"{years}年"
    if days >= 335:
        return "一年"
    months = round(days / 30)
    return f"{months}个月"


# ── 版本号提取 ───────────────────────────────────────────
# 版本格式：Formware/Formare/FW + 数字，或数字紧跟"升级"/"版本"
# FW50→5.0, FW40→4.0, FW70→7.0（两位数字，十位是主版本，个位次版本）
_VERSION_PATTERNS = [
    # Formware6.0 / Formare 5.0 / FW7.0
    _re.compile(r"[Ff](?:ormwa?re?|W)\s*(\d+\.\d+)", _re.IGNORECASE),
    # FW50 / FW40 / FW70（两位，无小数点）→ 格式化为 X.Y
    _re.compile(r"\bFW(\d{2})\b", _re.IGNORECASE),
    # 数字.数字 紧跟"升级"/"版本"，如 财务8.0升级
    _re.compile(r"(\d+\.\d+)(?=升级|版本)"),
]

_YEAR_FROM_FN = _re.compile(r"(20\d{2})")

def infer_year(record: dict) -> int | None:
    """report_year 为空时从文件名提取第一个 20xx 年份作为兜底。"""
    yr = record.get("report_year")
    if yr:
        return yr
    fn = record.get("file_name", "")
    m = _YEAR_FROM_FN.search(fn)
    return int(m.group(1)) if m else None


def extract_version(fn: str) -> str:
    """从文件名提取软件版本号；无法识别则返回空串。"""
    for i, pat in enumerate(_VERSION_PATTERNS):
        m = pat.search(fn)
        if m:
            ver = m.group(1)
            if i == 1:  # FW50 → "5.0"
                ver = f"{ver[0]}.{ver[1]}"
            return ver
    return ""


# ── 摘要处理 ──────────────────────────────────────────────
_SRF_SERVICE_KEYWORDS = [
    ("实施", "系统实施"),
    ("开发", "软件开发"),
    ("培训", "培训服务"),
    ("升级", "系统升级"),
    ("迁移", "系统迁移"),
    ("维护", "系统维护"),
]

def format_summary(record: dict, cat: str) -> str:
    """返回清理后的摘要：去掉 [派克集团] 前缀；SRF 补充服务类型/编号/服务期。"""
    raw = record.get("summary", "") or ""
    # 去掉 [XXX] 前缀（如 [派克集团]）
    import re as _re
    summary = _re.sub(r"^\[[^\]]+\]\s*", "", raw).strip()

    if cat in ("维护合同", "项目合同", "升级合同"):
        fn = record.get("file_name", "")
        # 优先用 record 里的服务期，否则从文件名解析
        sp = service_period(record)
        start_d, end_d = (None, None)
        if not sp:
            start_d, end_d = _parse_period_from_filename(fn)
            if start_d and end_d:
                sp = f"{start_d} ~ {end_d}"
        else:
            # 尝试解析已有服务期字符串
            m = _re.search(r"(20\d{2}-\d{2}-\d{2})\s*~\s*(20\d{2}-\d{2}-\d{2})", sp)
            if m:
                try:
                    start_d = _date.fromisoformat(m.group(1))
                    end_d   = _date.fromisoformat(m.group(2))
                except ValueError:
                    pass

        duration = _period_label(start_d, end_d) if start_d and end_d else ""
        parts = []
        if duration:
            parts.append(f"{duration}合同")
        # 只在原摘要里没有服务期信息时才追加
        if sp and "服务期" not in summary and "至" not in summary:
            parts.append(f"维护期 {sp}")
        if parts:
            return f"{summary}（{'；'.join(parts)}）"
        return summary

    if cat == "SRF":
        fn = record.get("file_name", "")
        # 从文件名推断服务类型
        service_type = "服务"
        for kw, label in _SRF_SERVICE_KEYWORDS:
            if kw in fn:
                service_type = label
                break

        # srf_number may be at top-level or nested in fields dict
        srf_no = record.get("srf_number", "")
        if not srf_no:
            fields_dict = record.get("fields", {})
            srf_field = fields_dict.get("srf_number", {})
            srf_no = (srf_field.get("value", "") if isinstance(srf_field, dict) else srf_field) or ""
        # Reject OCR-misread values: SRF numbers are short (≤30 chars) and mostly ASCII/digits
        if srf_no and (len(srf_no) > 30 or _re.search(r"[\u4e00-\u9fa5]{3,}", srf_no)):
            srf_no = ""
        sp = service_period(record)

        parts = [service_type]
        if srf_no:
            parts.append(f"编号 {srf_no}")
        if sp:
            parts.append(f"服务期 {sp}")
        if summary:
            # 保留原摘要中公司+年份部分，附加服务详情
            return f"{summary}（{'；'.join(parts)}）"
        return "；".join(parts)

    return summary


# ── 服务期格式化 ──────────────────────────────────────────
def _get_field(record: dict, key: str) -> str:
    """Get a field value from top-level or nested fields dict."""
    val = record.get(key, "")
    if not val:
        fd = record.get("fields", {}).get(key, {})
        val = (fd.get("value", "") if isinstance(fd, dict) else fd) or ""
    return str(val) if val else ""


def service_period(record: dict) -> str:
    start = _get_field(record, "service_period_start")
    end   = _get_field(record, "service_period_end")
    if start and end:
        return f"{start} ~ {end}"
    if start:
        return f"{start} ~"
    if end:
        return f"~ {end}"
    return ""


# ── 主流程 ───────────────────────────────────────────────
EXCLUDE_DOC_TYPES = {"UNKNOWN", "OTHER", "ATTACHMENT", "PAYMENT_NOTICE", "PROPOSAL"}
EXCLUDE_GROUPS = {"内部文件"}

def load_records() -> list[dict]:
    seen: set[str] = set()
    records = []
    with open(AUDIT_PATH, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            fn = r.get("file_name", "")
            if fn in seen:
                continue
            seen.add(fn)
            # 过滤掉非合同类文件
            if r.get("doc_type", "UNKNOWN") in EXCLUDE_DOC_TYPES:
                continue
            records.append(r)
    return records


def build_rows(records: list[dict]) -> list[dict]:
    rows = []
    for r in records:
        cat = classify(r)
        if cat is None:
            continue

        amt, amt_src = best_amount(r)
        year = infer_year(r)

        # 有问题的标记
        bad_flags = [
            f for f in r.get("flags", [])
            if "amount_invalid" in f or "company_invalid" in f
        ]
        note = "; ".join(bad_flags) if bad_flags else ""

        rows.append({
            "年份":     year,
            "合同类型":  cat,
            "合同方":    r.get("detected_company", ""),
            "金额":      amt,
            "币种":      r.get("currency") or "CNY",
            "金额类型":  amt_src,
            "服务期":    service_period(r),
            "版本号":    (r.get("software_version", "")
                         or _get_field(r, "software_version")
                         or extract_version(r.get("file_name", ""))),
            "摘要":      format_summary(r, cat),
            "文件路径":  short_path(r),
            "备注":      note,   # 内部用，不写入 Excel
        })

    # 年份升序，同年按合同类型、合同方排序
    rows.sort(key=lambda x: (x["年份"] or 0, x["合同类型"], x["合同方"] or ""))
    return rows


def build_summary(rows: list[dict]) -> list[dict]:
    """按年份 × 合同类型汇总金额。"""
    from collections import defaultdict
    data: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    for r in rows:
        year = r["年份"] or 0
        cat  = r["合同类型"]
        if r["金额"]:
            data[year][cat].append(r["金额"])

    summary = []
    for year in sorted(data.keys()):
        entry = {"年份": year if year else "未知"}
        cats = data[year]
        for cat in ["维护合同", "SRF", "采购合同", "项目合同", "升级合同"]:
            amounts = cats.get(cat, [])
            entry[f"{cat}_笔数"] = len(amounts)
            entry[f"{cat}_总额"] = sum(amounts) if amounts else None
        entry["合计"] = sum(
            v for k, v in entry.items()
            if k.endswith("总额") and v is not None
        ) or None
        summary.append(entry)

    return summary


EXCEL_COLUMNS = ["年份", "合同类型", "合同方", "金额", "币种", "金额类型", "服务期", "版本号", "摘要", "文件路径"]

def write_excel(rows: list[dict], group: str) -> None:
    out_path = OUTPUT_BASE / group / f"{group}_合同汇总.xlsx"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df_detail = pd.DataFrame(rows)[EXCEL_COLUMNS]

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df_detail.to_excel(writer, sheet_name="合同明细", index=False)

        ws = writer.sheets["合同明细"]
        for col_idx, col in enumerate(df_detail.columns, 1):
            col_letter = ws.cell(1, col_idx).column_letter
            max_len = max(
                len(str(col)),
                (df_detail[col].astype(str).str.len().max() if len(df_detail) else 0),
            )
            ws.column_dimensions[col_letter].width = min(max_len + 2, 45)

    print(f"已生成: {out_path}")


def process_group(group: str, records: list[dict]) -> None:
    """为单个集团生成汇总表并打印控制台摘要。"""
    group_records = [r for r in records if r.get("detected_group") == group]
    rows = build_rows(group_records)
    if not rows:
        print(f"[跳过] {group}：无符合条件的合同")
        return

    summary = build_summary(rows)
    write_excel(rows, group)

    # 控制台预览
    from collections import Counter
    type_counts = Counter(r["合同类型"] for r in rows)
    print(f"  筛选结果：" + "  ".join(f"{k} {v}条" for k, v in type_counts.items()))

    def fmt(v): return f"{v:>12,.0f}" if v else f"{'—':>12}"
    print(f"\n  {'年份':>6}  {'维护合同':>12}  {'SRF':>10}  {'采购合同':>12}  {'合计':>12}")
    print("  " + "-" * 58)
    for s in summary:
        print(f"  {str(s['年份']):>6}  {fmt(s.get('维护合同_总额'))}  "
              f"{fmt(s.get('SRF_总额')):>10}  "
              f"{fmt(s.get('采购合同_总额'))}  {fmt(s.get('合计'))}")

    no_amt = [r for r in rows if not r["金额"]]
    if no_amt:
        print(f"\n  [!] {len(no_amt)} 条无金额：")
        for r in no_amt:
            print(f"    {r['文件路径']}")

    flagged = [r for r in rows if r["备注"]]
    if flagged:
        print(f"\n  [!] {len(flagged)} 条存在识别问题：")
        for r in flagged:
            print(f"    {r['文件路径']}  金额={r['金额']}  ({r['备注'][:60]})")


def main() -> None:
    records = load_records()

    # 按集团分组，过滤掉"未分组"和"内部文件"
    groups = sorted({r.get("detected_group", "") for r in records
                     if r.get("detected_group")
                     and r.get("detected_group") not in ("未分组", *EXCLUDE_GROUPS)})

    print(f"共发现 {len(groups)} 个集团：{', '.join(groups)}\n")
    for group in groups:
        print(f"=== {group} ===")
        process_group(group, records)
        print()


if __name__ == "__main__":
    main()

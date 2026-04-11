"""Entry point for the Contract Sorter system.

Can be run as:
    python src/main.py [command] [options]
    python -m src.main [command] [options]
"""
from __future__ import annotations

# NOTE: The old main.py has been replaced by the new CLI-based entry point.
# Use: python src/main.py run --input ... --output ...
# Or:  python -m src.cli run ...

from src.cli import cli

if __name__ == "__main__":
    cli()

# Legacy placeholder to prevent import errors if old code references this module
import re
import json
from pathlib import Path

import fitz
import pandas as pd
from PIL import Image
from pdf2image import convert_from_path

from mapper import (
    build_company_aliases_from_group_mapping,
    load_group_mapping_from_excel,
    map_company_to_group,
)
from organizer import (
    clear_runtime_folders,
    copy_to_group_folder,
    copy_to_review_folder,
    safe_folder_name,
)
from exporter import export_group_reports, export_summary_reports
from ai_extractor import extract_fields_with_ai


# ====== 路径配置 ======
BASE_DIR = Path(r"C:\LSC\contract_sorter")
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
CONFIG_DIR = BASE_DIR / "config"
REVIEW_DIR = BASE_DIR / "review"
LOGS_DIR = BASE_DIR / "logs"

POPPLER_PATH = r"C:\poppler-25.12.0\Library\bin"


# ====== 支持格式 ======
SUPPORTED_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}

# ====== 日期规则 ======
DATE_PATTERNS = [
    r"((20\d{2})[.\-/年](0?[1-9]|1[0-2])[.\-/月](0?[1-9]|[12]\d|3[01])日?)",
    r"((19\d{2})[.\-/年](0?[1-9]|1[0-2])[.\-/月](0?[1-9]|[12]\d|3[01])日?)"
]
YEAR_PATTERN = r"(19\d{2}|20\d{2})"

# ====== 固定乙方/服务商黑名单 ======
VENDOR_BLOCKLIST = [
    "上海莱升信息科技有限公司",
    "上海莱升信息科技",
    "莱升信息科技有限公司",
    "莱升信息科技",
    "泛纬软件",
    "license information technology",
    "shanghai license information technology",
    "shanghai license information technology co., ltd.",
    "license information technology co., ltd.",
    "上海菜升信息科技有限公司",
    "菜升信息科技有限公司",
    # OCR 常见误读变体（莱→跃/菜/莱斯，升→升）
    "上海跃升软件咨询有限公司",
    "跃升软件咨询",
    "上海莱升软件咨询有限公司",
    "莱升软件咨询",
    "上海莱斯软件咨询有限公司",
    "上海莱斯软件有限公司",
    "上海莱斯信息科技有限公司",
    "上海莱斯科技有限公司",
    "莱斯软件咨询",
    "莱斯软件有限公司",
    "莱斯信息科技",
    "莱斯科技有限公司",
    "莱斯电子科技有限公司",
]

# ====== 明显不是公司名的词 ======
BAD_COMPANY_EXACT = {
    "有限公司", "有限责任公司", "集团", "公司",
    "工业技术有限公司", "上海有限公司", "苏州有限公司", "深圳有限公司",
    "客户", "甲方", "乙方", "供方", "需方", "双方"
}


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\u3000", " ")
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("【", "[").replace("】", "]")
    text = text.replace("〈", "(").replace("〉", ")")
    text = text.replace("《", "").replace("》", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n+", "\n", text)
    return text.strip()


def compact_cjk_spacing(text: str) -> str:
    """
    修复 OCR 把中文拆开的情况：
    尼 得 科 仪器 ( 浙 江 ) 有 限 公 司 -> 尼得科仪器(浙江)有限公司
    """
    if not text:
        return ""

    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("〈", "(").replace("〉", ")")

    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"([\u4e00-\u9fa5])\s+([\u4e00-\u9fa5])", r"\1\2", text)
        text = re.sub(r"([\u4e00-\u9fa5])\s+([()])", r"\1\2", text)
        text = re.sub(r"([()])\s+([\u4e00-\u9fa5])", r"\1\2", text)

    text = text.replace("有 限 公 司", "有限公司")
    text = text.replace("有 限 责 任 公 司", "有限责任公司")
    text = text.replace("集 团 有 限 公 司", "集团有限公司")
    text = text.replace("集 团", "集团")
    text = text.replace("上 海", "上海")
    text = text.replace("苏 州", "苏州")
    text = text.replace("深 圳", "深圳")
    text = text.replace("浙 江", "浙江")
    text = text.replace("广 东", "广东")
    text = text.replace("无 锡", "无锡")
    text = text.replace("青 岛", "青岛")
    return text


def normalize_company_name(name: str) -> str:
    if not name:
        return ""

    name = normalize_text(name)
    name = compact_cjk_spacing(name)
    name = name.replace("（", "(").replace("）", ")")
    name = re.sub(r"\s+", "", name)

    # OCR 常见错字修正
    name = name.replace("菜升", "莱升")

    # 去掉明显业务尾巴
    tail_patterns = [
        r"[-_－—].*$",
        r"\(\d+家\)$",
        r"（\d+家）$",
        r"\(\d+\)$",
        r"（\d+）$",
        r"(维护|项目|外包|升级|SRF|报价单|合同)$",
    ]
    for p in tail_patterns:
        name = re.sub(p, "", name, flags=re.IGNORECASE)

    name = name.strip(",:：;；，。[]【】<>《》\"' ")
    name = name.strip("()")
    return name


def has_company_marker(name: str) -> bool:
    lower_name = name.lower()
    markers = [
        "有限公司", "有限责任公司", "集团有限公司", "集团", "公司",
        "co.,ltd", "co., ltd", "limited", "inc.", "llc"
    ]
    return any(m in lower_name for m in markers)


def is_bad_company_candidate(name: str) -> bool:
    if not name:
        return True

    n = normalize_company_name(name)
    lower_n = n.lower()

    if len(n) < 4:
        return True

    if n in BAD_COMPANY_EXACT:
        return True

    if re.fullmatch(r"[()（）\u4e00-\u9fa5]{0,3}(有限公司|有限责任公司|集团|公司)", n):
        return True

    for bad in VENDOR_BLOCKLIST:
        if bad.lower().replace(" ", "") in lower_n.replace(" ", ""):
            return True

    bad_fragments = [
        "服务需求表", "软件购买及服务合同", "合同双方", "一般条款",
        "地址", "联系人", "联系电话", "电话", "传真", "电子邮件",
        "softwarelicenceandserviceagreement", "servicesrequestform"
    ]
    if any(b.lower().replace(" ", "") in lower_n.replace(" ", "") for b in bad_fragments):
        return True

    return False


def contains_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fa5]", text or ""))


def dedupe_keep_order(items: list) -> list:
    result = []
    seen = set()
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def get_pdf_text_layer(pdf_path: Path, max_pages: int = 3) -> str:
    """从 PDF 文字层提取文本（数字 PDF 直接可用，扫描件返回空）"""
    text_parts = []
    try:
        doc = fitz.open(pdf_path)
        for i in range(min(len(doc), max_pages)):
            t = doc[i].get_text("text")
            if t:
                text_parts.append(t)
        doc.close()
    except Exception as e:
        print(f"  [PDF_ERROR] {e}")
    text = "\n".join(text_parts).strip()
    return compact_cjk_spacing(normalize_text(text))


def get_file_images(file_path: Path, max_pages: int = 15) -> list:
    """转换所有页（最多 max_pages），供 AI Vision 全文识别"""
    ext = file_path.suffix.lower()
    try:
        if ext == ".pdf":
            doc = fitz.open(file_path)
            total = len(doc)
            doc.close()
            return convert_from_path(
                str(file_path), first_page=1, last_page=min(total, max_pages),
                poppler_path=POPPLER_PATH, dpi=100
            )
        else:
            return [Image.open(file_path)]
    except Exception as e:
        print(f"  [IMAGE_ERROR] {e}")
        return []


def extract_candidate_dates(text: str) -> list:
    dates = []
    for pattern in DATE_PATTERNS:
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        for m in matches:
            dates.append(m[0] if isinstance(m, tuple) else m)
    return list(dict.fromkeys(dates))


def extract_year(text: str, filename: str = "") -> str:
    combined = f"{filename}\n{text}"
    dates = extract_candidate_dates(combined)
    if dates:
        m = re.search(r"(19\d{2}|20\d{2})", dates[0])
        if m:
            year = m.group(1)
            if 2000 <= int(year) <= 2035:
                return year

    years = re.findall(YEAR_PATTERN, combined)
    years = [y for y in years if 2000 <= int(y) <= 2035]
    return years[0] if years else ""


def extract_year_from_path(file_path: Path) -> str:
    """从文件所在目录名中提取年份（如 input/派克集团/2000/xxx.pdf → '2000'）"""
    for part in file_path.parts:
        if re.fullmatch(r"(19\d{2}|20\d{2})", part):
            y = int(part)
            if 2000 <= y <= 2035:
                return part
    return ""


# 用于检测 AI 将 prompt 模板原文返回的特征片段
_PROMPT_TEMPLATE_FRAGMENTS = ["不能填入", "注意：上海莱升", "乙方，不能"]


def is_ai_company_valid(name: str) -> bool:
    """返回 False 表示 AI 返回的甲方字段不可信（模板文本或乙方名称）"""
    if not name:
        return False
    # 检测是否为 prompt 模板原文
    if any(frag in name for frag in _PROMPT_TEMPLATE_FRAGMENTS):
        return False
    # 检测是否为乙方/黑名单
    if is_bad_company_candidate(name):
        return False
    return True


def extract_full_date(text: str, filename: str = "") -> str:
    combined = f"{filename}\n{text}"
    dates = extract_candidate_dates(combined)
    return dates[0] if dates else ""


def extract_signing_date(text: str, filename: str = "") -> str:
    """优先从签字/签署/日期关键词附近提取日期"""
    sign_patterns = [
        r"签(?:字|署|订)[日期]*[：:]\s*((20\d{2})[.\-/年](0?[1-9]|1[0-2])[.\-/月](0?[1-9]|[12]\d|3[01])日?)",
        r"日期[：:]\s*((20\d{2})[.\-/年](0?[1-9]|1[0-2])[.\-/月](0?[1-9]|[12]\d|3[01])日?)",
        r"Date[：:]\s*((20\d{2})[.\-/](0?[1-9]|1[0-2])[.\-/](0?[1-9]|[12]\d|3[01]))",
    ]
    for pattern in sign_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    # 兜底：取文本中第一个完整日期
    return extract_full_date(text=text, filename=filename)


def extract_contract_number(text: str, filename: str = "") -> str:
    """提取合同号"""
    patterns = [
        r"合同号[：:]\s*([A-Za-z0-9\-_(（）)\u4e00-\u9fa5]{4,40})",
        r"合同编号[：:]\s*([A-Za-z0-9\-_(（）)\u4e00-\u9fa5]{4,40})",
        r"Contract\s*No\.?[：:\s]+([A-Za-z0-9\-_()]{4,40})",
        r"编号[：:]\s*([A-Za-z0-9\-_(（）\u4e00-\u9fa5]{4,40})",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip().rstrip("，,；; ")
            if val:
                return val
    stem = Path(filename).stem if filename else ""
    m = re.search(r"([A-Za-z]+\([A-Za-z]+\)\d{6,})", stem)
    if m:
        return m.group(1)
    m = re.search(r"([A-Za-z]{2,}-\d{4}-\d{3,})", stem)
    if m:
        return m.group(1)
    return ""


def extract_installation_location(text: str) -> str:
    """提取安装地点"""
    patterns = [
        r"安装地点[：:]\s*([^\n，,]{2,40})",
        r"安装地址[：:]\s*([^\n，,]{2,40})",
        r"安装位置[：:]\s*([^\n，,]{2,40})",
        r"installation\s+(?:site|location)[：:\s]+([^\n]{2,60})",
        r"使用地点[：:]\s*([^\n，,]{2,40})",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip().rstrip("，,；;。 ")
            if val:
                return val
    return ""


def extract_software_version(text: str, filename: str = "") -> str:
    """提取软件产品及版本，如 FormWare财务 V5.1"""
    combined = f"{filename}\n{text[:1500]}"
    m = re.search(
        r"(FormWare[\u4e00-\u9fa5A-Za-z]*)\s*(V\d+\.\d+(?:\.\d+)?)",
        combined, re.IGNORECASE
    )
    if m:
        return f"{m.group(1).strip()} {m.group(2).strip()}"
    m = re.search(
        r"([\u4e00-\u9fa5A-Za-z]{2,20})\s*(V\d+\.\d+(?:\.\d+)?)",
        combined, re.IGNORECASE
    )
    if m:
        return f"{m.group(1).strip()} {m.group(2).strip()}"
    m = re.search(r"\b(V\d+\.\d+(?:\.\d+)?)\b", combined, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"版本[：:]\s*([^\n，,]{1,20})", text)
    if m:
        return m.group(1).strip()
    return ""


def extract_annual_fee(text: str) -> str:
    """提取年度维护费金额"""
    patterns = [
        r"年度维护费[：:￥¥]?\s*[￥¥]?\s*([\d,]+\.?\d*)\s*元?",
        r"年度服务费[：:￥¥]?\s*[￥¥]?\s*([\d,]+\.?\d*)\s*元?",
        r"维护费[：:]\s*[￥¥]?\s*([\d,]+\.?\d*)\s*元?",
        r"服务费[：:]\s*[￥¥]?\s*([\d,]+\.?\d*)\s*元?",
        r"年费[：:]\s*[￥¥]?\s*([\d,]+\.?\d*)\s*元?",
        r"[￥¥]\s*([\d,]+\.?\d*)\s*/?\s*年",
        r"人民币[：:\s]*([\d,]+\.?\d*)\s*元",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            val = m.group(1).replace(",", "")
            try:
                return f"{float(val):.2f}"
            except ValueError:
                return val
    return ""


def extract_doc_type(text: str, filename: str = "") -> str:
    """
    合同类型识别：
    1. 文件名优先
    2. 正文前500字优先（标题区）
    3. 全文兜底
    """
    filename_l = (filename or "").lower()
    text_l = (text or "").lower()
    head_text = text_l[:500]

    rules = [
        ("SRF", ["srf", "services request form", "服务需求表"]),
        ("报价单", ["报价单", "quotation", "quote"]),
        ("声明", ["授权声明", "声明"]),
        ("维护合同", ["维护合同", "维保合同", "维护服务合同", "年度维护服务"]),
        ("项目合同", ["项目合同", "项目协议", "项目建议书"]),
        ("服务合同", [
            "software licence and service agreement",
            "software license and service agreement",
            "service agreement",
            "服务合同",
            "技术服务合同",
            "服务协议"
        ]),
        ("采购合同", ["采购合同", "购买合同", "采购订单", "purchase agreement", "purchase order"]),
    ]

    for doc_type, keywords in rules:
        for kw in keywords:
            if kw in filename_l:
                return doc_type

    for doc_type, keywords in rules:
        for kw in keywords:
            if kw in head_text:
                return doc_type

    for doc_type, keywords in rules:
        for kw in keywords:
            if kw in text_l:
                return doc_type

    return "其他"


def extract_company_from_filename(filename: str) -> list:
    stem = Path(filename).stem
    stem = normalize_text(stem)
    stem = compact_cjk_spacing(stem)

    candidates = []
    patterns = [
        r"([A-Za-z0-9\u4e00-\u9fa5()&,\.\- ]{4,160}?有限公司)",
        r"([A-Za-z0-9\u4e00-\u9fa5()&,\.\- ]{4,160}?有限责任公司)",
        r"([A-Za-z0-9\u4e00-\u9fa5()&,\.\- ]{4,160}?集团有限公司)",
        r"([A-Za-z0-9\u4e00-\u9fa5()&,\.\- ]{4,160}?集团)",
        r"([A-Za-z0-9\u4e00-\u9fa5()&,\.\- ]{4,160}?公司)",
        r"([A-Za-z0-9\u4e00-\u9fa5()&,\.\- ]{4,180}?(?:Co\.,?\s*Ltd\.?|Limited|Inc\.?|LLC))"
    ]

    for pattern in patterns:
        matches = re.findall(pattern, stem, flags=re.IGNORECASE)
        for m in matches:
            c = normalize_company_name(m)
            if has_company_marker(c) and not is_bad_company_candidate(c):
                candidates.append(c)

    return dedupe_keep_order(candidates)


def extract_first_party_from_bilingual_contract(text: str) -> list:
    candidates = []

    m = re.search(r"BY AND BETWEEN[:：\s]*([\s\S]{0,1200})", text, flags=re.IGNORECASE)
    if not m:
        return candidates

    block = m.group(1)

    eng_matches = re.findall(
        r"([A-Za-z0-9\u4e00-\u9fa5()&,\.\- ]{4,180}?(?:Co\.,?\s*Ltd\.?|Limited|Inc\.?|LLC))",
        block,
        flags=re.IGNORECASE
    )
    for item in eng_matches:
        c = normalize_company_name(item)
        if has_company_marker(c) and not is_bad_company_candidate(c):
            candidates.append(c)

    zh_matches = re.findall(
        r"([A-Za-z0-9\u4e00-\u9fa5()·&,\-\. ]{4,160}?(?:有限公司|有限责任公司|集团有限公司|集团|公司))",
        block
    )
    for item in zh_matches:
        c = normalize_company_name(item)
        if has_company_marker(c) and not is_bad_company_candidate(c):
            candidates.append(c)

    return dedupe_keep_order(candidates)


def extract_company_by_context(text: str) -> list:
    candidates = []

    strong_patterns = [
        r"客户[：:\s]*([A-Za-z0-9\u4e00-\u9fa5()·&,\-\. ]{4,180}?(?:有限公司|有限责任公司|集团有限公司|集团|公司))",
        r"甲方[：:\s]*([A-Za-z0-9\u4e00-\u9fa5()·&,\-\. ]{4,180}?(?:有限公司|有限责任公司|集团有限公司|集团|公司))",
        r"Client[：:\s]*([A-Za-z0-9\u4e00-\u9fa5()·&,\-\. ]{4,180}?(?:Co\.,?\s*Ltd\.?|Limited|Inc\.?|LLC))",
    ]

    for pattern in strong_patterns:
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        for m in matches:
            c = normalize_company_name(m)
            if has_company_marker(c) and not is_bad_company_candidate(c):
                candidates.append(c)

    m = re.search(r"合同双方[：:\s]*([\s\S]{0,400})", text)
    if m:
        block = m.group(1)
        general = re.findall(
            r"([A-Za-z0-9\u4e00-\u9fa5()·&,\-\. ]{4,160}?(?:有限公司|有限责任公司|集团有限公司|集团|公司))",
            block
        )
        for item in general:
            c = normalize_company_name(item)
            if has_company_marker(c) and not is_bad_company_candidate(c):
                candidates.append(c)

    return dedupe_keep_order(candidates)


def extract_company_general(text: str) -> list:
    candidates = []

    patterns = [
        r"([A-Za-z0-9\u4e00-\u9fa5()·&,\-\. ]{4,160}?有限公司)",
        r"([A-Za-z0-9\u4e00-\u9fa5()·&,\-\. ]{4,160}?有限责任公司)",
        r"([A-Za-z0-9\u4e00-\u9fa5()·&,\-\. ]{4,160}?集团有限公司)",
        r"([A-Za-z0-9\u4e00-\u9fa5()·&,\-\. ]{4,160}?集团)",
        r"([A-Za-z0-9\u4e00-\u9fa5()·&,\-\. ]{4,160}?公司)",
        r"([A-Za-z0-9\u4e00-\u9fa5()·&,\-\. ]{4,180}?(?:Co\.,?\s*Ltd\.?|Limited|Inc\.?|LLC))",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        for m in matches:
            c = normalize_company_name(m)
            if has_company_marker(c) and not is_bad_company_candidate(c):
                candidates.append(c)

    return dedupe_keep_order(candidates)


def match_alias(candidate: str, company_aliases: dict) -> str:
    cand_n = normalize_company_name(candidate).lower()
    if not cand_n:
        return ""

    for standard_name, aliases in company_aliases.items():
        all_aliases = [standard_name] + aliases
        for alias in all_aliases:
            alias_n = normalize_company_name(alias).lower()
            if not alias_n:
                continue
            if cand_n == alias_n or cand_n in alias_n or alias_n in cand_n:
                return standard_name
    return ""


def prefer_chinese_name(company_name: str, matched_alias: str, company_aliases: dict, candidates: list = None):
    if not company_name:
        return company_name, matched_alias

    if contains_chinese(company_name):
        return company_name, matched_alias

    if contains_chinese(matched_alias):
        return matched_alias, matched_alias

    if candidates:
        for cand in candidates:
            if contains_chinese(cand):
                cand_n = normalize_company_name(cand).lower()
                for standard_name, aliases in company_aliases.items():
                    all_aliases = [standard_name] + aliases
                    for alias in all_aliases:
                        alias_n = normalize_company_name(alias).lower()
                        if alias_n and (cand_n == alias_n or cand_n in alias_n or alias_n in cand_n):
                            if contains_chinese(standard_name):
                                return standard_name, cand
                return cand, cand

    current_n = normalize_company_name(company_name).lower()
    for standard_name, aliases in company_aliases.items():
        all_aliases = [standard_name] + aliases
        for alias in all_aliases:
            alias_n = normalize_company_name(alias).lower()
            if alias_n and (current_n == alias_n or current_n in alias_n or alias_n in current_n):
                if contains_chinese(standard_name):
                    return standard_name, matched_alias

    return company_name, matched_alias


def find_company(text: str, filename: str, company_aliases: dict):
    """
    分层识别：
    1. 文件名 aliases
    2. 文件名直接提取
    3. BY AND BETWEEN 双语合同优先第一家
    4. 客户/甲方/Client
    5. 正文 aliases
    6. 全文一般候选
    """
    filename_n = normalize_company_name(filename).lower()
    text_n = normalize_company_name(text).lower()

    debug_candidates = []

    best_company = ""
    best_alias = ""
    best_score = 0

    for standard_name, aliases in company_aliases.items():
        all_aliases = [standard_name] + aliases
        for alias in all_aliases:
            alias_n = normalize_company_name(alias).lower()
            if not alias_n:
                continue

            score = 0
            if alias_n in filename_n:
                score += 95
            if alias_n in text_n:
                score += 70

            if any(bad.lower().replace(" ", "") in alias_n.replace(" ", "") for bad in VENDOR_BLOCKLIST):
                score -= 80

            if score > best_score:
                best_score = score
                best_company = standard_name
                best_alias = alias

    if best_company and best_score >= 75:
        return best_company, best_alias, best_score, debug_candidates

    filename_candidates = extract_company_from_filename(filename)
    debug_candidates.extend(filename_candidates)
    if filename_candidates:
        std = match_alias(filename_candidates[0], company_aliases)
        if std:
            return std, filename_candidates[0], 92, filename_candidates
        return filename_candidates[0], filename_candidates[0], 88, filename_candidates

    bilingual_candidates = extract_first_party_from_bilingual_contract(text)
    debug_candidates.extend(bilingual_candidates)
    if bilingual_candidates:
        for cand in bilingual_candidates:
            std = match_alias(cand, company_aliases)
            if std:
                return std, cand, 90, bilingual_candidates
        return bilingual_candidates[0], bilingual_candidates[0], 84, bilingual_candidates

    context_candidates = extract_company_by_context(text)
    debug_candidates.extend(context_candidates)
    if context_candidates:
        for cand in context_candidates:
            std = match_alias(cand, company_aliases)
            if std:
                return std, cand, 86, context_candidates
        return context_candidates[0], context_candidates[0], 80, context_candidates

    best_company = ""
    best_alias = ""
    best_score = 0
    for standard_name, aliases in company_aliases.items():
        all_aliases = [standard_name] + aliases
        for alias in all_aliases:
            alias_n = normalize_company_name(alias).lower()
            if not alias_n:
                continue

            score = 0
            if alias_n in text_n:
                score += 72

            if any(bad.lower().replace(" ", "") in alias_n.replace(" ", "") for bad in VENDOR_BLOCKLIST):
                score -= 80

            if score > best_score:
                best_score = score
                best_company = standard_name
                best_alias = alias

    if best_company and best_score >= 50:
        return best_company, best_alias, best_score, debug_candidates

    general_candidates = extract_company_general(text)
    debug_candidates.extend(general_candidates)
    if general_candidates:
        for cand in general_candidates:
            std = match_alias(cand, company_aliases)
            if std:
                return std, cand, 68, general_candidates
        return general_candidates[0], general_candidates[0], 60, general_candidates

    return "", "", 0, debug_candidates


def build_confidence(company_score: int, year: str, full_date: str, doc_type: str, group_name: str) -> int:
    score = min(company_score, 90)
    if year:
        score += 5
    if full_date:
        score += 3
    if doc_type != "其他":
        score += 2
    if group_name:
        score += 3
    return min(score, 100)


def get_review_reason(company_name: str, group_name: str, year: str, confidence: int, text: str) -> str:
    reasons = []

    if not company_name:
        reasons.append("未识别公司名")
    if company_name and not group_name:
        reasons.append("未匹配到集团")
    if not year:
        reasons.append("未识别年份")
    if confidence < 78:
        reasons.append("置信度偏低")
    if not text or text.startswith("[") or len(text.strip()) < 20:
        reasons.append("文本提取不足")

    return "；".join(reasons)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    group_mapping = load_group_mapping_from_excel(
        CONFIG_DIR / "group_company_mapping_clean.xlsx",
        sheet_name="mapping_clean"
    )
    company_aliases = build_company_aliases_from_group_mapping(group_mapping)

    clear_runtime_folders(OUTPUT_DIR, REVIEW_DIR)

    rows = []
    files = [p for p in INPUT_DIR.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS]

    print(f"找到文件数量: {len(files)}")

    for idx, file_path in enumerate(files, start=1):
        print(f"[{idx}/{len(files)}] 处理中: {file_path.name}")

        filename = file_path.name
        rel_path = str(file_path.relative_to(INPUT_DIR))
        ext = file_path.suffix.lower()

        # ── 1. 尝试读取文字层（数字 PDF 直接用，扫描件为空）──
        text = get_pdf_text_layer(file_path) if ext == ".pdf" else ""
        use_ai = len(text.strip()) < 200

        # ── 2. 文字层不足时，调 GPT-4o-mini Vision ──
        ai_fields = {}
        if use_ai:
            images = get_file_images(file_path)
            if images:
                print(f"  → 调用 AI Vision 识别")
                ai_fields = extract_fields_with_ai(images, filename)

        # ── 3. 公司识别 ──
        raw_ai_company = ai_fields.get("甲方", "").strip()
        if raw_ai_company and is_ai_company_valid(raw_ai_company):
            std = match_alias(raw_ai_company, company_aliases)
            company_name = std if std else raw_ai_company
            matched_alias = raw_ai_company
            company_score = 85
            company_candidates = [raw_ai_company]
        else:
            if raw_ai_company and not is_ai_company_valid(raw_ai_company):
                print(f"  [AI_COMPANY_SKIP] AI 返回无效甲方，回退到文件名识别: {raw_ai_company[:40]}")
            company_name, matched_alias, company_score, company_candidates = find_company(
                text=text, filename=filename, company_aliases=company_aliases
            )
            company_name, matched_alias = prefer_chinese_name(
                company_name=company_name,
                matched_alias=matched_alias,
                company_aliases=company_aliases,
                candidates=company_candidates
            )

        group_name = map_company_to_group(company_name, group_mapping) if company_name else ""

        # ── 4. 其他字段：AI 优先，回退到正则 ──
        if ai_fields:
            signing_date  = str(ai_fields.get("签字时间") or "").strip()
            contract_no   = str(ai_fields.get("合同号") or "").strip()
            install_location = str(ai_fields.get("安装地点") or "").strip()
            software_version = str(ai_fields.get("版本") or "").strip()
            annual_fee    = str(ai_fields.get("年度维护费") or "").strip()
            # 文件名优先，文件名不明确再用 AI，最后兜底正文
            doc_type = extract_doc_type(text="", filename=filename)
            if doc_type == "其他":
                doc_type = str(ai_fields.get("合同类型") or "其他").strip()
            if doc_type == "其他":
                doc_type = extract_doc_type(text=text, filename=filename)
            full_date     = signing_date
            # 文件名年份优先，AI 年份兜底
            year = (extract_year(text="", filename=filename)
                    or str(ai_fields.get("年份") or "").strip())
        else:
            year             = extract_year(text=text, filename=filename)
            full_date        = extract_full_date(text=text, filename=filename)
            signing_date     = extract_signing_date(text=text, filename=filename)
            contract_no      = extract_contract_number(text=text, filename=filename)
            install_location = extract_installation_location(text=text)
            software_version = extract_software_version(text=text, filename=filename)
            annual_fee       = extract_annual_fee(text=text)
            doc_type         = extract_doc_type(text=text, filename=filename)

        confidence = build_confidence(company_score, year, full_date, doc_type, group_name)
        review_reason = get_review_reason(company_name, group_name, year, confidence, text)
        manual_review = "是" if review_reason else "否"

        if group_name and year and manual_review == "否":
            actual_output_path = copy_to_group_folder(
                output_dir=OUTPUT_DIR,
                src_file=file_path,
                group_name=group_name,
                year=year
            )
        else:
            actual_output_path = copy_to_review_folder(
                review_dir=REVIEW_DIR,
                src_file=file_path
            )

        rows.append({
            "序号": idx,
            "原文件名": filename,
            "相对路径": rel_path,
            "识别公司名": matched_alias,
            "标准公司名": company_name,
            "所属集团": group_name,
            "候选公司名列表": " | ".join(company_candidates[:10]),
            "识别年份": year,
            "合同日期": full_date,
            "签字时间": signing_date,
            "合同号": contract_no,
            "安装地点": install_location,
            "版本": software_version,
            "年度维护费": annual_fee,
            "合同类型": doc_type,
            "实际输出路径": actual_output_path,
            "置信度": confidence,
            "是否需人工确认": manual_review,
            "待复核原因": review_reason,
            "OCR文本前500字": text[:500]
        })

    df = pd.DataFrame(rows)

    if df.empty:
        print("没有找到可处理文件。")
        return

    export_summary_reports(df, OUTPUT_DIR)
    export_group_reports(df, OUTPUT_DIR)

    print(f"\n已输出总表和集团汇总表到: {OUTPUT_DIR}")
    print(f"待复核文件夹: {REVIEW_DIR}")
    print("完成。")


if __name__ == "__main__":
    main()
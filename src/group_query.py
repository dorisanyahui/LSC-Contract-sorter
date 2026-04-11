"""
group_query.py
--------------
使用方式：python src/group_query.py
1. 显示集团列表，让用户选择目标集团
2. 只处理该集团旗下公司的文件
3. 输出三个 Excel：
   - 集团汇总表（新格式：年份/合同号/甲方/安装地点/版本/签字时间/年度维护费/文件名）
   - 汇总总表（原格式，供审核）
   - 待人工确认（供审核）
"""

import hashlib
import re
import shutil
import sys
import time
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
from ai_extractor import extract_fields_with_ai

# ====== 路径配置 ======
BASE_DIR = Path(r"C:\LSC\contract_sorter")
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
CONFIG_DIR = BASE_DIR / "config"

POPPLER_PATH = r"C:\poppler-25.12.0\Library\bin"

SUPPORTED_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}

DATE_PATTERNS = [
    r"((20\d{2})[.\-/年](0?[1-9]|1[0-2])[.\-/月](0?[1-9]|[12]\d|3[01])日?)",
    r"((19\d{2})[.\-/年](0?[1-9]|1[0-2])[.\-/月](0?[1-9]|[12]\d|3[01])日?)"
]
YEAR_PATTERN = r"(19\d{2}|20\d{2})"

VENDOR_BLOCKLIST = [
    "上海莱升信息科技有限公司", "上海莱升信息科技", "莱升信息科技有限公司",
    "莱升信息科技", "泛纬软件",
    "license information technology",
    "shanghai license information technology",
    "shanghai license information technology co., ltd.",
    "license information technology co., ltd.",
    "上海菜升信息科技有限公司", "菜升信息科技有限公司",
    # OCR 常见误读变体（莱→跃/菜，新→斯）
    "上海跃升软件咨询有限公司", "跃升软件咨询",
    "上海莱升软件咨询有限公司", "莱升软件咨询",
    "上海莱斯软件咨询有限公司", "上海莱斯软件有限公司",
    "上海莱斯信息科技有限公司", "上海莱斯科技有限公司",
    "莱斯软件咨询", "莱斯软件有限公司",
    "莱斯信息科技", "莱斯科技有限公司", "莱斯电子科技有限公司",
]

BAD_COMPANY_EXACT = {
    "有限公司", "有限责任公司", "集团", "公司",
    "工业技术有限公司", "上海有限公司", "苏州有限公司", "深圳有限公司",
    "客户", "甲方", "乙方", "供方", "需方", "双方"
}


# ===================================================================
# 文本清洗
# ===================================================================

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\u3000", " ")
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("【", "[").replace("】", "]")
    text = text.replace("《", "").replace("》", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n+", "\n", text)
    return text.strip()


def compact_cjk_spacing(text: str) -> str:
    if not text:
        return ""
    text = text.replace("（", "(").replace("）", ")")
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"([\u4e00-\u9fa5])\s+([\u4e00-\u9fa5])", r"\1\2", text)
        text = re.sub(r"([\u4e00-\u9fa5])\s+([()])", r"\1\2", text)
        text = re.sub(r"([()])\s+([\u4e00-\u9fa5])", r"\1\2", text)
    for pair in [("有 限 公 司", "有限公司"), ("有 限 责 任 公 司", "有限责任公司"),
                 ("集 团 有 限 公 司", "集团有限公司"), ("集 团", "集团"),
                 ("上 海", "上海"), ("苏 州", "苏州"), ("深 圳", "深圳"),
                 ("浙 江", "浙江"), ("广 东", "广东"), ("无 锡", "无锡"), ("青 岛", "青岛")]:
        text = text.replace(pair[0], pair[1])
    return text


def normalize_company_name(name: str) -> str:
    if not name:
        return ""
    name = normalize_text(name)
    name = compact_cjk_spacing(name)
    name = name.replace("（", "(").replace("）", ")")
    name = re.sub(r"\s+", "", name)
    name = name.replace("菜升", "莱升")
    tail_patterns = [
        r"[-_－—].*$", r"\(\d+家\)$", r"（\d+家）$",
        r"\(\d+\)$", r"（\d+）$",
        r"(维护|项目|外包|升级|SRF|报价单|合同)$",
    ]
    for p in tail_patterns:
        name = re.sub(p, "", name, flags=re.IGNORECASE)
    name = name.strip(",:：;；，。[]【】<>《》\"' ")
    name = name.strip("()")
    return name


def has_company_marker(name: str) -> bool:
    lower_name = name.lower()
    return any(m in lower_name for m in [
        "有限公司", "有限责任公司", "集团有限公司", "集团", "公司",
        "co.,ltd", "co., ltd", "limited", "inc.", "llc"
    ])


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
    result, seen = [], set()
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


# ===================================================================
# 合同类型识别
# ===================================================================

def extract_doc_type(text: str, filename: str = "") -> str:
    """文件名优先，正文兜底识别合同类型"""
    filename_l = (filename or "").lower()
    text_l = (text or "").lower()
    head_text = text_l[:500]

    rules = [
        ("SRF",    ["srf", "services request form", "服务需求表"]),
        ("报价单",  ["报价单", "quotation", "quote"]),
        ("维护合同", ["维护合同", "维保合同", "维护服务合同", "年度维护服务"]),
        ("项目合同", ["项目合同", "项目协议", "项目建议书"]),
        ("服务合同", ["software licence and service agreement",
                    "software license and service agreement",
                    "service agreement", "服务合同", "技术服务合同", "服务协议"]),
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


# ===================================================================
# OCR / 文本提取
# ===================================================================

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
    return compact_cjk_spacing(normalize_text("\n".join(text_parts).strip()))


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


# ===================================================================
# 基础字段提取（年份、日期）
# ===================================================================

def extract_candidate_dates(text: str) -> list:
    dates = []
    for pattern in DATE_PATTERNS:
        for m in re.findall(pattern, text, flags=re.IGNORECASE):
            dates.append(m[0] if isinstance(m, tuple) else m)
    return list(dict.fromkeys(dates))


def extract_year(text: str, filename: str = "") -> str:
    combined = f"{filename}\n{text}"
    dates = extract_candidate_dates(combined)
    if dates:
        m = re.search(r"(19\d{2}|20\d{2})", dates[0])
        if m and 2000 <= int(m.group(1)) <= 2035:
            return m.group(1)
    years = [y for y in re.findall(YEAR_PATTERN, combined) if 2000 <= int(y) <= 2035]
    return years[0] if years else ""


def extract_year_from_path(file_path: Path) -> str:
    """从文件所在目录名中提取年份（如 input/派克集团/2000/xxx.pdf → '2000'）"""
    for part in file_path.parts:
        if re.fullmatch(r"(19\d{2}|20\d{2})", part):
            y = int(part)
            if 2000 <= y <= 2035:
                return part
    return ""


_PROMPT_TEMPLATE_FRAGMENTS = ["不能填入", "注意：上海莱升", "乙方，不能"]


def is_ai_company_valid(name: str) -> bool:
    """返回 False 表示 AI 返回的甲方字段不可信（模板文本或乙方名称）"""
    if not name:
        return False
    if any(frag in name for frag in _PROMPT_TEMPLATE_FRAGMENTS):
        return False
    if is_bad_company_candidate(name):
        return False
    return True


def extract_signing_date(text: str, filename: str = "") -> str:
    """优先从正文签署栏提取签字日期"""
    sign_patterns = [
        r"签(?:字|署|订)[日期]*[：:]\s*((20\d{2})[.\-/年](0?[1-9]|1[0-2])[.\-/月](0?[1-9]|[12]\d|3[01])日?)",
        r"日期[：:]\s*((20\d{2})[.\-/年](0?[1-9]|1[0-2])[.\-/月](0?[1-9]|[12]\d|3[01])日?)",
        r"Date[：:]\s*((20\d{2})[.\-/\-](0?[1-9]|1[0-2])[.\-/\-](0?[1-9]|[12]\d|3[01]))",
    ]
    for pattern in sign_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()

    # 兜底：取文本中第一个完整日期
    combined = f"{filename}\n{text}"
    dates = extract_candidate_dates(combined)
    return dates[0] if dates else ""


# ===================================================================
# 新增字段提取
# ===================================================================

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

    # 从文件名中寻找类似 "Sandvik(SH)20210201" 的编码
    stem = Path(filename).stem if filename else ""
    # 模式：字母+(括号字母)+数字8位以上
    m = re.search(r"([A-Za-z]+\([A-Za-z]+\)\d{6,})", stem)
    if m:
        return m.group(1)
    # 模式：纯字母数字编号，如 LSC-2024-001
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

    # 优先：产品名 + 版本号连在一起
    m = re.search(
        r"(FormWare[\u4e00-\u9fa5A-Za-z]*)\s*(V\d+\.\d+(?:\.\d+)?)",
        combined, re.IGNORECASE
    )
    if m:
        return f"{m.group(1).strip()} {m.group(2).strip()}"

    # 通用：中文产品名 + 版本号
    m = re.search(
        r"([\u4e00-\u9fa5A-Za-z]{2,20})\s*(V\d+\.\d+(?:\.\d+)?)",
        combined, re.IGNORECASE
    )
    if m:
        return f"{m.group(1).strip()} {m.group(2).strip()}"

    # 版本号单独出现
    m = re.search(r"\b(V\d+\.\d+(?:\.\d+)?)\b", combined, re.IGNORECASE)
    if m:
        return m.group(1)

    # 版本字段
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


# ===================================================================
# 公司识别（精简版，直接用别名表匹配）
# ===================================================================

def extract_company_from_filename(filename: str) -> list:
    stem = Path(filename).stem
    stem = compact_cjk_spacing(normalize_text(stem))
    candidates = []
    patterns = [
        r"([A-Za-z0-9\u4e00-\u9fa5()&,\.\- ]{4,160}?有限公司)",
        r"([A-Za-z0-9\u4e00-\u9fa5()&,\.\- ]{4,160}?有限责任公司)",
        r"([A-Za-z0-9\u4e00-\u9fa5()&,\.\- ]{4,160}?集团)",
        r"([A-Za-z0-9\u4e00-\u9fa5()&,\.\- ]{4,180}?(?:Co\.,?\s*Ltd\.?|Limited|Inc\.?|LLC))"
    ]
    for pattern in patterns:
        for m in re.findall(pattern, stem, flags=re.IGNORECASE):
            c = normalize_company_name(m)
            if has_company_marker(c) and not is_bad_company_candidate(c):
                candidates.append(c)
    return dedupe_keep_order(candidates)


def extract_company_by_context(text: str) -> list:
    candidates = []
    strong_patterns = [
        r"客户[：:\s]*([A-Za-z0-9\u4e00-\u9fa5()·&,\-\. ]{4,180}?(?:有限公司|有限责任公司|集团|公司))",
        r"甲方[：:\s]*([A-Za-z0-9\u4e00-\u9fa5()·&,\-\. ]{4,180}?(?:有限公司|有限责任公司|集团|公司))",
        r"Client[：:\s]*([A-Za-z0-9\u4e00-\u9fa5()·&,\-\. ]{4,180}?(?:Co\.,?\s*Ltd\.?|Limited|Inc\.?|LLC))",
    ]
    for pattern in strong_patterns:
        for m in re.findall(pattern, text, flags=re.IGNORECASE):
            c = normalize_company_name(m)
            if has_company_marker(c) and not is_bad_company_candidate(c):
                candidates.append(c)
    return dedupe_keep_order(candidates)


def match_alias(candidate: str, company_aliases: dict) -> str:
    cand_n = normalize_company_name(candidate).lower()
    if not cand_n:
        return ""
    for std_name, aliases in company_aliases.items():
        for alias in [std_name] + aliases:
            alias_n = normalize_company_name(alias).lower()
            if alias_n and (cand_n == alias_n or cand_n in alias_n or alias_n in cand_n):
                return std_name
    return ""


def find_company_for_group(text: str, filename: str, company_aliases: dict):
    """简化版公司识别，专用于单集团查询"""
    # 文件名用原始 stem（不做裁剪），避免 _ 截断导致漏匹配
    from pathlib import Path as _Path
    stem_raw = _Path(filename).stem.lower().replace("（", "(").replace("）", ")")
    text_n = normalize_company_name(text).lower()

    # 1. alias 直接命中（文件名 > 全文）
    best_company, best_alias, best_score = "", "", 0
    for std_name, aliases in company_aliases.items():
        for alias in [std_name] + aliases:
            alias_n = normalize_company_name(alias).lower()
            if not alias_n:
                continue
            score = 0
            if alias_n in stem_raw:
                score += 95
            elif alias_n in text_n:
                score += 70
            if any(bad.lower().replace(" ", "") in alias_n.replace(" ", "")
                   for bad in VENDOR_BLOCKLIST):
                score -= 80
            if score > best_score:
                best_score, best_company, best_alias = score, std_name, alias

    if best_company and best_score >= 70:
        return best_company, best_alias, best_score

    # 2. 文件名直接提取（含公司标记）
    fn_candidates = extract_company_from_filename(filename)
    if fn_candidates:
        return fn_candidates[0], fn_candidates[0], 80

    # 3. 上下文
    ctx_candidates = extract_company_by_context(text)
    if ctx_candidates:
        return ctx_candidates[0], ctx_candidates[0], 70

    # 4. 文件名分段模糊匹配：stem 中的片段若是某公司名的前缀（简称），也认为命中
    stem_parts = [p for p in re.split(r'[_\s\-·]+', _Path(filename).stem) if len(p) >= 4]
    for part in stem_parts:
        part_l = part.lower().replace("（", "(").replace("）", ")")
        if any(bad.lower().replace(" ", "") in part_l.replace(" ", "") for bad in VENDOR_BLOCKLIST):
            continue
        for std_name, aliases in company_aliases.items():
            all_names = [std_name] + aliases
            for cn in all_names:
                cn_l = normalize_company_name(cn).lower()
                if cn_l and part_l in cn_l and len(part_l) >= 4:
                    return std_name, part, 60

    return "", "", 0


# ===================================================================
# 主流程
# ===================================================================

def select_group(group_mapping: dict) -> str:
    all_groups = sorted(group_mapping.keys())

    print("\n===== 已加载集团列表 =====")
    for i, g in enumerate(all_groups, 1):
        company_count = len(group_mapping[g].get("companies", []))
        print(f"  {i:>3}. {g}  ({company_count} 家公司)")
    print("=" * 30)

    while True:
        raw = input("\n请输入集团名称或序号：").strip()
        if not raw:
            continue

        # 输入序号
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(all_groups):
                return all_groups[idx]
            print(f"序号超出范围，请输入 1~{len(all_groups)}")
            continue

        # 精确匹配
        if raw in group_mapping:
            return raw

        # 模糊匹配
        matches = [g for g in all_groups if raw in g or g in raw]
        if len(matches) == 1:
            print(f"  → 已匹配到：{matches[0]}")
            return matches[0]
        if len(matches) > 1:
            print(f"  找到多个匹配：{matches}")
            print("  请输入更精确的名称")
            continue

        print(f"  未找到「{raw}」，请重新输入")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 加载集团映射
    group_mapping = load_group_mapping_from_excel(
        CONFIG_DIR / "group_company_mapping_clean.xlsx",
        sheet_name="mapping_clean"
    )

    # 选择集团
    target_group = select_group(group_mapping)
    group_info = group_mapping[target_group]
    companies = group_info.get("companies", [])
    aliases = group_info.get("aliases", [])

    print(f"\n目标集团：【{target_group}】")
    print(f"旗下公司（{len(companies)} 家）：")
    for c in companies:
        print(f"  - {c}")

    # 只为这个集团构建 alias 表
    single_group_mapping = {target_group: group_info}
    company_aliases = build_company_aliases_from_group_mapping(single_group_mapping)

    safe_group = re.sub(r'[<>:"/\\|?*]', "_", target_group).strip()

    all_files = [p for p in INPUT_DIR.rglob("*")
                 if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS]
    print(f"\n输入文件总数：{len(all_files)}")
    print("开始处理...\n")

    rows = []
    for idx, file_path in enumerate(all_files, 1):
        filename = file_path.name
        ext = file_path.suffix.lower()
        print(f"[{idx}/{len(all_files)}] {filename}")

        # ── 1. 尝试文字层，不足则调 AI Vision ──
        text = get_pdf_text_layer(file_path) if ext == ".pdf" else ""
        use_ai = len(text.strip()) < 200

        ai_fields = {}
        if use_ai:
            images = get_file_images(file_path)
            if images:
                print(f"  → 调用 AI Vision 识别")
                ai_fields = extract_fields_with_ai(images, filename)

        # ── 2. 公司识别 ──
        raw_ai_company = ai_fields.get("甲方", "").strip()
        if raw_ai_company and is_ai_company_valid(raw_ai_company):
            std = match_alias(raw_ai_company, company_aliases)
            company_name = std if std else raw_ai_company
            matched_alias = raw_ai_company
            company_score = 85
        else:
            if raw_ai_company and not is_ai_company_valid(raw_ai_company):
                print(f"  [AI_COMPANY_SKIP] AI 返回无效甲方，回退到文件名识别: {raw_ai_company[:40]}")
            company_name, matched_alias, company_score = find_company_for_group(
                text=text, filename=filename, company_aliases=company_aliases
            )

        group_name = map_company_to_group(company_name, group_mapping) if company_name else ""

        # ── 3. 其他字段：AI 优先，回退到正则 ──
        if ai_fields:
            signing_date  = str(ai_fields.get("签字时间") or "").strip()
            maintenance_period = str(ai_fields.get("维护期间") or "").strip()
            # 有维护期就填维护期，否则填签字日期
            date_display  = maintenance_period or signing_date
            # 文件名优先，文件名不明确再用 AI，最后兜底正文
            doc_type = extract_doc_type(text="", filename=filename)
            if doc_type == "其他":
                doc_type = str(ai_fields.get("合同类型") or "其他").strip()
            if doc_type == "其他":
                doc_type = extract_doc_type(text=text, filename=filename)
            fee      = str(ai_fields.get("年度维护费") or "").strip()
            tax_rate = str(ai_fields.get("税率") or "").strip()
            if tax_rate and not tax_rate.endswith("%"):
                tax_rate = tax_rate + "%"
            tax_incl = str(ai_fields.get("含税金额") or "").strip()
            # 组合金额：能区分含税/不含税就都写，否则只写金额
            if tax_rate and tax_incl and tax_incl != fee and fee:
                annual_fee = f"不含税:{fee} / 税率:{tax_rate} / 含税:{tax_incl}"
            elif tax_rate and fee:
                annual_fee = f"{fee}（税率{tax_rate}）"
            else:
                annual_fee = tax_incl or fee
            # 文件名年份优先，AI 年份兜底
            year = (extract_year(text="", filename=filename)
                    or str(ai_fields.get("年份") or "").strip())
        else:
            year               = extract_year(text=text, filename=filename)
            signing_date       = extract_signing_date(text=text, filename=filename)
            maintenance_period = ""
            date_display       = signing_date
            doc_type           = extract_doc_type(text=text, filename=filename)
            annual_fee         = extract_annual_fee(text=text)
            tax_rate, tax_incl = "", ""

        # ── 4. 归档判断 ──
        review_reasons = []
        if not company_name:
            review_reasons.append("未识别公司名")
        if company_name and group_name != target_group:
            review_reasons.append(f"未匹配到目标集团（识别为：{group_name or '未知'}）")
        if not year:
            review_reasons.append("未识别年份")
        if company_score < 70 and group_name != target_group:
            review_reasons.append("置信度偏低")

        review_reason = "；".join(review_reasons)
        manual_review = "是" if review_reasons else "否"

        # ── 5. 文件归档 ──
        src_hash = hashlib.md5(file_path.read_bytes()).hexdigest()

        def copy_if_new(src: Path, dst_dir: Path) -> None:
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / src.name
            counter = 1
            while dst.exists():
                if hashlib.md5(dst.read_bytes()).hexdigest() == src_hash:
                    return  # 内容相同，跳过
                dst = dst_dir / f"{src.stem}_{counter}{src.suffix}"
                counter += 1
            shutil.copy2(src, dst)

        if manual_review == "否":
            copy_if_new(file_path, OUTPUT_DIR / safe_group / str(year))
        else:
            copy_if_new(file_path, BASE_DIR / "review" / safe_group)

        rows.append({
            "年份":            year,
            "公司名称":         company_name if contains_chinese(company_name) else (matched_alias or company_name),
            "合同类型":         doc_type,
            "合同日期/有效期":   date_display,
            "年度维护金额（元）": annual_fee,
            "税率":             tax_rate if ai_fields else "",
            "含税金额（元）":    tax_incl if ai_fields else "",
            "文件名":           filename,
            "摘要":             str(ai_fields.get("摘要") or "").strip() if ai_fields else "",
            "备注":             "",
            # 审核用字段
            "所属集团":         group_name,
            "置信度":           company_score,
            "是否需人工确认":    manual_review,
            "待复核原因":        review_reason,
        })

    df = pd.DataFrame(rows)

    if df.empty:
        print("\n未找到任何可处理文件。")
        return

    group_out_dir = OUTPUT_DIR / safe_group
    group_out_dir.mkdir(parents=True, exist_ok=True)

    SUMMARY_COLS  = ["年份", "公司名称", "合同类型", "合同日期/有效期",
                     "年度维护金额（元）", "税率", "含税金额（元）", "文件名", "摘要", "备注"]
    REVIEW_COLS   = SUMMARY_COLS + ["所属集团", "置信度", "是否需人工确认", "待复核原因"]

    # ── 集团汇总表（仅已确认文件，按年份排序）──
    matched_df = df[df["是否需人工确认"] == "否"][SUMMARY_COLS].sort_values("年份").copy()
    group_report = group_out_dir / f"{safe_group}_集团汇总表.xlsx"
    matched_df.to_excel(group_report, index=False)
    print(f"\n集团汇总表（{len(matched_df)} 条）：{group_report}")

    # ── 汇总总表（所有文件，含审核字段）──
    summary_report = group_out_dir / f"{safe_group}_汇总总表.xlsx"
    df[REVIEW_COLS].to_excel(summary_report, index=False)
    print(f"汇总总表（{len(df)} 条）：{summary_report}")

    # ── 待人工确认 ──
    review_df = df[df["是否需人工确认"] == "是"][REVIEW_COLS].copy()
    review_report = group_out_dir / f"{safe_group}_待人工确认.xlsx"
    review_df.to_excel(review_report, index=False)
    print(f"待人工确认（{len(review_df)} 条）：{review_report}")

    print(f"\n完成！输出目录：{group_out_dir}")


if __name__ == "__main__":
    main()

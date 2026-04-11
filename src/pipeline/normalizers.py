from __future__ import annotations

import re
from datetime import date

from src.models.enums import DocType


# City names commonly found in Chinese company names
_CITY_PREFIXES = [
    "上海", "北京", "广州", "深圳", "天津", "重庆", "成都", "武汉", "杭州",
    "南京", "西安", "苏州", "青岛", "大连", "宁波", "无锡", "厦门", "福州",
    "济南", "郑州", "长沙", "合肥", "哈尔滨", "沈阳", "昆明", "太原", "石家庄",
    "南昌", "南宁", "贵阳", "乌鲁木齐", "呼和浩特", "拉萨", "银川", "西宁",
    "兰州", "长春", "吉林", "唐山", "保定", "秦皇岛", "邯郸", "廊坊",
    "烟台", "威海", "临沂", "淄博", "潍坊", "东莞", "佛山", "珠海",
    "中山", "汕头", "江门", "惠州", "湛江", "温州", "绍兴", "嘉兴",
    "金华", "台州", "常州", "南通", "徐州", "盐城", "扬州", "镇江",
    "泰州", "淮安", "连云港", "芜湖", "蚌埠", "淮南", "马鞍山", "安庆",
    "黄山", "滁州", "阜阳", "宿州", "六安", "宣城", "铜陵", "池州",
    "亳州", "泉州", "漳州", "三明", "莆田", "南平", "龙岩", "宁德",
    "赣州", "吉安", "上饶", "抚州", "宜春", "景德镇", "萍乡", "新余",
    "鹰潭", "九江", "洛阳", "开封", "安阳", "新乡", "焦作", "鹤壁",
    "濮阳", "许昌", "漯河", "三门峡", "南阳", "商丘", "信阳", "周口",
    "驻马店", "黄石", "宜昌", "襄阳", "荆州", "荆门", "鄂州", "孝感",
    "黄冈", "咸宁", "随州", "十堰", "恩施", "仙桃", "天门", "潜江",
    "株洲", "湘潭", "衡阳", "邵阳", "岳阳", "常德", "张家界", "益阳",
    "郴州", "永州", "怀化", "娄底", "湘西",
]


def strip_city(name: str) -> str:
    """Remove city prefix or bracketed city suffix from a company name.

    Examples:
        青岛派克汉尼汾流体连接件有限公司 -> 派克汉尼汾流体连接件有限公司
        派克汉尼汾流体连接件(青岛)有限公司 -> 派克汉尼汾流体连接件有限公司
    """
    if not name:
        return name

    # Remove bracketed city: (城市) or （城市）
    for city in _CITY_PREFIXES:
        name = re.sub(rf"[（(]{re.escape(city)}[)）]", "", name)

    # Remove leading city prefix
    for city in _CITY_PREFIXES:
        if name.startswith(city):
            candidate = name[len(city):]
            # Only strip if what remains is still a valid company name (4+ chars)
            if len(candidate) >= 4:
                name = candidate
                break

    return name.strip()


def normalize_company_name(name: str) -> str:
    """Standardize a company name: strip city, normalize brackets."""
    if not name:
        return name

    # Normalize brackets
    name = name.replace("（", "(").replace("）", ")")

    # Strip city prefix/suffix
    name = strip_city(name)

    # Remove extra whitespace
    name = re.sub(r"\s+", " ", name).strip()

    return name


def normalize_date_str(date_obj: date | str | None) -> str:
    """Convert a date to YYYY-MM-DD string format."""
    if date_obj is None:
        return ""
    if isinstance(date_obj, str):
        from src.utils.date_utils import parse_date
        parsed = parse_date(date_obj)
        if parsed:
            return parsed.isoformat()
        return date_obj
    return date_obj.isoformat()


def normalize_tax_rate(s: str) -> str:
    """Normalize a tax rate string to ensure % suffix.

    Examples:
        "13" -> "13%"
        "0.13" -> "13%"
        "13%" -> "13%"
    """
    if not s:
        return ""

    s = s.strip()

    # Already has % suffix
    if s.endswith("%"):
        # Check if it's a decimal like 0.13%
        val_str = s[:-1]
        try:
            val = float(val_str)
            if val < 1.0:
                val = val * 100
            return f"{val:g}%"
        except ValueError:
            return s

    # No % suffix
    try:
        val = float(s)
        if val < 1.0:
            val = val * 100
        return f"{val:g}%"
    except ValueError:
        return s


def normalize_doc_type(s: str) -> DocType:
    """Map a Chinese or English string (or enum name) to a DocType enum value."""
    if not s:
        return DocType.UNKNOWN

    # Direct enum name match (e.g. "PURCHASE_ORDER" from settings.yaml keys)
    try:
        return DocType[s.upper().strip()]
    except KeyError:
        pass

    s_lower = s.lower().strip()

    mappings = {
        DocType.CONTRACT: ["合同", "协议", "agreement", "contract", "服务合同", "维护合同", "维保合同", "项目合同"],
        DocType.PURCHASE_ORDER: ["采购合同", "采购订单", "购买合同", "purchase order", "订购单", "采购单"],
        DocType.QUOTE: ["报价单", "报价书", "quotation", "quote"],
        DocType.PROPOSAL: ["项目建议书", "建议书", "proposal", "方案建议"],
        DocType.SRF: ["srf", "服务需求表", "service request"],
        DocType.PAYMENT_NOTICE: ["付款通知", "催款", "payment notice", "invoice"],
        DocType.ATTACHMENT: ["附件", "附录", "attachment", "appendix"],
        DocType.OTHER: ["声明", "工作报告", "交付报告", "承诺书", "statement", "report", "delivery report"],
    }

    for doc_type, keywords in mappings.items():
        for kw in keywords:
            if kw in s_lower:
                return doc_type

    return DocType.UNKNOWN

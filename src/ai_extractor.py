"""
ai_extractor.py
---------------
用 GPT-4o-mini Vision 从合同图片中提取结构化字段。
需要设置环境变量 OPENAI_API_KEY。
"""

import base64
import io
import json
import re
import time

from openai import OpenAI
from PIL import Image


# ── TPM 速率限制器 ──────────────────────────────────────────────────
# DPI=100 的 A4 页面约 1160×820px，detail="auto" 时约 6 tile = 1105 token/页
# 200K TPM 限额留 25% 缓冲，实际使用 150K
_TPM_BUDGET      = 170_000  # 200K 限额留 15% 缓冲
_TOKENS_PER_PAGE = 36_000   # DPI=100 quality=70，估算约 36K token/页（base64计入）
_tpm_window: list[tuple[float, int]] = []   # (timestamp, tokens)


def _tpm_wait(estimated_tokens: int) -> None:
    """调用前执行：若当前分钟窗口剩余 token 不足，则主动睡眠至窗口刷新。"""
    global _tpm_window
    now = time.time()
    _tpm_window = [(t, tok) for t, tok in _tpm_window if now - t < 60]
    used = sum(tok for _, tok in _tpm_window)
    if used + estimated_tokens > _TPM_BUDGET:
        if _tpm_window:
            wait = 61 - (now - _tpm_window[0][0])
            if wait > 0:
                print(f"  [RATE_LIMITER] 本分钟已用 {used:,} token，预估不足，主动等待 {wait:.0f}s")
                time.sleep(wait)
    _tpm_window.append((time.time(), estimated_tokens))


EXPECTED_KEYS = {"甲方", "合同号", "签字时间", "维护期间", "年份", "安装地点", "版本", "年度维护费", "税率", "含税金额", "合同类型", "摘要"}

VALID_DOC_TYPES = {"维护合同", "服务合同", "SRF", "报价单", "采购合同", "项目合同", "其他"}

EXTRACT_PROMPT = """以下图片是同一份合同/服务文件的所有页面，由上海莱升信息科技有限公司（乙方/供方，曾用名泛纬软件/LICENSE CONSULTING）与客户（甲方）签订。

【重要规则：严禁猜测或推断】
- 所有字段只能填写你在图片中能清晰、明确看到的内容
- 任何数字（金额、税率、日期）若图片中不清晰或无法确认，必须填 null，绝对不允许猜测
- 不允许根据上下文推算金额，只填文档中明文出现的数字
- 宁可填 null 也不填错误数据

请逐页仔细阅读，重点关注：
- 第1页：甲方公司名称、合同编号
- 中间页：服务内容、软件版本、金额（注意可能出现在报价表、费用条款、项目列表等位置）
- 最后几页：签字页/盖章页上的签字时间（手写日期）、合同金额

提取以下字段，严格以JSON格式返回，不要输出任何其他文字：

{
  "甲方": "客户/购买方公司全称。注意：上海莱升、莱升信息科技、泛纬软件、LSC、LICENSE 是乙方，绝对不能填入。若无法识别则填 null",
  "合同号": "合同编号。若无则填 null",
  "签字时间": "合同签署日期，优先从签字页/盖章页的手写日期提取（通常在最后几页），格式 YYYY-MM-DD。文件名中的日期也可作为参考。若无法识别则填 null",
  "维护期间": "软件维护或服务的有效期区间，如 '2021-01-01 至 2021-12-31' 或 '2021.01-2021.12'。维护合同/服务合同通常有此字段。若文件名中有维护期信息也可提取。若无则填 null",
  "年份": "合同签署年份，4位数字。从签字时间提取或从文件名提取。若无法识别则填 null",
  "安装地点": "软件安装或服务地点。若无则填 null",
  "版本": "软件产品名称及版本号，如 FormWare财务 V5.1。若无则填 null",
  "年度维护费": "合同不含税金额或税前服务费（人民币，仅填纯数字，如 29800）。请查看所有页面包括费用条款和报价页。若只有含税金额则填含税金额。若无则填 null",
  "税率": "增值税税率，如 13%、6%、16%。若文件中明确标注税率则填写，否则填 null",
  "含税金额": "含税总金额（人民币，仅填纯数字）。重要：只有文件中明确写出含税金额时才填，若文件仅标注不含税金额（如'不含13%税金'），此字段必须填 null，不可填入不含税金额。若无则填 null",
  "合同类型": "从以下选一个：维护合同 / 服务合同 / SRF / 报价单 / 采购合同 / 项目合同 / 其他",
  "摘要": "简要概括合同核心内容，包括：年份、甲方名称、服务/产品内容、所有金额（若有多笔如购买费+维护费则均列出）。例如：'2021年莱升为派克汉尼汾工程材料提供FormWare V5.0软件购买及维护服务，购买费29800元，年度维护费8000元。'金额/年份若无法识别可省略。不超过100字。若文件无法识别则填 null"
}"""


def _to_base64_jpeg(img: Image.Image) -> str:
    buf = io.BytesIO()
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=70)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _parse_json(raw: str) -> dict:
    """从 AI 回复中安全解析 JSON，兼容 markdown 代码块格式"""
    # 去掉 markdown 代码块包裹
    raw = re.sub(r"```(?:json)?\s*", "", raw).strip()
    # 找最外层的 { ... }（非贪婪，取第一个完整对象）
    depth, start = 0, -1
    for i, ch in enumerate(raw):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start != -1:
                try:
                    return json.loads(raw[start:i + 1])
                except json.JSONDecodeError:
                    return {}
    return {}


def extract_fields_with_ai(images: list, filename: str = "", retries: int = 5) -> dict:
    """
    将合同页面图片发给 GPT-4o-mini，返回结构化字段字典。
    返回键：甲方 / 合同号 / 签字时间 / 年份 / 安装地点 / 版本 / 年度维护费 / 合同类型
    失败时返回空字典 {}
    """
    if not images:
        return {}

    client = OpenAI(timeout=60)

    content = []
    if filename:
        content.append({"type": "text", "text": f"文件名：{filename}"})
    for img in images:
        b64 = _to_base64_jpeg(img)
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "auto"}
        })
    content.append({"type": "text", "text": EXTRACT_PROMPT})

    # 调用前主动限速：估算本次 token 用量，不足则等待
    estimated_tokens = len(images) * _TOKENS_PER_PAGE
    _tpm_wait(estimated_tokens)

    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=700,
                temperature=0,
                messages=[{"role": "user", "content": content}]
            )
            # 用 API 返回的实际 token 数替换估算值，提高后续限速精度
            actual_tokens = getattr(response.usage, "total_tokens", estimated_tokens)
            _tpm_window[-1] = (time.time(), actual_tokens)
            print(f"  [TOKEN] {filename}: 实际消耗 {actual_tokens:,} token")

            raw = response.choices[0].message.content.strip()
            result = _parse_json(raw)

            if not result:
                print(f"  [AI_WARN] {filename}: 无法解析JSON，原始回复: {raw[:100]}")
                continue

            # 补全缺失字段、清理 null 值（含 AI 返回字符串 "null"/"None"）
            cleaned = {}
            for key in EXPECTED_KEYS:
                val = result.get(key)
                val_str = "" if val is None else str(val).strip()
                cleaned[key] = "" if val_str.lower() in ("null", "none", "nan") else val_str

            # 合同类型校验，非法值归为"其他"
            if cleaned.get("合同类型") not in VALID_DOC_TYPES:
                cleaned["合同类型"] = "其他"

            return cleaned

        except Exception as e:
            err_str = str(e)
            # 429 限速：从错误信息提取等待时间，兜底等 10 秒
            if "429" in err_str or "rate_limit" in err_str.lower():
                wait_match = re.search(r"try again in (\d+(?:\.\d+)?)s", err_str)
                wait_sec = float(wait_match.group(1)) + 1 if wait_match else 10
                if attempt < retries - 1:
                    print(f"  [AI_RATE_LIMIT] {filename}: 限速，等待 {wait_sec:.0f}s 后重试")
                    time.sleep(wait_sec)
                else:
                    print(f"  [AI_FAILED] {filename}: 限速重试耗尽，将跳过AI识别，仅用文件名兜底")
            elif attempt < retries - 1:
                print(f"  [AI_RETRY {attempt+1}] {filename}: {e}")
                time.sleep(2 ** attempt)
            else:
                print(f"  [AI_FAILED] {filename}: {e}")

    return {}

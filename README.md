# Contract Sorter — 企业合同自动归档系统

将历史扫描合同（PDF/图片）按集团和年份自动分类归档，使用 PaddleOCR + GPT-4o 识别字段，生成 Excel 汇总表。

---

## 架构

```
src/
├── cli.py                    Click CLI 入口
├── main.py                   Python 模块入口
├── config.py                 配置加载（settings.yaml）
│
├── models/
│   ├── enums.py              DocType, PageType, FieldSource 等枚举
│   └── schema.py             Pydantic v2 数据模型
│
├── pipeline/
│   ├── pdf_router.py         PDF 文字层分析
│   ├── ocr_pipeline.py       PaddleOCR 处理（含缓存）
│   ├── page_classifier.py    页面分类（签名页/金额页/条款页等）
│   ├── packetizer.py         文档拆包（一个 PDF 可含多个子文档）
│   ├── candidate_builder.py  候选字段提取
│   ├── validators.py         字段验证
│   ├── normalizers.py        字段标准化（城市名/日期/税率等）
│   ├── ai_resolver.py        AI 调解冲突字段
│   ├── summarizer.py         摘要生成
│   └── ingest.py             主处理流水线
│
├── extractors/
│   ├── base.py               抽象基类
│   ├── contract_extractor.py 服务/维护合同
│   ├── purchase_order_extractor.py 采购订单
│   ├── quote_extractor.py    报价单
│   ├── proposal_extractor.py 建议书
│   ├── srf_extractor.py      服务需求表
│   ├── payment_notice_extractor.py 付款通知
│   ├── attachment_extractor.py 附件
│   └── unknown_extractor.py  未知类型兜底
│
├── mapping/
│   ├── alias_matcher.py      rapidfuzz 模糊匹配
│   └── company_mapper.py     公司→集团映射
│
├── exporters/
│   ├── excel_exporter.py     Excel 输出
│   └── json_exporter.py      JSONL 审计输出
│
└── prompts/
    ├── classify_doc.txt      文档分类提示词
    ├── resolve_amount.txt    金额冲突解决提示词
    ├── resolve_date.txt      日期冲突解决提示词
    ├── resolve_company_role.txt 甲乙方识别提示词
    └── summarize_doc.txt     摘要生成提示词
```

---

## 安装

### 1. 创建虚拟环境

```cmd
cd C:\LSC\contract_sorter
python -m venv .venv
.venv\Scripts\activate.bat
```

### 2. 安装依赖

```cmd
pip install -r requirements.txt
```

### 3. 安装 PaddleOCR（Windows）

```cmd
pip install paddlepaddle -i https://pypi.tuna.tsinghua.edu.cn/simple
pip install paddleocr
```

首次运行时会自动下载中文模型（约 200MB）。

### 4. 配置 OpenAI API Key

```cmd
set OPENAI_API_KEY=sk-...
```

---

## 使用方法

### 全量处理

```cmd
python src/main.py run --input input/ --output output/
```

### 按集团过滤

```cmd
python src/main.py run --group "派克集团" --input input/ --output output/
```

### 调试单个文件

```cmd
python src/main.py debug-file --file "input/合同_2021.pdf"
python src/main.py debug-packet --file "input/合同_2021.pdf"
```

### 从缓存重新导出

```cmd
python src/main.py export --from-cache --output output/
python src/main.py rebuild-cache --input input/
```

---

## 配置

编辑 `config/settings.yaml`：

```yaml
base_dir: "C:/LSC/contract_sorter"
input_dir: "C:/LSC/contract_sorter/input"
output_dir: "C:/LSC/contract_sorter/output"

ocr:
  engine: paddleocr
  dpi: 200

ai:
  enabled: true
  model: gpt-4o
  tpm_budget: 80000

rules:
  amount_ranges:
    annual_maintenance_fee: [1000, 200000]
```

---

## 输出格式

```
output/
├── all_documents.xlsx
├── audit.jsonl
├── packets.xlsx
└── {集团名}/
    ├── {集团名}_汇总表.xlsx
    └── {年份}/
        └── 归档的原始 PDF
```

---

## 运行测试

```cmd
pip install pytest
python -m pytest tests/ -v
```

---

## 旧系统兼容

旧系统文件（`src/ai_extractor.py`, `src/mapper.py` 等）仍在 `src/` 目录中。新系统入口：

```cmd
python src/main.py run ...
```

---

## 功能概述

- 自动识别合同中的公司名、年份、金额、签字日期、合同类型等字段
- 将合同文件按 `output/{集团名}/{年份}/` 结构归档
- 生成三份 Excel 报表：集团汇总表、汇总总表、待人工确认表
- 支持扫描件（GPT-4o-mini Vision）和数字 PDF（PyMuPDF 文字层）
- 支持按单集团处理或全量批处理

---

## 环境要求

| 依赖 | 版本/说明 |
|------|---------|
| Python | 3.10+ |
| Poppler | `C:\poppler-25.12.0\Library\bin` |
| OpenAI API Key | GPT-4o-mini Vision |

### 安装依赖

```cmd
cd C:\LSC\contract_sorter
python -m venv .venv
.venv\Scripts\activate.bat
pip install pymupdf pandas openpyxl pdf2image pillow openai
```

---

## 目录结构

```
contract_sorter/
├── src/
│   ├── group_query.py      # 单集团交互式处理（主要入口）
│   ├── main.py             # 全量批处理入口
│   ├── ai_extractor.py     # GPT-4o-mini Vision 字段提取
│   ├── mapper.py           # 集团/公司映射逻辑
│   ├── organizer.py        # 文件归档工具
│   └── exporter.py         # Excel 报表生成
├── config/
│   └── group_company_mapping_clean.xlsx   # 集团-公司-别名映射表
├── input/                  # 待处理合同文件（支持子目录）
├── output/                 # 归档结果（按集团/年份）
└── review/                 # 需人工确认的文件
```

---

## 使用方法

### 单集团处理（推荐）

```cmd
cd C:\LSC\contract_sorter
.venv\Scripts\activate.bat
set OPENAI_API_KEY=sk-...

python src\group_query.py
```

按提示选择集团名称，程序将：
1. 扫描 `input/` 下所有文件
2. 识别属于该集团的合同
3. 归档到 `output/{集团名}/{年份}/`
4. 生成三份 Excel 到 `output/{集团名}/`

### 全量批处理

```cmd
python src\main.py
```

---

## 输出 Excel 格式

| 列名 | 说明 |
|------|------|
| 年份 | 合同签署年份 |
| 公司名称 | 甲方公司全称 |
| 合同类型 | 维护合同/服务合同/采购合同/报价单/SRF/项目合同 |
| 合同日期/有效期 | 有维护期则显示维护期区间，否则显示签字日期 |
| 年度维护金额（元） | 含税率信息（如有），例：`29800（税率13%）` |
| 税率 | 增值税税率（如 13%） |
| 含税金额（元） | 含税总金额 |
| 文件名 | 原始文件名 |
| 摘要 | AI 生成的一句话摘要 |
| 备注 | 人工备注（留空） |

---

## 字段提取优先级

| 字段 | 优先级 |
|------|--------|
| 合同类型 | 文件名关键词 → AI识别 → 正文内容 |
| 年份 | 文件名日期 → AI识别 |
| 公司名称 | AI识别（验证非乙方）→ 文件名提取 |
| 金额/日期 | AI Vision 全文识别 |

---

## 配置说明

### 集团映射表 `config/group_company_mapping_clean.xlsx`

Sheet: `mapping_clean`，必须包含以下列：

| 列名 | 说明 |
|------|------|
| 名称 | 公司全称 |
| 所属集团名称 | 所属集团 |
| 简称 | 别名/简称（用于模糊匹配） |

### 路径配置（修改 `src/main.py` 和 `src/group_query.py` 顶部）

```python
BASE_DIR     = Path(r"C:\LSC\contract_sorter")
POPPLER_PATH = r"C:\poppler-25.12.0\Library\bin"
```

---

## 注意事项

- 重新跑之前建议清空 `output/` 和 `review/`（程序有 MD5 去重，不会复制重复文件）
- AI 识别需要 `OPENAI_API_KEY` 环境变量
- 扫描件质量差（空白页/损坏）时自动跳过 AI，仅用文件名提取
- 限速（429）会自动等待重试，每次成功调用后有 3 秒冷却间隔

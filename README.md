# Contract Sorter — 企业合同自动归档系统

将上海莱升信息科技有限公司（曾用名：泛纬软件）20 年间（2004-2025）的历史扫描合同（PDF/图片）按客户集团和签订年份自动分类归档，使用 **GPT-4o-mini Vision** OCR 提取字段，生成 Excel 汇总表。

当前状态：**3,459 条记录 / 190+ 集团 / 金额覆盖率 93.1%**，详见 [CLAUDE.md](./CLAUDE.md) 的更新记录章节。

---

## 快速开始

```powershell
cd C:\LSC\contract_sorter
.venv\Scripts\Activate.ps1

# 首次配置（或每次新开 PowerShell）
$env:OPENAI_API_KEY = "sk-你的key"

# 全量处理
python -m src.main run

# 生成客户合同汇总表
python generate_client_summary.py

# 调试单个文件
python -m src.main debug-file --file "input\某文件.pdf"
```

> ⚠️ 必须用 `python -m src.main run`，直接 `python src\main.py` 会报 `ModuleNotFoundError`。

---

## 架构

```
src/pipeline/ingest.py          主流程入口
      │
      ├── pdf_router.py          检测是否有文字层
      ├── ocr_pipeline.py        OCR 引擎（GPT-4o-mini Vision）
      ├── page_classifier.py     页面分类
      ├── packetizer.py          文档拆包（一个 PDF 可含多个子文档）
      ├── extractors/            字段提取器（按文档类型）
      │     ├── contract_extractor.py
      │     ├── srf_extractor.py
      │     ├── quote_extractor.py
      │     └── purchase_order_extractor.py
      ├── mapping/company_mapper.py   公司→集团映射（含模糊匹配和城市名归一）
      ├── validators.py          字段验证
      ├── normalizers.py         字段规范化
      └── exporters/             Excel + JSONL 审计输出

generate_client_summary.py      每个集团生成一份客户合同汇总 Excel
verify_summaries.py             全量校验（金额/摘要/集团匹配/乙方）
```

有文字层的 PDF 直接用 PyMuPDF 提取文本，跳过 OCR；扫描件才发给 GPT Vision。

---

## 字段提取优先级

| 字段 | 优先级（高→低） |
|------|----------------|
| 合同类型 | 文件名关键词 → 正文正则 |
| 年份 | 文件名日期 → OCR 文本 → 文件名首个年份兜底 → 父目录名（"纸质合同扫描件 YYYY"）|
| 公司名称 | OCR 提取（验证非乙方）→ 文件名提取 |
| 金额/日期/维护期 | 规则提取器（带置信度打分） |
| 软件版本 | OCR 正则（"版本：V5.1"）→ 文件名正则 |

乙方黑名单（`src/mapping/company_mapper.py` 的 `VENDOR_BLOCKLIST`）会过滤 OCR 误读的莱升/跃升/莱斯/泛纬等变体，防止回填成甲方。

---

## 输出结构

```
output/
├── audit.jsonl                 所有文件提取结果（汇总脚本的数据源）
├── audit_fixed.jsonl           备份副本
└── {集团名}/
    ├── {年份}/                 归档的原始 PDF（按签订年份分组）
    ├── {集团名}_汇总表.xlsx    pipeline 自动生成
    └── {集团名}_合同汇总.xlsx  客户合同汇总表（按合同类型分类）
```

合同类型分 5 类（优先级从高到低）：**升级合同 / 采购合同 / 项目合同 / SRF / 维护合同**。

---

## 安装

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

主要依赖：`pymupdf` · `pandas` · `openpyxl` · `pillow` · `openai` · `loguru`

环境变量：
```powershell
$env:OPENAI_API_KEY = "sk-..."
# 永久保存
[System.Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "sk-...", "User")
```

---

## 数据修复工具箱

根目录下有一批一次性修复脚本（`fix_*.py` / `extract_*.py` / `normalize_*.py`），记录了历次数据清洗的完整过程：

| 脚本 | 用途 |
|------|------|
| `fix_year_mismatches.py` | 批量修复 audit 年份与文件名不符（273 条 OCR 年份错误） |
| `fix_vendor_ocr_typos.py` | 修复 OCR 将乙方"莱升"误读为"跃升/莱斯"导致的客户名错误 |
| `extract_missing_amounts.py` | 用 GPT Vision 扫描无金额 PDF，两轮提取（页 1-3 + 深扫 4-6） |
| `extract_amounts_pass2.py` | 二轮扫描：修复 evidence_mismatch + 深扫页 4-6 |
| `apply_extracted_amounts.py` | 合并 pass1/pass2 结果并写回 audit.jsonl |
| `normalize_groups.py` | 集团名称规范化合并（如"亨斯"→"亨斯迈"） |
| `fix_other_groups*.py` | 从"其他"集团提取记录到正确集团 |
| `reorganize_folders*.py` | 文件夹重命名/合并/PDF 移动 |
| `verify_summaries.py` | 全量校验金额/摘要/集团匹配/乙方（推荐每次修复后运行） |

历史修复的完整日志见 [CLAUDE.md](./CLAUDE.md) 底部的"更新记录"章节。

---

## 开发规范

见 [CLAUDE.md](./CLAUDE.md) —— 每次修改代码后必须：
1. 自己运行验证（`python -m src.main debug-file ...` 或 `python generate_client_summary.py`）再告知用户
2. 在 CLAUDE.md 底部补充一条更新记录

修改 audit.jsonl 后**必须**同步复制到 audit_fixed.jsonl 保持一致，且必须跑 `verify_summaries.py`。

---

## 已知限制

| 限制 | 说明 |
|------|------|
| 手写年份不稳定 | GPT 对手写"2020"和"2021"偶有混淆，以文件名年份为准 |
| 含税/不含税无法区分 | 部分合同只列一个金额，AI 无法可靠区分 |
| TPM 限速 | 每分钟 170K token 预算，自动等待；大批量建议升级 OpenAI Tier |
| 无年份文件 | 文件名无年份且 OCR 无法识别时年份显示"未知年份" |
| 多年合同金额 | 系统记录合同总额，非年度金额，需人工判断 |

---

## 测试

```powershell
python -m pytest tests/ -v
```

覆盖：金额提取 / 日期解析 / 公司映射 / 文档分类 / 字段验证。

---

## 仓库

https://github.com/dorisanyahui/LSC-Contract-sorter

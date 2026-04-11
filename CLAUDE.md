# CLAUDE.md — Contract Sorter 项目开发指南

## 项目概述

将历史扫描合同（PDF/图片）按集团和年份自动分类归档，使用 GPT-4o-mini Vision 识别字段，生成 Excel 汇总表。乙方固定为"上海莱升信息科技有限公司"（曾用名：泛纬软件）。

---

## 开发规范（必须遵守）

1. **每次修改代码后必须自己验证结果**，再告知用户。验证方式：
   - 功能改动：运行 `python -m src.main debug-file --file "input/某文件.pdf"` 测试至少1个文件
   - 汇总脚本改动：运行 `python generate_client_summary.py` 确认无报错、输出符合预期
   - 修改提取逻辑：对比修改前后的字段值是否正确

2. **每次修改必须在本文件底部的"更新记录"章节补充一条记录**，格式：
   ```
   - YYYY-MM-DD  修改内容简述  影响文件
   ```

---

## 架构一览

```
src/pipeline/ingest.py          主流程入口（新管道）
       │
       ├── pdf_router.py         检测是否有文字层
       ├── ocr_pipeline.py       OCR 引擎（GPT-4o-mini Vision）
       ├── extractors/           字段提取器（按文档类型）
       │     ├── contract_extractor.py
       │     ├── srf_extractor.py
       │     ├── quote_extractor.py
       │     └── purchase_order_extractor.py
       ├── mapping/company_mapper.py   公司→集团映射
       ├── organizer.py          文件归档（MD5去重）
       └── exporter.py           Excel + audit.jsonl 生成

generate_client_summary.py      客户合同汇总表（每集团一份）
```

---

## 关键设计决策

### OCR 引擎

全部使用 **GPT-4o-mini Vision**（`dpi=100, detail="auto"`）：
- 扫描件无文字层 → 每页图片发给 GPT 返回文字
- 有文字层的 PDF → 直接用 PyMuPDF 提取，跳过 OCR
- 约 2000 token/页，TPM 预算 170K/分钟，自动限速等待

```python
# src/pipeline/ocr_pipeline.py
# 有文字层：src/pipeline/ingest.py 直接用 pdf_router 提取的文本
# 无文字层：_gpt_ocr_page() → GPT-4o-mini Vision
```

### 字段提取优先级

| 字段 | 优先级（高→低） |
|------|----------------|
| 合同类型 | 文件名关键词 → 正文正则 |
| 年份 | 文件名日期 → OCR文本 → 文件名首个年份兜底 |
| 公司名称 | OCR提取（验证非乙方）→ 文件名提取 |
| 金额/日期/维护期 | 规则提取器（带置信度打分） |
| 软件版本 | OCR文本正则（"版本：V5.1"）→ 文件名正则 |

### 公司名验证（防止回填乙方）

`is_ai_company_valid()` 检测并丢弃：
- VENDOR_BLOCKLIST 中的乙方名称（莱升/泛纬/LSC）
- 长度超过60字且含"注意："的 prompt 模板文字
- 长度不足4字的无效名称

### 城市名规范化匹配

`mapper.strip_city()` 处理城市位置不同导致的匹配失败：
- `青岛派克汉尼汾流体连接件有限公司` → 去城市前缀 → 匹配成功
- `派克汉尼汾流体连接件(青岛)有限公司` → 去括号城市 → 匹配成功

---

## 常见修改场景

### 新增合同类型关键词

修改 `generate_client_summary.py` 中的分类规则，以及 `src/extractors/contract_extractor.py` 的 `_extract_doc_type_from_filename()` 的 `type_hints` 字典。

### 新增乙方黑名单

修改 `src/mapping/company_mapper.py` 中的 `VENDOR_BLOCKLIST`。

### 修改汇总表分类规则

`generate_client_summary.py` 顶部的 `classify()` 函数，五个类别优先级从高到低：
1. 升级合同（文件名含"升级"）
2. 采购合同（文件名含"采购合同"/"购买合同"）
3. 项目合同（文件名含"项目合同"）
4. SRF（doc_type=SRF）
5. 维护合同（doc_type=CONTRACT + 文件名含维护/服务/合作协议等关键词）

### 修改软件版本提取规则

`src/extractors/base.py` 中的 `_extract_software_version()`，同时被 `ContractExtractor` 和 `SRFExtractor` 继承使用。

---

## 运行命令

```powershell
cd C:\LSC\contract_sorter
.venv\Scripts\Activate.ps1

# 必须先设置 OpenAI API Key（每次新开 PowerShell 都要设置，或写入系统环境变量）
$env:OPENAI_API_KEY = "sk-你的key"

# 第一步：清空旧结果
rmdir /s /q output
mkdir output

# 第二步：全量处理（将 PDF 放入 input/ 后执行）
python -m src.main run

# 第三步：生成每个集团汇总表
python generate_client_summary.py

# 调试单个文件
python -m src.main debug-file --file "input\某文件.pdf"
```

> **注意：**
> - 必须用 `python -m src.main run`，直接 `python src\main.py` 会报 `ModuleNotFoundError`
> - 必须设置 `OPENAI_API_KEY` 环境变量，否则 OCR 全部失败
> - 永久保存 key：`[System.Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "sk-你的key", "User")`

---

## 输出结构

```
output/
└── {集团名}/
    ├── {年份}/                    归档文件
    ├── {集团名}_汇总表.xlsx        自动生成（pipeline）
    └── {集团名}_合同汇总.xlsx      客户汇总表（generate_client_summary.py）

output/audit.jsonl                 所有文件提取结果（供汇总脚本使用）
```

---

## 已知限制

| 限制 | 说明 |
|------|------|
| 手写年份不稳定 | GPT 对手写"2020"和"2021"有时混淆，以文件名年份为准 |
| 含税/税前金额 | 部分合同只列一个金额，AI 无法区分 |
| TPM 限速 | 每分钟 170K token 预算，自动等待；大批量建议升级 OpenAI Tier |
| 无年份文件 | 文件名无年份且 OCR 无法识别时，年份显示"未知年份" |
| 两年合同金额 | 系统记录合同总额，非年度金额，需人工判断 |

---

## 依赖版本

```
pymupdf
pandas
openpyxl
pillow
openai
loguru
```

---

## 更新记录

- 2026-03-29  新管道（src/pipeline/）替代旧管道，OCR 引擎从 PaddleOCR 改为 GPT-4o-mini Vision  `src/pipeline/ocr_pipeline.py`
- 2026-03-29  有文字层的 PDF 跳过 OCR 直接用文字层  `src/pipeline/ingest.py`
- 2026-03-29  新增 software_version 字段提取（正则匹配"版本：V5.x"）  `src/extractors/base.py`, `src/models/schema.py`, `src/pipeline/ingest.py`
- 2026-03-29  generate_client_summary.py 支持所有集团（按 detected_group 分组，每集团生成一份 Excel）
- 2026-03-29  汇总表新增：升级合同、项目合同两个类别；摘要去掉集团前缀；SRF 摘要补充服务类型/编号/服务期；维护合同摘要补充维护期和合同时长
- 2026-03-29  修复 report_year 为空时从文件名兜底提取年份（infer_year）
- 2026-03-29  修复 备注 字段从 Excel 列移除但 console 输出仍引用导致 KeyError 的 bug
- 2026-04-03  新增 validate_and_fix.py 校验流程：自动修复乙方误识别/关于前缀/噪音公司名，无映射公司归入"其他"  `validate_and_fix.py`
- 2026-04-03  generate_client_summary.py 过滤 UNKNOWN/OTHER/内部文档类型，过滤"内部文件"/"上海莱升"集团  `generate_client_summary.py`
- 2026-04-03  mapping 新增15个公司（罗门哈斯/日本电产/奇美材料/艾美仕/松下天津等）  `config/group_company_mapping_clean.xlsx`
- 2026-04-03  新增 OCR 引擎选择（settings.yaml engine: gpt/paddleocr）  `src/pipeline/ocr_pipeline.py`, `config/settings.yaml`
- 2026-04-03  修复 _build_keyword_map 中 "-legris"/"(685)" 等内部编码阻止法律后缀识别，导致"产品有限公司"成为派克集团关键词，75条英特尔/爱普生/西门子等记录被误归到派克集团  `src/mapping/company_mapper.py`
- 2026-04-03  validate_and_fix.py 新增：问题4c 公司名无法验证当前集团时重置为"其他"，问题4b 补充文件名兜底映射  `validate_and_fix.py`
- 2026-04-03  mapping 新增 27 条（锐科独立集团、英特尔、爱普生、汉斯格雅、安迪苏、珀金埃尔OCR变体、琉璃工房、摩恩厨房变体、西门子医疗）；上海挪威→DNV  `config/group_company_mapping_clean.xlsx`
- 2026-04-05  大规模集团归属修正：330条记录从"其他"分类到正确集团（派克/泰科/西门子/摩恩/丰树/必维/阿特拉斯/第一精工等），33条第二轮修正，19条按文件名修正  `fix_other_groups.py`, `fix_other_groups2.py`, `fix_other_by_filename.py`
- 2026-04-05  集团名称规范化合并：493条记录（亨斯→亨斯迈、珀金埃尔→珀金埃尔默、锐科→派克集团、三井→三井集团、马勒→马勒集团等），company-level名称→group名称  `normalize_groups.py`
- 2026-04-05  公司名清洗：去除"服务合同-"/"采购单-"/"保密合同-"等合同类型前缀  `fix_other_groups.py`
- 2026-04-05  输出文件夹重组：64个文件夹重命名/合并，338个PDF移动到正确的 集团/年份 目录  `reorganize_folders2.py`
- 2026-04-05  重新生成208个集团的合同汇总Excel表  `generate_client_summary.py`
- 2026-04-05  生成集团公司归类清单最终版（234集团，1159公司）  `output/集团公司归类清单_最终版.xlsx`
- 2026-04-05  逐文件夹检查放错位置的文件：修正27个PDF（富耐连→摩恩、南院→福寿园、村田独立、轩尼诗→酩悦轩尼诗等）  `fix_misplaced.py`
- 2026-04-05  首诺/挪瓦玛翠→伊士曼、艾微美/英特格/安诺→应特格  按用户要求合并集团
- 2026-04-05  OCR公司名修正110处：流体转动→传动、罗氏剃药→制药、传奇电气→西门子电气传动、铂金埃尔默→珀金埃尔默等  `deep_check_summaries.py`
- 2026-04-05  清除16个年份误识别金额（如2018.01、2021.6等被OCR当作金额的日期）
- 2026-04-05  公司名前后缀清洗12处（债务继承通知-、供应商合同-、解除服务合同、-未补全等）
- 2026-04-05  最终验证：208份汇总表、2188条记录、1597条有金额，0个OCR/金额问题
- 2026-04-06  清除83个无PDF的空文件夹（只含Excel的旧集团文件夹）
- 2026-04-06  集团名规范化527处：62个公司全名→简短集团名（audit_fixed.jsonl同步到audit.jsonl）  `fix_audit_groups.py`
- 2026-04-06  从文件名补充100处空公司名、清除19处金额疑似日期、修复1处公司名前缀噪音
- 2026-04-06  全量核对汇总表：193个集团、2277条记录，金额/摘要/集团匹配 0 问题  `verify_summaries.py`
- 2026-04-06  修复错误归类：狼爪从观光投资移出、赫斯合并到赫斯可、帝亚吉欧合并到酩悦轩尼诗（59个PDF移动）；索尼/空气化工/艾默生各1个文件修正  `fix_misplaced2.py`
- 2026-04-06  从OCR正文补充9条未知年份记录（阿奇2011、丰树2013、莫仕2021、轩尼诗2020等），剩余138条无法自动确定
- 2026-04-06  从输入文件夹路径"纸质合同扫描件YYYY"提取年份，修复138条未知年份记录（仅剩2条无法确定）；移动84个PDF从未知年份到正确年份文件夹；清理47个空文件夹  `output/audit.jsonl`
- 2026-04-07  verify_summaries.py 新增 audit 同步检查、--strict 模式、严重问题标记；修复 Windows 大小写重复计数 bug  `verify_summaries.py`
- 2026-04-07  从"其他"集团提取205条记录到92个正确集团（珐菲琦→发发奇、爱博才思→丹纳赫、东福喜→日本电产、SONY SEH→索尼等）  `fix_other_to_groups.py`
- 2026-04-07  狮城德科→欣阳集团（2条）、苏州迈捷独立集团（3条）
- 2026-04-07  内部文件归类：41条记录分配到正确集团（山特维克7条、骊住/高仪7条、阿奇5条、慧瞻2条等），移动30个PDF；剩余7条为莱升自身内部文件
- 2026-04-07  验证通过：192个集团、2204条记录，金额/摘要/集团匹配 0 严重问题  `verify_summaries.py`
- 2026-04-08  全量逐条校验 3459 条记录，创建检查表 `output/audit_check_progress.jsonl`  `full_audit_check.py`
- 2026-04-08  修复 142 条 PDF 在错误集团文件夹（audit group 与 PDF 位置不一致），合并锐科→派克、泰科→泰科集团、FlexLink→摩恩  `fix audit + move PDFs`
- 2026-04-08  修复 41 条公司名为乙方（从文件名提取甲方名），补充 9 条空公司名，修复 22 条空年份（全部归零）
- 2026-04-08  移动 5 个 PDF 从未知年份到正确年份文件夹；修复途泰/涂泰 2 条记录
- 2026-04-08  验证通过：190个集团、2205条记录，0 严重问题  `verify_summaries.py`
- 2026-04-08  二次修复：FlexLink→摩恩4条、年份异常3条（航天信息1998→2004/莱升1999→2008/伊藤忠2017→2018）、OCR公司名3条（应辉/艾微/应铭格→英特格）、Sandvik归类1条  `fix_remaining_issues.py`
- 2026-04-08  移动3个PDF到正确年份文件夹（巴克莱/应特格/三井集团），删除FlexLink文件夹，清理8个空未知年份文件夹
- 2026-04-08  最终校验：3459条记录，2933条通过（84.7%），526条不可自动修复（PDF_NOT_FOUND 448 + COMPANY_EMPTY 148 + EXCEL_AMOUNT_DIFF 66假阳性 + 内部文件2条）
- 2026-04-10  批量修复年份错误：273条 audit 年份与文件名不符（"维护期2005-2006"被 OCR 读成2026等），按文件名年份优先原则更新631条，移动560个PDF到正确年份文件夹  `fix_year_mismatches.py`
- 2026-04-10  哈挺/未知年份文件移到2021（文件名含2021.12.16）；签名电子集团下的"索尼电子华南"PDF 移到索尼集团2013文件夹
- 2026-04-10  清理6个 其他 集团 PDF 到正确年份，删除2个陈旧汇总表（应特格/艾微美_合同汇总.xlsx、应特格/英特格_合同汇总.xlsx，合并前遗留），清理113个空文件夹
- 2026-04-10  最终校验：3459条记录，2933条通过，526条不可修复（同上），严重问题全部清零
- 2026-04-10  必维→必维集团合并（1条audit+1个PDF），泰科→泰科集团合并（6条audit，删陈旧空文件夹）  相似命名集团扫描
- 2026-04-10  VENDOR_BLOCKLIST 扩充：新增跃升/莱斯系列OCR变体（莱升OCR误读）；修复8条因此导致的客户名错误（派克汉尼汾/圣诺技/汉堡王/首诺/礼来/马勒/阿特拉斯/凯瑞德）  `src/main.py`, `src/group_query.py`, `fix_vendor_ocr_typos.py`
- 2026-04-10  批量补提取金额：用 GPT-4o-mini Vision 扫描 467 个无金额 PDF（维护/采购/SRF/升级类），两轮扫描（页1-3 + 深扫页4-6），成功提取 395 条金额；金额覆盖率从 74.4% 提升至 93.1%  `extract_missing_amounts.py`, `extract_amounts_pass2.py`, `apply_extracted_amounts.py`
- 2026-04-10  修正派克 wofe1 2016-2017 维护合同金额（26,560→27,020 含17%增值税，2年总价），补充维护期和季付信息  `audit.jsonl`
- 2026-04-11  多年合同金额修正：用 PyMuPDF 渲染 PDF 为图片直接读图（替代 OpenAI API），核对 8 份文件名标明多年期的合同。5 份派克（wofe1/液压天津×2/液压系统上海/过滤系统上海）数值正确但字段语义错（移到 tax_included_amount 并补维护期和 2 年标注）；莫仕 SRF 金额从 ¥4,500（单价/人天）改为 ¥31,500 不含税/¥32,850 含6%税；舒尔年费 ¥9,000→2年总价 ¥18,000 含税；托纳斯 ¥18,270→打95折后 2年总价 ¥34,713 含税；全部修正通过校验  `audit.jsonl`

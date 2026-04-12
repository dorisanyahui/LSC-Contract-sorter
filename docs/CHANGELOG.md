# 更新记录

本文档归档 Contract Sorter 项目的历史变更日志。最新变更（最近 5-10 条）保留在 [CLAUDE.md](../CLAUDE.md) 末尾。

---

## 2026-03-29 — 新管道上线

- 新管道（src/pipeline/）替代旧管道，OCR 引擎从 PaddleOCR 改为 GPT-4o-mini Vision  `src/pipeline/ocr_pipeline.py`
- 有文字层的 PDF 跳过 OCR 直接用文字层  `src/pipeline/ingest.py`
- 新增 software_version 字段提取（正则匹配"版本：V5.x"）  `src/extractors/base.py`, `src/models/schema.py`, `src/pipeline/ingest.py`
- generate_client_summary.py 支持所有集团（按 detected_group 分组，每集团生成一份 Excel）
- 汇总表新增：升级合同、项目合同两个类别；摘要去掉集团前缀；SRF 摘要补充服务类型/编号/服务期；维护合同摘要补充维护期和合同时长
- 修复 report_year 为空时从文件名兜底提取年份（infer_year）
- 修复 备注 字段从 Excel 列移除但 console 输出仍引用导致 KeyError 的 bug

## 2026-04-03 — 校验流程 + mapping 扩充

- 新增 validate_and_fix.py 校验流程：自动修复乙方误识别/关于前缀/噪音公司名，无映射公司归入"其他"  `validate_and_fix.py`
- generate_client_summary.py 过滤 UNKNOWN/OTHER/内部文档类型，过滤"内部文件"/"上海莱升"集团  `generate_client_summary.py`
- mapping 新增 15 个公司（罗门哈斯/日本电产/奇美材料/艾美仕/松下天津等）  `config/group_company_mapping_clean.xlsx`
- 新增 OCR 引擎选择（settings.yaml engine: gpt/paddleocr）  `src/pipeline/ocr_pipeline.py`, `config/settings.yaml`
- 修复 _build_keyword_map 中 "-legris"/"(685)" 等内部编码阻止法律后缀识别，导致"产品有限公司"成为派克集团关键词，75 条英特尔/爱普生/西门子等记录被误归到派克集团  `src/mapping/company_mapper.py`
- validate_and_fix.py 新增：问题 4c 公司名无法验证当前集团时重置为"其他"，问题 4b 补充文件名兜底映射  `validate_and_fix.py`
- mapping 新增 27 条（锐科独立集团、英特尔、爱普生、汉斯格雅、安迪苏、珀金埃尔 OCR 变体、琉璃工房、摩恩厨房变体、西门子医疗）；上海挪威→DNV  `config/group_company_mapping_clean.xlsx`

## 2026-04-05 — 大规模集团归属修正

- 大规模集团归属修正：330 条记录从"其他"分类到正确集团（派克/泰科/西门子/摩恩/丰树/必维/阿特拉斯/第一精工等），33 条第二轮修正，19 条按文件名修正  `fix_other_groups.py`, `fix_other_groups2.py`, `fix_other_by_filename.py`
- 集团名称规范化合并：493 条记录（亨斯→亨斯迈、珀金埃尔→珀金埃尔默、锐科→派克集团、三井→三井集团、马勒→马勒集团等），company-level 名称→group 名称  `normalize_groups.py`
- 公司名清洗：去除"服务合同-"/"采购单-"/"保密合同-"等合同类型前缀  `fix_other_groups.py`
- 输出文件夹重组：64 个文件夹重命名/合并，338 个 PDF 移动到正确的 集团/年份 目录  `reorganize_folders2.py`
- 重新生成 208 个集团的合同汇总 Excel 表  `generate_client_summary.py`
- 生成集团公司归类清单最终版（234 集团，1159 公司）  `output/集团公司归类清单_最终版.xlsx`
- 逐文件夹检查放错位置的文件：修正 27 个 PDF（富耐连→摩恩、南院→福寿园、村田独立、轩尼诗→酩悦轩尼诗等）  `fix_misplaced.py`
- 首诺/挪瓦玛翠→伊士曼、艾微美/英特格/安诺→应特格  按用户要求合并集团
- OCR 公司名修正 110 处：流体转动→传动、罗氏剃药→制药、传奇电气→西门子电气传动、铂金埃尔默→珀金埃尔默等  `deep_check_summaries.py`
- 清除 16 个年份误识别金额（如 2018.01、2021.6 等被 OCR 当作金额的日期）
- 公司名前后缀清洗 12 处（债务继承通知-、供应商合同-、解除服务合同、-未补全等）
- 最终验证：208 份汇总表、2188 条记录、1597 条有金额，0 个 OCR/金额问题

## 2026-04-06 — 集团名规范化 + 汇总表核对

- 清除 83 个无 PDF 的空文件夹（只含 Excel 的旧集团文件夹）
- 集团名规范化 527 处：62 个公司全名→简短集团名（audit_fixed.jsonl 同步到 audit.jsonl）  `fix_audit_groups.py`
- 从文件名补充 100 处空公司名、清除 19 处金额疑似日期、修复 1 处公司名前缀噪音
- 全量核对汇总表：193 个集团、2277 条记录，金额/摘要/集团匹配 0 问题  `verify_summaries.py`
- 修复错误归类：狼爪从观光投资移出、赫斯合并到赫斯可、帝亚吉欧合并到酩悦轩尼诗（59 个 PDF 移动）；索尼/空气化工/艾默生各 1 个文件修正  `fix_misplaced2.py`
- 从 OCR 正文补充 9 条未知年份记录（阿奇 2011、丰树 2013、莫仕 2021、轩尼诗 2020 等），剩余 138 条无法自动确定
- 从输入文件夹路径"纸质合同扫描件 YYYY"提取年份，修复 138 条未知年份记录（仅剩 2 条无法确定）；移动 84 个 PDF 从未知年份到正确年份文件夹；清理 47 个空文件夹  `output/audit.jsonl`

## 2026-04-07 — 其他集团提取 + 内部文件归类

- verify_summaries.py 新增 audit 同步检查、--strict 模式、严重问题标记；修复 Windows 大小写重复计数 bug  `verify_summaries.py`
- 从"其他"集团提取 205 条记录到 92 个正确集团（珐菲琦→发发奇、爱博才思→丹纳赫、东福喜→日本电产、SONY SEH→索尼等）  `fix_other_to_groups.py`
- 狮城德科→欣阳集团（2 条）、苏州迈捷独立集团（3 条）
- 内部文件归类：41 条记录分配到正确集团（山特维克 7 条、骊住/高仪 7 条、阿奇 5 条、慧瞻 2 条等），移动 30 个 PDF；剩余 7 条为莱升自身内部文件
- 验证通过：192 个集团、2204 条记录，金额/摘要/集团匹配 0 严重问题  `verify_summaries.py`

## 2026-04-08 — 全量逐条校验

- 全量逐条校验 3459 条记录，创建检查表 `output/audit_check_progress.jsonl`  `full_audit_check.py`
- 修复 142 条 PDF 在错误集团文件夹（audit group 与 PDF 位置不一致），合并锐科→派克、泰科→泰科集团、FlexLink→摩恩  `fix audit + move PDFs`
- 修复 41 条公司名为乙方（从文件名提取甲方名），补充 9 条空公司名，修复 22 条空年份（全部归零）
- 移动 5 个 PDF 从未知年份到正确年份文件夹；修复途泰/涂泰 2 条记录
- 验证通过：190 个集团、2205 条记录，0 严重问题  `verify_summaries.py`
- 二次修复：FlexLink→摩恩 4 条、年份异常 3 条（航天信息 1998→2004/莱升 1999→2008/伊藤忠 2017→2018）、OCR 公司名 3 条（应辉/艾微/应铭格→英特格）、Sandvik 归类 1 条  `fix_remaining_issues.py`
- 移动 3 个 PDF 到正确年份文件夹（巴克莱/应特格/三井集团），删除 FlexLink 文件夹，清理 8 个空未知年份文件夹
- 最终校验：3459 条记录，2933 条通过（84.7%），526 条不可自动修复（PDF_NOT_FOUND 448 + COMPANY_EMPTY 148 + EXCEL_AMOUNT_DIFF 66 假阳性 + 内部文件 2 条）

## 2026-04-10 — 年份修复 + 金额补提取

- 批量修复年份错误：273 条 audit 年份与文件名不符（"维护期 2005-2006"被 OCR 读成 2026 等），按文件名年份优先原则更新 631 条，移动 560 个 PDF 到正确年份文件夹  `fix_year_mismatches.py`
- 哈挺/未知年份文件移到 2021（文件名含 2021.12.16）；签名电子集团下的"索尼电子华南"PDF 移到索尼集团 2013 文件夹
- 清理 6 个 其他 集团 PDF 到正确年份，删除 2 个陈旧汇总表（应特格/艾微美_合同汇总.xlsx、应特格/英特格_合同汇总.xlsx，合并前遗留），清理 113 个空文件夹
- 最终校验：3459 条记录，2933 条通过，526 条不可修复（同上），严重问题全部清零
- 必维→必维集团合并（1 条 audit+1 个 PDF），泰科→泰科集团合并（6 条 audit，删陈旧空文件夹）  相似命名集团扫描
- VENDOR_BLOCKLIST 扩充：新增跃升/莱斯系列 OCR 变体（莱升 OCR 误读）；修复 8 条因此导致的客户名错误（派克汉尼汾/圣诺技/汉堡王/首诺/礼来/马勒/阿特拉斯/凯瑞德）  `src/main.py`, `src/group_query.py`, `fix_vendor_ocr_typos.py`
- 批量补提取金额：用 GPT-4o-mini Vision 扫描 467 个无金额 PDF（维护/采购/SRF/升级类），两轮扫描（页 1-3 + 深扫页 4-6），成功提取 395 条金额；金额覆盖率从 74.4% 提升至 93.1%  `extract_missing_amounts.py`, `extract_amounts_pass2.py`, `apply_extracted_amounts.py`
- 修正派克 wofe1 2016-2017 维护合同金额（26,560→27,020 含 17%增值税，2 年总价），补充维护期和季付信息  `audit.jsonl`
</content>
</invoke>
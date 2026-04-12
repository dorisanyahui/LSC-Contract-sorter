# CLAUDE.md — Contract Sorter 项目开发指南

将历史扫描合同按集团/年份自动归档。乙方固定为"上海莱升信息科技有限公司"（曾用名：泛纬软件）。架构、字段优先级、输出结构等见 [README.md](./README.md)。

---

## 开发规范（必须遵守）

1. **每次修改代码后必须自己验证**再告知用户：
   - 功能改动：`python -m src.main debug-file --file "input/某文件.pdf"`
   - 汇总脚本改动：`python generate_client_summary.py` 确认无报错
   - 提取逻辑：对比修改前后字段值
2. **每次修改必须在"最近更新"章节补一条**，历史归档到 [docs/CHANGELOG.md](./docs/CHANGELOG.md)。
3. 修改 audit.jsonl 后**必须**同步复制到 audit_fixed.jsonl，并跑 `verify_summaries.py`。
4. 小批量核对 PDF **不要调 OpenAI Vision API**，用 PyMuPDF 渲染 JPEG + Read 工具直接看图。
5. `software_version` 字段**绝不能猜**，只能来自 PDF 文字证据，缺失就留 NaN。

---

## 运行命令

```powershell
cd C:\LSC\contract_sorter
.venv\Scripts\Activate.ps1
$env:OPENAI_API_KEY = "sk-..."

python -m src.main run                                    # 全量处理
python generate_client_summary.py                         # 生成集团汇总
python -m src.main debug-file --file "input\某文件.pdf"   # 单文件调试
```

必须用 `python -m src.main run`，直接 `python src\main.py` 会 `ModuleNotFoundError`。

---

## 最近更新

历史归档见 [docs/CHANGELOG.md](./docs/CHANGELOG.md)。

- 2026-04-11  多年合同金额修正：用 PyMuPDF 渲染 PDF 读图（替代 OpenAI Vision API），核对 8 份多年期合同；5 份派克数值正确但字段语义错（移到 tax_included_amount 并补维护期）；莫仕 SRF ¥4,500→¥31,500/¥32,850；舒尔 ¥9,000→¥18,000；托纳斯 ¥18,270→¥34,713  `audit.jsonl`
- 2026-04-11  省钱配置调整（**未验证**）：`config/settings.yaml` 的 `ocr.dpi` 200→120、`ai.model` gpt-4o→gpt-4o-mini，理论全量跑成本从 ~$50 降到 $3-5；用户决定先改不验证，待未来跑新批次时用 debug-file 测试  `config/settings.yaml`
- 2026-04-11  CLAUDE.md 瘦身：历史更新记录归档到 `docs/CHANGELOG.md`（2026-03-29 ~ 2026-04-10 共 50+ 条），CLAUDE.md 从 234 行精简到 43 行，删除与 README 重复的架构/字段/输出结构章节；每轮注入 token 降低 ~8K  `CLAUDE.md`, `docs/CHANGELOG.md`
- 2026-04-11  汇总表数据质量清洗 Phase 1：新增 `scan_all_summaries.py` 全量扫描 190 份集团 Excel（2211 行，发现 736 个问题），`clean_audit_summaries.py` 自动修复 606 条 audit 记录的摘要——404 条 off-by-one 模板年份（AI 把维护期末年当签订年）、153 条跨年大错、21 条 `Shanghai LICENSE` 乙方名残留、14 条 `[上海莱升]` 前缀、5 条 `Excluding VAT) (Inc` OCR 碎片、1 条"力运集团"当公司名；重新生成 190 份 Excel，verify_summaries 0 严重问题  `scan_all_summaries.py`, `clean_audit_summaries.py`
- 2026-04-11  汇总表数据质量 Phase 2：`build_manual_review_queue.py` 生成 `output/manual_review_queue.xlsx` 人工核查清单 285 条（51 HIGH 版本时间线异常 V7/V8、19 MEDIUM 可疑低金额、206 LOW 无金额、9 LOW 残留边缘情况）；Phase 3 OCR 错字归一暂缓  `build_manual_review_queue.py`
</content>
</invoke>

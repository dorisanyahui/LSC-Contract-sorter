from __future__ import annotations

from typing import TYPE_CHECKING

from src.models.enums import DocType
from src.models.schema import DocumentResult

if TYPE_CHECKING:
    from src.pipeline.ai_resolver import AIResolver


class Summarizer:
    """Generates document summaries using rule-based logic or AI."""

    def generate(
        self,
        result: DocumentResult,
        ai_resolver: "AIResolver | None" = None,
    ) -> str:
        """Generate a one-sentence Chinese summary for the document.

        Uses rule-based generation first; falls back to AI for complex cases.
        """
        # Try rule-based summary
        summary = self._rule_based_summary(result)
        if summary:
            return summary

        # Fall back to AI for unknown or complex types
        if ai_resolver and result.doc_type in (DocType.UNKNOWN,):
            all_text_snippet = ""
            if result.fields:
                all_text_snippet = " ".join(
                    f.evidence_text for f in result.fields.values() if f.evidence_text
                )[:500]

            key_fields = {
                "公司": result.detected_company,
                "集团": result.detected_group,
                "日期": result.sign_date,
                "金额": str(result.contract_total_amount) if result.contract_total_amount else "",
                "年份": str(result.report_year) if result.report_year else "",
            }

            ai_summary = ai_resolver.summarize(
                doc_type=result.doc_type.value,
                fields=key_fields,
                text_snippet=all_text_snippet,
            )
            if ai_summary:
                return ai_summary

        return summary

    def _rule_based_summary(self, result: DocumentResult) -> str:
        """Generate a summary using rule-based templates."""
        company = result.detected_company or result.detected_counterparty or "未知公司"
        year = str(result.report_year) if result.report_year else ""
        group = result.detected_group

        # Format amounts
        amount_str = ""
        for amt_field in [result.annual_maintenance_fee, result.contract_total_amount, result.tax_included_amount]:
            if amt_field:
                amount_str = f"¥{amt_field:,.2f}"
                break

        prefix = f"[{group}] " if group else ""

        if result.doc_type == DocType.CONTRACT:
            period = ""
            if result.service_period_start and result.service_period_end:
                period = f"，服务期 {result.service_period_start} 至 {result.service_period_end}"
            elif result.service_period_start:
                period = f"，服务期自 {result.service_period_start}"

            if amount_str:
                return f"{prefix}与{company}签订的{year}年度服务合同，年度维护费 {amount_str}{period}"
            return f"{prefix}与{company}签订的{year}年度服务合同{period}"

        elif result.doc_type == DocType.PURCHASE_ORDER:
            if amount_str:
                return f"{prefix}{year}年 {company} 采购订单，总金额 {amount_str}"
            return f"{prefix}{year}年 {company} 采购订单"

        elif result.doc_type == DocType.QUOTE:
            if amount_str:
                return f"{prefix}向 {company} 提供的{year}年报价单，总额 {amount_str}"
            return f"{prefix}向 {company} 提供的{year}年报价单"

        elif result.doc_type == DocType.PROPOSAL:
            return f"{prefix}为 {company} 准备的{year}年项目建议书"

        elif result.doc_type == DocType.SRF:
            return f"{prefix}{company} 的{year}年服务需求表"

        elif result.doc_type == DocType.PAYMENT_NOTICE:
            if amount_str:
                return f"{prefix}向 {company} 发出的付款通知，金额 {amount_str}"
            return f"{prefix}向 {company} 发出的付款通知"

        elif result.doc_type == DocType.ATTACHMENT:
            subtype = result.doc_subtype or "附件"
            return f"{prefix}{company} 相关{subtype}"

        return ""

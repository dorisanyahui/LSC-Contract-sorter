from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field

from src.models.enums import DocType, FieldSource, Currency


class Candidate(BaseModel):
    value: str
    normalized_value: str = ""
    label: str = ""
    page: int = 0
    bbox: list[float] | None = None
    evidence_text: str = ""
    score: float = 0.0
    source: FieldSource = FieldSource.OCR


class FieldEvidence(BaseModel):
    value: str
    confidence: float = 0.0
    page: int | None = None
    bbox: list[float] | None = None
    evidence_text: str = ""
    source: FieldSource = FieldSource.OCR
    candidates: list[Candidate] = Field(default_factory=list)


class OCRTextBlock(BaseModel):
    text: str
    bbox: list[float]
    confidence: float
    page: int


class OCRPageResult(BaseModel):
    page_no: int
    width: int
    height: int
    text_blocks: list[OCRTextBlock] = Field(default_factory=list)
    raw_text: str = ""
    confidence_avg: float = 0.0


class PacketResult(BaseModel):
    packet_id: str
    start_page: int
    end_page: int
    packet_type: str = "UNKNOWN"
    title_hint: str = ""
    doc_type: DocType = DocType.UNKNOWN
    fields: dict[str, FieldEvidence] = Field(default_factory=dict)


class DocumentResult(BaseModel):
    # File metadata
    file_path: str = ""
    file_name: str = ""
    file_md5: str = ""
    page_count: int = 0
    has_text_layer: bool = False

    # Doc classification
    doc_type: DocType = DocType.UNKNOWN
    doc_subtype: str = ""
    is_primary_doc: bool = True
    packet_count: int = 0

    # Company info
    detected_group: str = ""
    detected_company: str = ""
    detected_counterparty: str = ""

    # Dates
    sign_date: str = ""
    effective_date: str = ""
    service_period_start: str = ""
    service_period_end: str = ""
    report_year: int | None = None

    # Financial
    currency: Currency = Currency.CNY
    annual_maintenance_fee: float | None = None
    tax_rate: str = ""
    tax_included_amount: float | None = None
    tax_excluded_amount: float | None = None
    contract_total_amount: float | None = None

    # Reference numbers
    po_number: str = ""
    quote_number: str = ""
    software_version: str = ""

    # Summary and metadata
    summary: str = ""
    confidence_overall: float = 0.0
    flags: list[str] = Field(default_factory=list)

    # Detailed extraction data
    fields: dict[str, FieldEvidence] = Field(default_factory=dict)
    packets: list[PacketResult] = Field(default_factory=list)

    # Error info
    error: str | None = None

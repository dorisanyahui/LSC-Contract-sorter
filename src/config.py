from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache
from dataclasses import dataclass, field
from typing import Any

import yaml


VENDOR_NAMES: list[str] = [
    "上海莱升",
    "莱升信息",
    "泛纬软件",
    "泛纬电脑",
    "LICENSE CONSULTING",
    "LICENSE Software",   # English contract letterhead variant
    "license-solution",
    "LSC",
]

_DEFAULT_SETTINGS_PATH = Path(__file__).parent.parent / "config" / "settings.yaml"


@dataclass
class OCRSettings:
    engine: str = "paddleocr"
    lang: str = "ch"
    use_angle_cls: bool = True
    dpi: int = 200
    max_workers: int = 2


@dataclass
class AISettings:
    enabled: bool = True
    provider: str = "openai"
    model: str = "gpt-4o"
    timeout_sec: int = 60
    max_retries: int = 3
    tpm_budget: int = 80000


@dataclass
class AmountRange:
    min_val: float
    max_val: float


@dataclass
class RulesSettings:
    amount_ranges: dict[str, list[float]] = field(default_factory=dict)
    doc_type_keywords: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class Settings:
    base_dir: Path = Path("C:/LSC/contract_sorter")
    input_dir: Path = Path("C:/LSC/contract_sorter/input")
    output_dir: Path = Path("C:/LSC/contract_sorter/output")
    cache_dir: Path = Path("C:/LSC/contract_sorter/cache")
    log_dir: Path = Path("C:/LSC/contract_sorter/logs")
    mapping_file: Path = Path("C:/LSC/contract_sorter/config/group_company_mapping_clean.xlsx")

    ocr: OCRSettings = field(default_factory=OCRSettings)
    ai: AISettings = field(default_factory=AISettings)
    rules: RulesSettings = field(default_factory=RulesSettings)

    vendor_names: list[str] = field(default_factory=lambda: list(VENDOR_NAMES))

    def ensure_dirs(self) -> None:
        for d in [self.input_dir, self.output_dir, self.cache_dir, self.log_dir]:
            d.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / "ocr").mkdir(parents=True, exist_ok=True)
        (self.cache_dir / "results").mkdir(parents=True, exist_ok=True)

    def get_amount_range(self, field_name: str) -> list[float]:
        return self.rules.amount_ranges.get(field_name, [1000, 200000])


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _parse_settings(data: dict[str, Any]) -> Settings:
    s = Settings()

    if "base_dir" in data:
        s.base_dir = Path(data["base_dir"])
    if "input_dir" in data:
        s.input_dir = Path(data["input_dir"])
    if "output_dir" in data:
        s.output_dir = Path(data["output_dir"])
    if "cache_dir" in data:
        s.cache_dir = Path(data["cache_dir"])
    if "log_dir" in data:
        s.log_dir = Path(data["log_dir"])
    if "mapping_file" in data:
        s.mapping_file = Path(data["mapping_file"])

    if "ocr" in data:
        ocr_data = data["ocr"]
        s.ocr = OCRSettings(
            engine=ocr_data.get("engine", "paddleocr"),
            lang=ocr_data.get("lang", "ch"),
            use_angle_cls=ocr_data.get("use_angle_cls", True),
            dpi=ocr_data.get("dpi", 200),
            max_workers=ocr_data.get("max_workers", 2),
        )

    if "ai" in data:
        ai_data = data["ai"]
        s.ai = AISettings(
            enabled=ai_data.get("enabled", True),
            provider=ai_data.get("provider", "openai"),
            model=ai_data.get("model", "gpt-4o"),
            timeout_sec=ai_data.get("timeout_sec", 60),
            max_retries=ai_data.get("max_retries", 3),
            tpm_budget=ai_data.get("tpm_budget", 80000),
        )

    if "rules" in data:
        rules_data = data["rules"]
        s.rules = RulesSettings(
            amount_ranges=rules_data.get("amount_ranges", {}),
            doc_type_keywords=rules_data.get("doc_type_keywords", {}),
        )

    return s


@lru_cache(maxsize=1)
def get_settings(config_path: str | None = None) -> Settings:
    path = Path(config_path) if config_path else _DEFAULT_SETTINGS_PATH
    if path.exists():
        data = _load_yaml(path)
        return _parse_settings(data)
    return Settings()

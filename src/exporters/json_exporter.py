from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from src.models.schema import DocumentResult
from src.utils.file_utils import ensure_dir


class JSONExporter:
    """Exports DocumentResult data to JSON/JSONL files for audit purposes."""

    def export_audit(self, results: list[DocumentResult], output_dir: Path) -> None:
        """Export all results to an audit.jsonl file (one JSON object per line).

        This format is suitable for downstream processing, debugging, and auditing.
        Each line is a self-contained JSON object.
        """
        ensure_dir(output_dir)
        output_path = output_dir / "audit.jsonl"

        written = 0
        with open(output_path, "w", encoding="utf-8") as f:
            for result in results:
                try:
                    data = result.model_dump()
                    # Convert enum values to strings for JSON serialization
                    data = _serialize_enums(data)
                    line = json.dumps(data, ensure_ascii=False, default=str)
                    f.write(line + "\n")
                    written += 1
                except Exception as e:
                    logger.warning(f"Failed to serialize result for {result.file_name}: {e}")
                    # Write minimal error record
                    error_record = {
                        "file_name": result.file_name,
                        "file_path": result.file_path,
                        "error": str(e),
                        "serialization_error": True,
                    }
                    f.write(json.dumps(error_record, ensure_ascii=False) + "\n")

        logger.info(f"Exported {written} audit records to {output_path}")

    def export_per_group(self, results: list[DocumentResult], output_dir: Path) -> None:
        """Export results grouped by detected_group, one JSONL per group."""
        ensure_dir(output_dir)

        groups: dict[str, list[DocumentResult]] = {}
        for result in results:
            group = result.detected_group or "未分组"
            groups.setdefault(group, []).append(result)

        for group_name, group_results in groups.items():
            safe_name = group_name.replace("/", "_").replace("\\", "_")
            output_path = output_dir / f"{safe_name}_audit.jsonl"

            with open(output_path, "w", encoding="utf-8") as f:
                for result in group_results:
                    try:
                        data = result.model_dump()
                        data = _serialize_enums(data)
                        f.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")
                    except Exception as e:
                        logger.warning(f"Failed to serialize {result.file_name}: {e}")

            logger.info(f"Exported {len(group_results)} records for group '{group_name}'")


def _serialize_enums(data: dict | list | object) -> dict | list | object:
    """Recursively convert Enum values to their string representation."""
    if isinstance(data, dict):
        return {k: _serialize_enums(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_serialize_enums(item) for item in data]
    elif hasattr(data, "value"):
        # Enum
        return data.value
    return data

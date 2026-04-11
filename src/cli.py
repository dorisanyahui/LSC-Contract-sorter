from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click
from loguru import logger

# Load .env file from project root if present
def _load_dotenv() -> None:
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

_load_dotenv()


def _setup_logging(log_dir: Path) -> None:
    """Configure loguru logging."""
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")
    logger.add(
        log_dir / "contract_sorter_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        rotation="1 day",
        retention="30 days",
        encoding="utf-8",
    )


@click.group()
def cli() -> None:
    """Contract Sorter — Automated enterprise document archiving system."""
    pass


@cli.command()
@click.option("--input", "input_dir", default=None, help="Input directory with PDF files")
@click.option("--output", "output_dir", default=None, help="Output directory for results")
@click.option("--group", "group_filter", default=None, help="Only process files for this group")
@click.option("--force-ocr", is_flag=True, default=False, help="Force re-OCR even if cached")
@click.option("--force-ai", is_flag=True, default=False, help="Force AI calls even for clear cases")
@click.option("--force-all", is_flag=True, default=False, help="Force all re-processing")
@click.option("--config", "config_path", default=None, help="Path to settings.yaml")
def run(
    input_dir: str | None,
    output_dir: str | None,
    group_filter: str | None,
    force_ocr: bool,
    force_ai: bool,
    force_all: bool,
    config_path: str | None,
) -> None:
    """Process all PDF files in the input directory."""
    from src.config import get_settings
    from src.exporters.excel_exporter import ExcelExporter
    from src.exporters.json_exporter import JSONExporter
    from src.pipeline.ingest import DocumentProcessor
    from src.utils.file_utils import scan_pdfs

    settings = get_settings(config_path)
    _setup_logging(settings.log_dir)
    settings.ensure_dirs()

    in_dir = Path(input_dir) if input_dir else settings.input_dir
    out_dir = Path(output_dir) if output_dir else settings.output_dir

    logger.info(f"Scanning for PDFs in: {in_dir}")
    pdf_paths = scan_pdfs(in_dir)
    logger.info(f"Found {len(pdf_paths)} PDF files")

    if not pdf_paths:
        logger.warning("No PDF files found. Exiting.")
        return

    # Initialize processor
    processor = DocumentProcessor(settings=settings)

    # Process files
    results = processor.process_batch(pdf_paths, group_filter=group_filter)

    # Export results
    excel_exporter = ExcelExporter()
    json_exporter = JSONExporter()

    excel_exporter.export_all(results, out_dir)
    excel_exporter.export_by_group(results, out_dir)
    excel_exporter.export_packets(results, out_dir)
    json_exporter.export_audit(results, out_dir)

    logger.info(f"Done. Results in: {out_dir}")

    # Print summary
    success = [r for r in results if not r.error]
    failed = [r for r in results if r.error]
    no_group = [r for r in success if not r.detected_group]

    click.echo(f"\nSummary:")
    click.echo(f"  Total processed: {len(results)}")
    click.echo(f"  Successful: {len(success)}")
    click.echo(f"  Failed: {len(failed)}")
    click.echo(f"  No group mapping: {len(no_group)}")


@cli.command("debug-file")
@click.option("--file", "file_path", required=True, help="Path to PDF file to debug")
@click.option("--config", "config_path", default=None, help="Path to settings.yaml")
def debug_file(file_path: str, config_path: str | None) -> None:
    """Process a single file and print detailed debug information."""
    from src.config import get_settings
    from src.pipeline.ingest import DocumentProcessor

    settings = get_settings(config_path)
    _setup_logging(settings.log_dir)

    pdf_path = Path(file_path)
    if not pdf_path.exists():
        click.echo(f"Error: File not found: {file_path}", err=True)
        sys.exit(1)

    logger.info(f"Debug processing: {pdf_path}")
    processor = DocumentProcessor(settings=settings)
    result = processor.process_file(pdf_path)

    click.echo("\n" + "=" * 60)
    click.echo(f"File: {result.file_name}")
    click.echo(f"MD5: {result.file_md5}")
    click.echo(f"Pages: {result.page_count}")
    click.echo(f"Has text layer: {result.has_text_layer}")
    click.echo(f"Doc type: {result.doc_type.value}")
    click.echo(f"Group: {result.detected_group}")
    click.echo(f"Company: {result.detected_company}")
    click.echo(f"Sign date: {result.sign_date}")
    click.echo(f"Year: {result.report_year}")
    click.echo(f"Annual fee: {result.annual_maintenance_fee}")
    click.echo(f"Tax rate: {result.tax_rate}")
    click.echo(f"Tax included: {result.tax_included_amount}")
    click.echo(f"Total: {result.contract_total_amount}")
    click.echo(f"Confidence: {result.confidence_overall:.3f}")
    click.echo(f"Flags: {result.flags}")
    click.echo(f"Summary: {result.summary}")

    if result.error:
        click.echo(f"ERROR: {result.error}", err=True)

    click.echo("\nExtracted fields:")
    for key, ev in result.fields.items():
        click.echo(f"  {key}: {ev.value!r} (conf={ev.confidence:.2f}, src={ev.source.value})")


@cli.command("debug-packet")
@click.option("--file", "file_path", required=True, help="Path to PDF file to debug packets")
@click.option("--config", "config_path", default=None, help="Path to settings.yaml")
def debug_packet(file_path: str, config_path: str | None) -> None:
    """Show packet structure for a single PDF file."""
    from src.config import get_settings
    from src.pipeline.ingest import DocumentProcessor

    settings = get_settings(config_path)
    _setup_logging(settings.log_dir)

    pdf_path = Path(file_path)
    if not pdf_path.exists():
        click.echo(f"Error: File not found: {file_path}", err=True)
        sys.exit(1)

    processor = DocumentProcessor(settings=settings)
    result = processor.process_file(pdf_path)

    click.echo(f"\nFile: {result.file_name}")
    click.echo(f"Total packets: {result.packet_count}")

    for packet in result.packets:
        click.echo(f"\n  Packet: {packet.packet_id}")
        click.echo(f"    Pages: {packet.start_page} - {packet.end_page}")
        click.echo(f"    Type: {packet.packet_type}")
        click.echo(f"    Doc type: {packet.doc_type.value}")
        click.echo(f"    Title: {packet.title_hint[:80]}")


@cli.command("export")
@click.option("--from-cache", is_flag=True, help="Export from cached results instead of re-processing")
@click.option("--output", "output_dir", default=None, help="Output directory")
@click.option("--config", "config_path", default=None, help="Path to settings.yaml")
def export(from_cache: bool, output_dir: str | None, config_path: str | None) -> None:
    """Export results to Excel and JSON."""
    from src.config import get_settings
    from src.exporters.excel_exporter import ExcelExporter
    from src.exporters.json_exporter import JSONExporter
    from src.models.schema import DocumentResult

    settings = get_settings(config_path)
    _setup_logging(settings.log_dir)

    out_dir = Path(output_dir) if output_dir else settings.output_dir

    if from_cache:
        # Load all cached results
        cache_dir = settings.cache_dir / "results"
        results: list[DocumentResult] = []

        if not cache_dir.exists():
            click.echo("No cache directory found.", err=True)
            return

        for cache_file in cache_dir.glob("*.json"):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                result = DocumentResult(**data)
                results.append(result)
            except Exception as e:
                logger.warning(f"Failed to load cache file {cache_file}: {e}")

        logger.info(f"Loaded {len(results)} results from cache")
    else:
        click.echo("Use --from-cache to export from cached results, or use the 'run' command to process files.", err=True)
        return

    excel_exporter = ExcelExporter()
    json_exporter = JSONExporter()

    excel_exporter.export_all(results, out_dir)
    excel_exporter.export_by_group(results, out_dir)
    json_exporter.export_audit(results, out_dir)

    click.echo(f"Exported {len(results)} results to {out_dir}")


@cli.command("rebuild-cache")
@click.option("--input", "input_dir", default=None, help="Input directory with PDF files")
@click.option("--config", "config_path", default=None, help="Path to settings.yaml")
def rebuild_cache(input_dir: str | None, config_path: str | None) -> None:
    """Rebuild OCR cache for all PDF files (force re-OCR)."""
    from src.config import get_settings
    from src.pipeline.ingest import DocumentProcessor
    from src.utils.file_utils import scan_pdfs
    from src.utils.hash_utils import md5_file

    settings = get_settings(config_path)
    _setup_logging(settings.log_dir)
    settings.ensure_dirs()

    in_dir = Path(input_dir) if input_dir else settings.input_dir
    pdf_paths = scan_pdfs(in_dir)

    logger.info(f"Rebuilding OCR cache for {len(pdf_paths)} files in {in_dir}")

    processor = DocumentProcessor(settings=settings)

    from tqdm import tqdm
    for pdf_path in tqdm(pdf_paths, desc="Rebuilding cache"):
        try:
            file_md5 = md5_file(pdf_path)
            processor._ocr_pipeline.process(pdf_path, file_md5, force=True)
        except Exception as e:
            logger.error(f"Failed to rebuild cache for {pdf_path}: {e}")

    logger.info("Cache rebuild complete.")

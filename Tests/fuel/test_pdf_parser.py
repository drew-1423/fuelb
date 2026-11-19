"""Unit tests for official decree PDF parser and table extraction."""
from pathlib import Path
import json
import pytest

from lebanon_fuel.structural.pdf_parser import (
    normalize_arabic,
    parse_arabic_date,
    parse_decision_number,
    parse_decree_table,
    extract_pdf_content,
    parse_official_pdf,
)

ROOT = Path(__file__).resolve().parents[2]
PDF_FIXTURE_DIGITAL = ROOT / "data/raw/official_document/12b629160cb79062cbd84635136cd0bd297376936c1b080b80968c6ff427dd43.pdf"
PDF_FIXTURE_SCANNED = ROOT / "data/raw/official_document/9f59129eaa93ba4fe82d5614a28b73a02ae271e5a1f30a1e5a9537c693fa0d39.pdf"


@pytest.mark.parametrize("raw,expected", [
    ("وزارة الطاق ـة والميـاه", "وزارة الطاقة والمياه"),
    ("وزارة الطاقة والمياه", "وزارة الطاقة والمياه"),
    ("الطاق\nـة 33300", "الطاق\nة 33300"),
])
def test_normalization_repairs_only_horizontal_tatweel_word_spacing(raw, expected):
    assert normalize_arabic(raw) == expected


def test_arabic_date_parsing():
    assert parse_arabic_date("بيروت في 27/10/2010") == "2010-10-27"
    assert parse_arabic_date("الأربعاء 27 تشرين الأول 2010") == "2010-10-27"
    assert parse_arabic_date("تاريخ 12 أيار 2023") == "2023-05-12"
    assert parse_arabic_date("صدر بتاريخ 29/5/2025") == "2025-05-29"
    assert parse_arabic_date("invalid date string") is None


def test_decision_number_parsing():
    assert parse_decision_number("قرار رقم 180") == "180"
    assert parse_decision_number("قرار رقم: 245") == "245"
    assert parse_decision_number("قرار 166 الصادر عن") == "166"
    assert parse_decision_number("بلا قرار مذكور") is None


def test_extract_digital_pdf_content():
    if not PDF_FIXTURE_DIGITAL.exists():
        pytest.skip("Digital PDF fixture not found")
    content = extract_pdf_content(PDF_FIXTURE_DIGITAL)
    assert content["page_count"] == 1
    assert content["is_scanned_raster"] is False
    assert content["total_text_length"] > 100
    assert content["sha256"] == "12b629160cb79062cbd84635136cd0bd297376936c1b080b80968c6ff427dd43"
    assert "وزارة الطاقة والمياه" in normalize_arabic(content["pages"][0]["text"])


def test_parse_decree_table_arithmetic():
    if not PDF_FIXTURE_DIGITAL.exists():
        pytest.skip("Digital PDF fixture not found")
    content = extract_pdf_content(PDF_FIXTURE_DIGITAL)
    text = content["pages"][0]["text"]
    parsed = parse_decree_table(text)

    assert parsed["date"] == "2010-10-27"
    assert "gasoline_95" in parsed["products"]
    g95 = parsed["products"]["gasoline_95"]
    assert g95["pretax_lbp_20l"] == 20740
    assert g95["tax_and_fees_lbp_20l"] == 12557
    assert g95["consumer_price_lbp_20l"] == 33300
    assert g95["arithmetic_valid"] is True
    assert g95["rounding_discrepancy_lbp_20l"] == 3  # 20740 + 12557 = 33297, rounded up to 33300


def test_scanned_raster_detection():
    if not PDF_FIXTURE_SCANNED.exists():
        pytest.skip("Scanned PDF fixture not found")
    result = parse_official_pdf(PDF_FIXTURE_SCANNED)
    assert result["page_count"] == 2
    assert result["is_scanned_raster"] is True
    assert result["extraction_status"] == "scanned_raster_requires_ocr_or_visual_transcription"
    assert result["file_sha256"] == "9f59129eaa93ba4fe82d5614a28b73a02ae271e5a1f30a1e5a9537c693fa0d39"


def test_structural_cli_parse_pdf():
    if not PDF_FIXTURE_DIGITAL.exists():
        pytest.skip("Digital PDF fixture not found")
    from lebanon_fuel.structural.cli import main
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = main(["parse-pdf", str(PDF_FIXTURE_DIGITAL)])
    assert exit_code == 0
    payload = json.loads(buf.getvalue())
    assert payload["date"] == "2010-10-27"
    assert payload["products"]["gasoline_95"]["consumer_price_lbp_20l"] == 33300

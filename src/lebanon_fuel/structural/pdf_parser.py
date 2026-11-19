"""Official Lebanese Ministry of Energy & Water (MEW) PDF decree parser.

Extracts tabular price schedules, taxes, dates, and decision numbers from
digital decrees, and extracts embedded raster images and hashes from scanned decrees.
"""
from datetime import date, datetime
from decimal import Decimal as D
from hashlib import sha256
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False


ARABIC_MONTHS = {
    "كانون الثاني": 1,
    "شباط": 2,
    "آذار": 3,
    "نيسان": 4,
    "أيار": 5,
    "حزيران": 6,
    "تموز": 7,
    "آب": 8,
    "أيلول": 9,
    "تشرين الأول": 10,
    "تشرين الاول": 10,
    "تشرين أول": 10,
    "تشرين اول": 10,
    "تشرين الثاني": 11,
    "تشرين ثاني": 11,
    "كانون الأول": 12,
    "كانون الاول": 12,
    "كانون أول": 12,
    "كانون اول": 12,
}

PRODUCT_PATTERNS = {
    "gasoline_95": r"بنزين\s*95\s*أوكتان\s+(\d+)\s+(\d+)\s+(\d+)",
    "gasoline_98": r"بنزين\s*98\s*أوكتان\s+(\d+)\s+(\d+)\s+(\d+)",
    "kerosene": r"كـ?از\s+(\d+)\s+(\d+)\s+(\d+)",
    "gasoil": r"مـ?ازوت\s+(\d+)\s+(\d+)\s+(\d+)",
    "diesel": r"ديـ?زل\s*أويـ?ل\s+(\d+)\s+(\d+)\s+(\d+)",
    "lpg_10kg": r"غـ?از\s*سائـ?ل\s*/\s*قـ?ارورة\s*10\s*كلـ?غ\s+(\d+)\s+(\d+)\s+(\d+)",
    "lpg_12_5kg": r"غـ?از\s*سائـ?ل\s*/\s*قـ?ارورة\s*12\.5\s*كلغ\s+(\d+)\s+(\d+)\s+(\d+)",
}


def normalize_arabic(text: str) -> str:
    """Remove tatweel and extraction spacing inside words, preserving boundaries."""
    if not text:
        return ""
    # Some supported PDF extractors put a horizontal space before a connecting
    # tatweel inside a word (e.g. الطاق ـة). Do not join ordinary words or lines.
    letters = r"\u0621-\u063a\u0641-\u064a"
    cleaned = re.sub(rf"(?<=[{letters}])[ \t]+(?=\u0640[{letters}])", "", text)
    cleaned = cleaned.replace("\u0640", "")
    return cleaned


def parse_arabic_date(text: str) -> Optional[str]:
    """Parse Arabic decree date string into ISO YYYY-MM-DD format."""
    text = normalize_arabic(text)
    # 1. Numeric format: dd/mm/yyyy or dd-mm-yyyy
    num_match = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", text)
    if num_match:
        day, month, year = map(int, num_match.groups())
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            pass

    # 2. Text format: e.g. "27 تشرين الأول 2010"
    for month_name, month_num in ARABIC_MONTHS.items():
        pattern = rf"(\d{{1,2}})\s+{month_name}\s+(\d{{4}})"
        match = re.search(pattern, text)
        if match:
            day, year = int(match.group(1)), int(match.group(2))
            try:
                return date(year, month_num, day).isoformat()
            except ValueError:
                pass

    return None


def parse_decision_number(text: str) -> Optional[str]:
    """Extract official decree / decision number if present."""
    match = re.search(r"قرار\s*(?:رقم)?\s*[:\s]*(\d+)", text)
    if match:
        return match.group(1)
    return None


def extract_pdf_content(pdf_path: Path) -> Dict[str, Any]:
    """Extract raw bytes hash, page text streams, and embedded images from a PDF file."""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    raw_bytes = pdf_path.read_bytes()
    file_sha256 = sha256(raw_bytes).hexdigest()

    if not PYPDF_AVAILABLE:
        return {
            "path": str(pdf_path),
            "sha256": file_sha256,
            "page_count": 0,
            "pages": [],
            "error": "pypdf is not installed",
        }

    reader = PdfReader(pdf_path)
    pages = []
    total_text_length = 0

    for i, page in enumerate(reader.pages):
        page_text = page.extract_text() or ""
        total_text_length += len(page_text)
        image_info = []
        if hasattr(page, "images"):
            for img in page.images:
                img_bytes = img.data
                image_info.append({
                    "name": img.name,
                    "sha256": sha256(img_bytes).hexdigest(),
                    "size_bytes": len(img_bytes),
                })
        pages.append({
            "page_number": i + 1,
            "text": page_text,
            "text_length": len(page_text),
            "images": image_info,
        })

    is_scanned = total_text_length < 50 and any(p["images"] for p in pages)

    return {
        "path": str(pdf_path),
        "sha256": file_sha256,
        "page_count": len(pages),
        "is_scanned_raster": is_scanned,
        "total_text_length": total_text_length,
        "pages": pages,
    }


def parse_decree_table(text: str) -> Dict[str, Any]:
    """Parse tabular fuel pricing figures from raw Arabic text."""
    norm_text = normalize_arabic(text)
    products = {}
    for product_key, pattern in PRODUCT_PATTERNS.items():
        m = re.search(pattern, norm_text)
        if m:
            pretax, tax, total = map(int, m.groups())
            sum_check = pretax + tax
            diff = abs(sum_check - total)
            products[product_key] = {
                "pretax_lbp_20l": pretax,
                "tax_and_fees_lbp_20l": tax,
                "consumer_price_lbp_20l": total,
                "recomputed_sum_lbp_20l": sum_check,
                "rounding_discrepancy_lbp_20l": diff,
                "arithmetic_valid": diff <= 10,
            }

    decree_date = parse_arabic_date(text)
    decision_num = parse_decision_number(text)

    return {
        "date": decree_date,
        "decision_number": decision_num,
        "products": products,
        "gasoline_95_found": "gasoline_95" in products,
    }


def parse_official_pdf(pdf_path: Path, source_url: Optional[str] = None) -> Dict[str, Any]:
    """End-to-end parser extracting official pricing decree data from a PDF."""
    pdf_path = Path(pdf_path)
    content = extract_pdf_content(pdf_path)

    full_text = "\n\n".join(p["text"] for p in content["pages"])
    parsed = parse_decree_table(full_text)

    return {
        "file_sha256": content["sha256"],
        "file_path": str(pdf_path),
        "source_url": source_url,
        "page_count": content["page_count"],
        "is_scanned_raster": content["is_scanned_raster"],
        "date": parsed["date"],
        "decision_number": parsed["decision_number"],
        "products": parsed["products"],
        "extraction_status": "success_digital_text" if parsed["gasoline_95_found"] else (
            "scanned_raster_requires_ocr_or_visual_transcription" if content["is_scanned_raster"] else "no_pricing_table_matched"
        ),
    }

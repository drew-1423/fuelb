"""Explicit units, date roles, and lossless source observations."""
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
import json
import re

BEIRUT = ZoneInfo("Asia/Beirut")
UNIT = "LBP/20L"
SOURCES = {
    "official_document": (1, "ministry"),
    "ministry": (2, "ministry"),
    "ipt": (3, "ipt"),
    "taqtek": (4, "ministry_derived"),
    "manual": (5, "manual_unverified"),
}
PROVISIONAL_PRICE = "provisional_corroborated"
VERIFIED = {"document_verified", "archive_corroborated"}


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def utc_timestamp(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("Timestamp needs an explicit UTC offset; date-only is a separate field")
    return dt.astimezone(timezone.utc).isoformat()


def price_integer(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("Missing/invalid price")
    text = str(value).strip().replace("٬", ",")
    text = "".join(str(int(c)) if c.isdecimal() else c for c in text)
    if not re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.0+)?", text):
        raise ValueError("Price must be an integer LBP amount, not inferred currency/units")
    try:
        value = Decimal(text.replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError("Invalid price") from exc
    if not value.is_finite() or value != value.to_integral_value() or not 0 < value <= 1_000_000_000:
        raise ValueError("Price outside positive integer range")
    return int(value)


def regime_label(day):
    """Research buckets, explicitly not certified legal transition dates."""
    if day < "2019-09-01":
        return "pre_crisis_research_bucket"
    if day < "2022-11-01":
        return "crisis_subsidy_transition_unresolved"
    if day < "2025-05-29":
        return "post_subsidy_fx_transition_unresolved"
    if day < "2026-02-16":
        return "2025_fiscal_changes_unresolved"
    return "2026_fiscal_changes_unresolved"


def weekday_disagreement(text, day):
    if not day: return False
    normalized=text.replace('أ','ا').replace('إ','ا').replace('آ','ا')
    weekdays={'الاثنين':0,'الثلاثاء':1,'الاربعاء':2,'الخميس':3,'الجمعة':4,'السبت':5,'الاحد':6}
    label=normalized.split(',')[0].strip()
    return label in weekdays and weekdays[label]!=date.fromisoformat(day).weekday()


@dataclass
class Observation:
    source: str
    source_date: str | None
    price_lbp_20l: int | None
    source_url: str
    raw: dict
    row_key: str
    unit: str = UNIT
    date_role: str = "source_label"
    official_effective_date: str | None = None
    publication_date: str | None = None
    publication_timestamp: str | None = None
    decision_number: str | None = None
    document_verified: bool = False
    issues: list[str] = field(default_factory=list)

    def checked(self, retrieved_at):
        issues = list(self.issues)
        try:
            self.price_lbp_20l = price_integer(self.price_lbp_20l)
        except ValueError:
            self.price_lbp_20l = None
            issues.append("invalid_price")
        if self.unit != UNIT:
            issues.append("unexpected_unit")
        retrieved = datetime.fromisoformat(utc_timestamp(retrieved_at))
        for name in ("source_date", "publication_date", "official_effective_date"):
            value = getattr(self, name)
            try:
                if value is not None:
                    date.fromisoformat(value)
                elif name == "source_date":
                    raise ValueError("Missing date")
            except ValueError:
                issues.append(name + "_invalid")
                setattr(self, name, None)
        if self.source_date and self.source_date > retrieved.astimezone(BEIRUT).date().isoformat():
            issues.append("future_source_date")
        if self.publication_timestamp:
            try:
                self.publication_timestamp = utc_timestamp(self.publication_timestamp)
                pub = datetime.fromisoformat(self.publication_timestamp)
                if pub > retrieved:
                    issues.append("future_publication")
                if self.publication_date and pub.astimezone(BEIRUT).date().isoformat() != self.publication_date:
                    issues.append("publication_date_alignment")
            except ValueError:
                self.publication_timestamp = None
                issues.append("invalid_timestamp")
        if self.publication_date and self.official_effective_date and self.publication_date > self.official_effective_date:
            issues.append("publication_after_effective_date")
        if self.official_effective_date and self.source_date != self.official_effective_date:
            issues.append("effective_date_differs_source_date")
        if self.document_verified and (self.source != "official_document" or not self.raw.get("reviewer") or not self.raw.get("evidence_locator")):
            issues.append("unsupported_document_verification")
        self.issues = sorted(set(issues))
        return self

    @property
    def valid(self):
        blocking = {"invalid_price", "unexpected_unit", "source_date_invalid", "future_source_date", "publication_date_invalid", "official_effective_date_invalid", "invalid_timestamp", "future_publication", "unsupported_document_verification"}
        return not bool(set(self.issues) & blocking)

    def semantic(self):
        record = asdict(self)
        record.pop("row_key")
        return json.dumps(record, sort_keys=True, ensure_ascii=False, default=str)

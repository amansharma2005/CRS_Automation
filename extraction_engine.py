"""
AI Document Processing System - Core Extraction Engine
======================================================
Handles OCR cleaning, LLM-based extraction, validation,
and self-correction for industrial blower test certificates.
"""

import re
import json
import logging
from typing import Optional
from datetime import datetime

from openai import AsyncOpenAI
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# DATA SCHEMA (Pydantic)
# ─────────────────────────────────────────────

class ExtractedDocument(BaseModel):
    company_name: Optional[str] = None
    client_code: Optional[str] = None
    crs_serial_number: Optional[str] = None
    crs_date: Optional[str] = None
    dispatch_date: Optional[str] = None
    offer_number: Optional[str] = None
    offer_date: Optional[str] = None
    proforma_invoice: Optional[str] = None
    invoice_date: Optional[str] = None
    blower_model: Optional[str] = None
    capacity: Optional[str] = None
    pressure: Optional[str] = None
    motor_power_kw: Optional[str] = None
    motor_power_hp: Optional[str] = None
    speed_rpm: Optional[str] = None
    motor_rating_speed_rpm: Optional[str] = None
    max_speed_rpm: Optional[str] = None
    power_consumption_bhp: Optional[str] = None
    flow_direction: Optional[str] = None

    @field_validator("crs_date", "dispatch_date", "offer_date", "invoice_date", mode="before")
    @classmethod
    def normalize_date(cls, v):
        if not v or v == "null":
            return None
        return _parse_date(str(v))

    class Config:
        extra = "ignore"


def _parse_date(raw: str) -> Optional[str]:
    """Try multiple date formats and return YYYY-MM-DD."""
    formats = [
        "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d",
        "%d.%m.%Y", "%d-%b-%Y", "%d/%b/%Y",
        "%B %d, %Y", "%d %B %Y", "%d %b %Y",
    ]
    raw = raw.strip()
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Return as-is if unparseable but looks like a date
    if re.search(r"\d{2,4}[\/\-\.]\d{2}[\/\-\.]\d{2,4}", raw):
        return raw
    return raw if raw else None


# ─────────────────────────────────────────────
# OCR PRE-PROCESSOR
# ─────────────────────────────────────────────

class OCRCleaner:
    """Cleans raw OCR text before sending to LLM."""

    # Common OCR broken-word patterns specific to blower certificates
    CORRECTIONS = {
        r"\bT\s+win\b": "Twin",
        r"\bB\s+lower\b": "Blower",
        r"\bC\s+RS\b": "CRS",
        r"\bR\s+PM\b": "RPM",
        r"\bB\s+HP\b": "BHP",
        r"\bK\s+W\b": "KW",
        r"\bH\s+P\b": "HP",
        r"\bD\s+ate\b": "Date",
        r"\bS\s+erial\b": "Serial",
        r"\bN\s+o\b\.?": "No.",
        r"\bI\s+nvoice\b": "Invoice",
        r"\bD\s+ispatch\b": "Dispatch",
        r"\bO\s+ffer\b": "Offer",
        r"\bP\s+roforma\b": "Proforma",
        r"\bC\s+apacity\b": "Capacity",
        r"\bP\s+ressure\b": "Pressure",
        r"\bS\s+peed\b": "Speed",
        r"\bF\s+low\b": "Flow",
        r"\bD\s+irection\b": "Direction",
        r"\bC\s+lient\b": "Client",
        r"\bC\s+ode\b": "Code",
        r"\bM\s+odel\b": "Model",
        r"\bP\s+ower\b": "Power",
        r"\bC\s+onsumption\b": "Consumption",
    }

    @classmethod
    def clean(cls, raw_text: str) -> str:
        text = raw_text

        # Fix broken words
        for pattern, replacement in cls.CORRECTIONS.items():
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

        # Remove null bytes and special chars
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

        # Normalize multiple spaces → single space
        text = re.sub(r"[ \t]+", " ", text)

        # Normalize multiple newlines → max 2
        text = re.sub(r"\n{3,}", "\n\n", text)

        # Fix common OCR symbol mistakes
        text = text.replace("|", "I").replace("0ffice", "Office")
        text = text.replace("l/", "1/").replace("O/", "0/")

        return text.strip()


# ─────────────────────────────────────────────
# LLM EXTRACTION ENGINE
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert document data extraction AI specialized in industrial blower test certificates.

Your task: Extract structured fields from OCR text of manufacturing/quality documents.

DOCUMENT LAYOUT CONTEXT:
These documents (Contract Review Sheets / CRS) typically have a tabular layout with:
- LEFT columns: Blower specifications (Capacity, Pressure, Speed, Power Consumption, Maximum Speed)
- RIGHT columns: Motor Rating details (KW, HP, Motor Speed, Flow Direction)

CRITICAL — SPEED FIELDS (there are multiple speed values, do NOT confuse them):
- "speed_rpm" = the BLOWER operating speed. This is labeled "Speed" in the left/main blower specifications column.
  It is typically a value like 1472, 1450, 2900 RPM etc. Extract ONLY the numeric value with unit.
- "motor_speed_rpm" = the MOTOR rated speed. This appears in the Motor Rating column, also labeled "Speed".
  It is typically a round number like 1500, 3000, 1000 RPM. Extract ONLY the numeric value with unit.
- "max_speed_rpm" = the MAXIMUM blower speed. Labeled "Maximum Speed" or "Max Speed" in the left column.

All three speed fields are DIFFERENT values. Pay close attention to which column/section each value comes from.

STRICT RULES:
1. Return ONLY valid JSON matching the exact schema provided
2. Use null (not "null" string) for missing fields
3. Normalize dates to YYYY-MM-DD format
4. Fix OCR artifacts (broken words, spacing errors)
5. Do NOT hallucinate values
6. Do NOT include any text outside the JSON object
7. Preserve units exactly (RPM, KW, BHP, HP, Kg/cm²)
8. "CRS Sr. No." maps to crs_serial_number
9. Ignore tables of components, parts lists, and signature blocks
10. For speed_rpm: ALWAYS use the blower speed from the LEFT column, NOT the motor speed from Motor Rating

FIELD MAPPINGS (handle variations):
- company_name: The manufacturing company/organization name (at top of document)
- client_code: Client Code, Customer Code
- crs_serial_number: CRS Sr. No., CRS Serial Number, Certificate Serial No.
- crs_date: CRS Date, Certificate Date (usually "Dated" next to CRS Sr. No.)
- dispatch_date: Dispatch Date, Date of Dispatch
- offer_number: Offer No., Offer Number, Quote No.
- offer_date: Offer Date, Date of Offer
- proforma_invoice: Proforma Invoice No., PI No., Invoice Reference
- invoice_date: Invoice Date, Date of Invoice (date from Proforma Invoice line)
- blower_model: Blower Model, Model No., Equipment Model (e.g. "Twin Lobe Air Cooled AB-59")
- capacity: Capacity with units (e.g., "600 M3/Hr")
- pressure: Pressure with units (e.g., "0.5 Kg/cm²")
- motor_power_kw: Motor Power/Rating in KW (e.g., "15.00 KW")
- motor_power_hp: Motor Power/Rating in HP (e.g., "20.00 HP")
- speed_rpm: BLOWER operating speed in RPM (from left column, e.g., "1472 RPM") — NOT the motor speed
- motor_speed_rpm: MOTOR rated speed in RPM (from Motor Rating section, e.g., "1500 RPM")
- max_speed_rpm: Maximum Speed in RPM (e.g., "1537 RPM")
- power_consumption_bhp: Power Consumption in BHP (e.g., "16.95 BHP")
- flow_direction: Flow Direction (Horizontal, Vertical, CW, CCW, Clockwise, etc.)
"""

USER_PROMPT_TEMPLATE = """Extract data from this OCR document text. Return ONLY JSON.

IMPORTANT: This document may contain TWO different "Speed" values:
1. Blower Speed (in blower specs section) → put in "speed_rpm"
2. Motor Speed (in Motor Rating section) → put in "motor_speed_rpm"
Do NOT confuse them. The blower speed and motor speed are usually different numbers.

SCHEMA:
{{
  "company_name": null,
  "client_code": null,
  "crs_serial_number": null,
  "crs_date": null,
  "dispatch_date": null,
  "offer_number": null,
  "offer_date": null,
  "proforma_invoice": null,
  "invoice_date": null,
  "blower_model": null,
  "capacity": null,
  "pressure": null,
  "motor_power_kw": null,
  "motor_power_hp": null,
  "speed_rpm": null,
  "motor_speed_rpm": null,
  "max_speed_rpm": null,
  "power_consumption_bhp": null,
  "flow_direction": null
}}

OCR TEXT:
---
{ocr_text}
---

Return ONLY the JSON object. No explanation. No markdown fences."""


# ─────────────────────────────────────────────
# SELF-CORRECTION VALIDATOR
# ─────────────────────────────────────────────

class SelfCorrector:
    """Validates extracted data and flags anomalies."""

    NUMERIC_FIELDS = {
        "motor_power_kw", "motor_power_hp",
        "speed_rpm", "max_speed_rpm", "power_consumption_bhp"
    }

    DATE_FIELDS = {"crs_date", "dispatch_date", "offer_date", "invoice_date"}

    @classmethod
    def validate_and_flag(cls, data: dict) -> tuple[dict, list[str]]:
        warnings = []

        for field in cls.DATE_FIELDS:
            val = data.get(field)
            if val and not re.match(r"\d{4}-\d{2}-\d{2}", str(val)):
                warnings.append(f"Date field '{field}' may not be normalized: {val}")

        # Check speed consistency
        speed = data.get("speed_rpm")
        max_speed = data.get("max_speed_rpm")
        if speed and max_speed:
            try:
                s = float(re.sub(r"[^\d.]", "", str(speed)))
                ms = float(re.sub(r"[^\d.]", "", str(max_speed)))
                if s > ms:
                    warnings.append(
                        f"speed_rpm ({s}) > max_speed_rpm ({ms}) — possible OCR swap"
                    )
            except ValueError:
                pass

        # Check KW/HP consistency (1 KW ≈ 1.341 HP)
        kw_val = data.get("motor_power_kw")
        hp_val = data.get("motor_power_hp")
        if kw_val and hp_val:
            try:
                kw = float(re.sub(r"[^\d.]", "", str(kw_val)))
                hp = float(re.sub(r"[^\d.]", "", str(hp_val)))
                ratio = hp / kw if kw > 0 else 0
                if not (1.2 < ratio < 1.5):
                    warnings.append(
                        f"KW/HP ratio anomaly: {kw}KW vs {hp}HP (expected ~1.341 ratio)"
                    )
            except ValueError:
                pass

        return data, warnings


# ─────────────────────────────────────────────
# MAIN EXTRACTION ENGINE
# ─────────────────────────────────────────────

class DocumentExtractionEngine:
    """
    Main engine coordinating: clean → extract → validate → correct.
    """

    def __init__(self, openai_client: AsyncOpenAI, model: str = "gpt-4o"):
        self.client = openai_client
        self.model = model
        self.cleaner = OCRCleaner()
        self.corrector = SelfCorrector()

    async def extract(self, raw_ocr_text: str) -> dict:
        """
        Full pipeline:
        1. Pre-clean OCR text
        2. LLM extraction
        3. Parse & validate JSON
        4. Self-correction pass
        5. Pydantic validation
        """
        # Step 1: Clean
        cleaned_text = self.cleaner.clean(raw_ocr_text)
        logger.info(f"OCR cleaned: {len(raw_ocr_text)} → {len(cleaned_text)} chars")

        # Step 2: LLM Extraction
        raw_json = await self._llm_extract(cleaned_text)

        # Step 3: Parse JSON
        extracted = self._safe_parse_json(raw_json)

        # Step 4: Self-correction
        extracted, warnings = self.corrector.validate_and_flag(extracted)
        if warnings:
            logger.warning(f"Validation warnings: {warnings}")
            # Re-run extraction with warnings as context if needed
            if any("swap" in w for w in warnings):
                extracted = self._correct_swapped_fields(extracted)

        # Step 5: Pydantic validation (enforce schema)
        try:
            doc = ExtractedDocument(**extracted)
            result = doc.model_dump()
        except Exception as e:
            logger.error(f"Schema validation error: {e}")
            result = extracted  # Return best-effort result

        return {
            "extracted_data": result,
            "warnings": warnings,
            "ocr_char_count": len(raw_ocr_text),
            "cleaned_char_count": len(cleaned_text),
        }

    async def _llm_extract(self, cleaned_text: str) -> str:
        """Call OpenAI to extract structured fields."""
        prompt = USER_PROMPT_TEMPLATE.format(ocr_text=cleaned_text[:12000])  # token safety

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0,          # deterministic
            max_tokens=1500,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content

    def _safe_parse_json(self, raw: str) -> dict:
        """Parse JSON with fallback cleanup."""
        if not raw:
            return self._empty_schema()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Strip markdown fences if present
            cleaned = re.sub(r"```(?:json)?", "", raw).strip().strip("`")
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                logger.error("Failed to parse LLM JSON response")
                return self._empty_schema()

    def _correct_swapped_fields(self, data: dict) -> dict:
        """Swap speed_rpm and max_speed_rpm if values are inverted."""
        speed = data.get("speed_rpm")
        max_speed = data.get("max_speed_rpm")
        if speed and max_speed:
            try:
                s = float(re.sub(r"[^\d.]", "", str(speed)))
                ms = float(re.sub(r"[^\d.]", "", str(max_speed)))
                if s > ms:
                    logger.info("Auto-correcting swapped speed fields")
                    data["speed_rpm"], data["max_speed_rpm"] = max_speed, speed
            except ValueError:
                pass
        return data

    @staticmethod
    def _empty_schema() -> dict:
        return {k: None for k in ExtractedDocument.model_fields.keys()}

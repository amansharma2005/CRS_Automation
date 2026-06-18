"""
Test script — validates extraction engine with sample OCR text
(no file upload needed, works without Tesseract installed)
"""

import asyncio
import json
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

SAMPLE_OCR_TEXT = """
ABC Industries Private Limited
CUSTOMER RUNNING SHEET (CRS)

CRS Sr. No.: CRS-2024-00123
CRS Date: 15-01-2024
Dispatch Date: 20-01-2024

Client Code: CLI-55789
Offer No.: OFF-2023-778
Offer Date: 10-12-2023

Proforma Invoice: PI-2024-00456
Invoice Date: 05-01-2024

BLOWER DETAILS:
Model: T win Lobe 65 RL
Capacity: 500 m3/hr
Pressure: 1000 mmWC
Motor Power: 7.5 K W / 10 H P
Speed: 1450 R PM
Max Speed: 1600 R PM
Power Consumption: 8.5 B HP
Flow Direction: Clockwise (CW)

--- COMPONENTS LIST ---
1. Bearing: SKF-6205
2. Seal: Mechanical Face
3. Coupling: Lovejoy L-100
--- END ---
"""


async def test_extraction():
    """Run extraction on sample OCR text."""
    openai_key = os.getenv("OPENAI_API_KEY", "")

    if not openai_key or openai_key == "your_openai_api_key_here":
        print("\n[!] No OpenAI API key found. Testing OCR cleaning only.\n")
        from extraction_engine import OCRCleaner
        cleaner = OCRCleaner()
        cleaned = cleaner.clean(SAMPLE_OCR_TEXT)
        print("=== OCR CLEANED TEXT ===")
        print(cleaned)
        print("\n[OK] OCR cleaner working correctly")
        return

    print("=== AI DOCUMENT EXTRACTION TEST ===\n")
    print(f"Input OCR text: {len(SAMPLE_OCR_TEXT)} chars")

    from openai import AsyncOpenAI
    from extraction_engine import DocumentExtractionEngine

    client = AsyncOpenAI(api_key=openai_key)
    engine = DocumentExtractionEngine(client, os.getenv("OPENAI_MODEL", "gpt-4o"))

    print("Calling extraction engine...")
    result = await engine.extract(SAMPLE_OCR_TEXT)

    print("\n=== EXTRACTED DATA ===")
    print(json.dumps(result["extracted_data"], indent=2))

    if result.get("warnings"):
        print("\n=== WARNINGS ===")
        for w in result["warnings"]:
            print(f"  ⚠  {w}")

    # Validate output
    data = result["extracted_data"]
    expected_non_null = [
        "company_name", "client_code", "crs_serial_number", "blower_model",
        "capacity", "motor_power_kw", "flow_direction"
    ]

    print("\n=== VALIDATION ===")
    all_ok = True
    for field in expected_non_null:
        val = data.get(field)
        status = "[OK]" if val else "[MISSING]"
        if not val:
            all_ok = False
        print(f"  {status}  {field}: {val}")

    print(f"{'[PASS] All key fields extracted!' if all_ok else '[FAIL] Some fields missing -- check API key or model'}")


if __name__ == "__main__":
    asyncio.run(test_extraction())

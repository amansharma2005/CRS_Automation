"""
AI Document Processing System - FastAPI Backend
=================================================
REST API providing document upload, OCR, and extraction endpoints.
"""

import os
import re
import uuid
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

import httpx

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI
from dotenv import load_dotenv

from ocr_service import OCRService, FileTypeDetector
from extraction_engine import DocumentExtractionEngine
from sheets_service import GoogleSheetsService


# ─────────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────────

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# APP LIFESPAN
# ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup."""
    openai_key = os.getenv("OPENAI_API_KEY", "")
    model = os.getenv("OPENAI_MODEL", "gpt-4o")

    app.state.ocr_service = OCRService(
        tesseract_cmd=os.getenv("TESSERACT_CMD"),
        poppler_path=os.getenv("POPPLER_PATH"),
    )

    if openai_key and openai_key != "your_openai_api_key_here":
        client = AsyncOpenAI(api_key=openai_key)
        app.state.extraction_engine = DocumentExtractionEngine(client, model)
        app.state.llm_available = True
        logger.info(f"LLM engine ready: {model}")
    else:
        app.state.extraction_engine = None
        app.state.llm_available = False
        logger.warning("No OpenAI API key — running in OCR-only mode")

    logger.info("AI Document Processing System started ✓")
    yield
    logger.info("System shutdown")


# ─────────────────────────────────────────────
# FASTAPI APP
# ─────────────────────────────────────────────

app = FastAPI(
    title="AI Document Processing System",
    description="Autonomous OCR + LLM extraction for industrial test certificates",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static frontend
app.mount("/static", StaticFiles(directory="static"), name="static")


# ─────────────────────────────────────────────
# GOOGLE DRIVE HELPER
# ─────────────────────────────────────────────

# Patterns to extract the file ID from various Google Drive URL formats
_DRIVE_PATTERNS = [
    # https://drive.google.com/file/d/FILE_ID/view?usp=sharing
    re.compile(r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)"),
    # https://drive.google.com/open?id=FILE_ID
    re.compile(r"drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)"),
    # https://drive.google.com/uc?id=FILE_ID&export=download
    re.compile(r"drive\.google\.com/uc\?.*id=([a-zA-Z0-9_-]+)"),
    # https://docs.google.com/document/d/FILE_ID/...
    re.compile(r"docs\.google\.com/\w+/d/([a-zA-Z0-9_-]+)"),
]


def _extract_drive_file_id(url: str) -> str | None:
    """Extract the Google Drive file ID from various link formats."""
    for pattern in _DRIVE_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    return None


async def _download_from_drive(url: str) -> tuple[bytes, str]:
    """
    Download a file from a Google Drive sharing link.
    Returns (file_bytes, guessed_filename).
    Handles the large-file confirmation page automatically.
    """
    file_id = _extract_drive_file_id(url)
    if not file_id:
        raise ValueError(
            "Invalid Google Drive link. Supported formats:\n"
            "  • https://drive.google.com/file/d/FILE_ID/view?usp=sharing\n"
            "  • https://drive.google.com/open?id=FILE_ID"
        )

    direct_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    logger.info(f"Downloading from Google Drive: file_id={file_id}")

    async with httpx.AsyncClient(follow_redirects=True, timeout=120.0) as client:
        # First request — may get a confirmation page for large files
        resp = await client.get(direct_url)
        resp.raise_for_status()

        # Check for the "virus scan warning" confirmation page
        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type:
            # Google is showing a confirmation page; extract confirm token
            confirm_match = re.search(
                r'confirm=([0-9A-Za-z_-]+)', resp.text
            )
            if confirm_match:
                confirm_token = confirm_match.group(1)
                confirmed_url = f"{direct_url}&confirm={confirm_token}"
                resp = await client.get(confirmed_url)
                resp.raise_for_status()
            else:
                # Try the direct download with confirm=t (works for most cases)
                confirmed_url = f"{direct_url}&confirm=t"
                resp = await client.get(confirmed_url)
                resp.raise_for_status()

        file_bytes = resp.content

        if len(file_bytes) < 100:
            raise ValueError(
                "Downloaded file is too small — the Drive link may be invalid, "
                "the file may not be publicly shared, or access is restricted.\n"
                "Make sure the file sharing is set to 'Anyone with the link'."
            )

        # Try to extract filename from Content-Disposition header
        filename = "drive_document.pdf"
        cd = resp.headers.get("content-disposition", "")
        fname_match = re.search(r'filename="?([^";\']+)', cd)
        if fname_match:
            filename = fname_match.group(1).strip()

        logger.info(f"Drive download complete: {filename} ({len(file_bytes)} bytes)")
        return file_bytes, filename


# ─────────────────────────────────────────────
# PROCESSING HISTORY (In-memory store)
# ─────────────────────────────────────────────

processing_history: list[dict] = []
MAX_HISTORY = 50


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Serve the main UI."""
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/api/health")
async def health_check(request: Request):
    """System health check."""
    return {
        "status": "online",
        "llm_available": request.app.state.llm_available,
        "version": "1.0.0",
        "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
    }


@app.post("/api/extract")
async def extract_document(
    request: Request,
    file: Optional[UploadFile] = File(None),
    raw_text: Optional[str] = Form(None),
    drive_link: Optional[str] = Form(None),
    crs_number: Optional[str] = Form(None),
):
    """
    Main extraction endpoint.
    Accepts: image file, PDF file, raw OCR text, Google Drive link, or CRS Number.
    Returns: structured JSON with extracted fields.
    """
    start_time = time.time()
    job_id = str(uuid.uuid4())[:8]

    # Dynamically reload environment variables (picks up spreadsheet ID changes instantly)
    load_dotenv(override=True)

    logger.info(f"[{job_id}] New extraction request")

    # ── 1. Get raw OCR text ──────────────────
    ocr_text = ""
    source_type = "unknown"
    filename = "unknown"

    active_drive_link = drive_link
    if crs_number and crs_number.strip():
        # Search spreadsheet for CRS drive link
        spreadsheet_id = os.getenv("GOOGLE_SPREADSHEET_ID")
        try:
            active_drive_link = await GoogleSheetsService.get_drive_link_by_crs(
                crs_number.strip(),
                spreadsheet_id=spreadsheet_id
            )
            source_type = "crs_lookup"
            filename = f"crs_{crs_number.strip()}.pdf"
            logger.info(f"[{job_id}] CRS '{crs_number}' resolved to drive link: {active_drive_link}")
        except Exception as e:
            logger.error(f"[{job_id}] CRS resolution failed: {e}")
            raise HTTPException(status_code=400, detail=str(e))

    if active_drive_link and active_drive_link.strip():
        # ── Google Drive link mode (or CRS resolved mode) ──────────────
        try:
            file_bytes, dl_filename = await _download_from_drive(active_drive_link.strip())
            if source_type != "crs_lookup":
                source_type = "google_drive"
                filename = dl_filename
            doc_type = FileTypeDetector.detect(file_bytes, filename)
            logger.info(
                f"[{job_id}] Processing Drive {doc_type}: {filename} ({len(file_bytes)} bytes)"
            )

            ocr_service = request.app.state.ocr_service
            if doc_type == "pdf":
                ocr_text = ocr_service.extract_from_pdf_bytes(file_bytes, filename)
            elif doc_type == "text":
                ocr_text = file_bytes.decode("utf-8", errors="replace")
            else:
                ocr_text = ocr_service.extract_from_image_bytes(file_bytes, filename)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except httpx.HTTPStatusError as e:
            logger.error(f"[{job_id}] Drive download HTTP error: {e}")
            raise HTTPException(
                status_code=502,
                detail=f"Failed to download from Google Drive: HTTP {e.response.status_code}"
            )
        except Exception as e:
            logger.error(f"[{job_id}] Drive download failed: {e}")
            raise HTTPException(status_code=502, detail=f"Drive download failed: {str(e)}")

    elif file and file.filename:
        filename = file.filename
        file_bytes = await file.read()
        doc_type = FileTypeDetector.detect(file_bytes, filename)
        logger.info(f"[{job_id}] Processing {doc_type} file: {filename} ({len(file_bytes)} bytes)")

        try:
            ocr_service = request.app.state.ocr_service
            if doc_type == "pdf":
                ocr_text = ocr_service.extract_from_pdf_bytes(file_bytes, filename)
                source_type = "pdf"
            elif doc_type == "text":
                ocr_text = file_bytes.decode("utf-8", errors="replace")
                source_type = "text_file"
            else:
                ocr_text = ocr_service.extract_from_image_bytes(file_bytes, filename)
                source_type = "image"
        except Exception as e:
            logger.error(f"[{job_id}] OCR failed: {e}")
            raise HTTPException(status_code=422, detail=f"OCR processing failed: {str(e)}")

    elif raw_text:
        ocr_text = raw_text
        source_type = "raw_text"
        filename = "text_input"
        logger.info(f"[{job_id}] Processing raw text ({len(raw_text)} chars)")

    else:
        raise HTTPException(
            status_code=400,
            detail="Provide a file, raw_text, or a Google Drive link"
        )

    if not ocr_text.strip():
        raise HTTPException(status_code=422, detail="No text could be extracted from document")

    # ── 2. LLM Extraction ───────────────────
    if not request.app.state.llm_available:
        raise HTTPException(
            status_code=503,
            detail="LLM not configured. Add OPENAI_API_KEY to .env file."
        )

    try:
        engine: DocumentExtractionEngine = request.app.state.extraction_engine
        result = await engine.extract(ocr_text)
    except Exception as e:
        logger.error(f"[{job_id}] Extraction engine error: {e}")
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")

    # ── 3. Build response ───────────────────
    elapsed = round(time.time() - start_time, 2)
    fields_extracted = sum(
        1 for v in result["extracted_data"].values() if v is not None
    )

    # ── 4. Auto-export to Google Sheets ───
    auto_export_status = "disabled"
    spreadsheet_id = os.getenv("GOOGLE_SPREADSHEET_ID")
    if spreadsheet_id:
        try:
            logger.info(f"[{job_id}] Auto-exporting to Google Sheets ID: {spreadsheet_id}")
            export_data = result["extracted_data"].copy()
            sheet_name = None
            if crs_number and crs_number.strip():
                export_data["crs_number"] = crs_number.strip()
                sheet_name = "CRS Extracted Data"

            await GoogleSheetsService.export_to_sheets(
                data=export_data,
                spreadsheet_id=spreadsheet_id,
                sheet_name=sheet_name
            )
            auto_export_status = "success"
            logger.info(f"[{job_id}] Auto-export successful!")
        except Exception as e:
            auto_export_status = f"failed: {str(e)}"
            logger.error(f"[{job_id}] Auto-export failed: {e}")

    response = {
        "job_id": job_id,
        "status": "success",
        "filename": filename,
        "source_type": source_type,
        "processing_time_seconds": elapsed,
        "ocr_char_count": result.get("ocr_char_count", len(ocr_text)),
        "cleaned_char_count": result.get("cleaned_char_count", 0),
        "warnings": result.get("warnings", []),
        "fields_extracted": fields_extracted,
        "extracted_data": result["extracted_data"],
        "auto_export_status": auto_export_status,
    }

    # Store in history
    processing_history.insert(0, {
        "job_id": job_id,
        "filename": filename,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "processing_time": elapsed,
        "warning_count": len(result.get("warnings", [])),
        "fields_extracted": fields_extracted,
        "auto_export_status": auto_export_status,
    })
    if len(processing_history) > MAX_HISTORY:
        processing_history.pop()

    logger.info(f"[{job_id}] Done in {elapsed}s — {fields_extracted}/18 fields extracted (sheets: {auto_export_status})")

    return JSONResponse(content=response)


@app.post("/api/extract/text")
async def extract_from_text(request: Request):
    """Extract from plain JSON body with ocr_text field."""
    body = await request.json()
    raw_text = body.get("ocr_text", "")
    if not raw_text:
        raise HTTPException(status_code=400, detail="ocr_text field required")

    fake_form = type("Req", (), {"app": request.app})()
    # Reuse main extraction logic
    from fastapi import Form as F
    return await extract_document(request, file=None, raw_text=raw_text)


@app.post("/api/extract/drive")
async def extract_from_drive(request: Request):
    """Extract from a Google Drive link provided in JSON body."""
    body = await request.json()
    drive_link = body.get("drive_link", "")
    if not drive_link:
        raise HTTPException(status_code=400, detail="drive_link field required")
    return await extract_document(request, file=None, raw_text=None, drive_link=drive_link)


@app.post("/api/extract/crs")
async def extract_from_crs(request: Request):
    """Extract from a CRS Number provided in JSON body."""
    body = await request.json()
    crs_number = body.get("crs_number", "")
    if not crs_number:
        raise HTTPException(status_code=400, detail="crs_number field required")
    return await extract_document(request, file=None, raw_text=None, drive_link=None, crs_number=crs_number)


@app.get("/api/history")
async def get_history():
    """Return recent processing history."""
    return {"history": processing_history, "total": len(processing_history)}


@app.post("/api/export/sheets")
async def export_to_google_sheets(request: Request):
    """
    Export extracted data to Google Sheets.
    """
    body = await request.json()
    extracted_data = body.get("extracted_data")
    if not extracted_data:
        raise HTTPException(status_code=400, detail="extracted_data is required")

    load_dotenv(override=True)
    webapp_url = body.get("webapp_url")
    spreadsheet_id = body.get("spreadsheet_id") or os.getenv("GOOGLE_SPREADSHEET_ID")
    sheet_name = body.get("sheet_name")

    if not spreadsheet_id and not webapp_url:
        raise HTTPException(status_code=400, detail="Google Spreadsheet ID not configured on server.")

    try:
        res = await GoogleSheetsService.export_to_sheets(
            data=extracted_data,
            webapp_url=webapp_url,
            spreadsheet_id=spreadsheet_id,
            sheet_name=sheet_name
        )
        return res
    except Exception as e:
        logger.error(f"Google Sheets export failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/history")
async def clear_history():
    """Clear processing history."""
    processing_history.clear()
    return {"status": "cleared"}


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", 8000)),
        reload=os.getenv("DEBUG", "true").lower() == "true",
        log_level="info",
    )

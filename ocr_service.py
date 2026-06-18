"""
AI Document Processing System - OCR Service
=============================================
Handles file ingestion (PDF + Images) and raw text extraction
using Tesseract OCR with Pillow pre-processing for quality improvement.
"""

import io
import os
import logging
from pathlib import Path
from typing import Optional

from PIL import Image, ImageEnhance, ImageFilter
import pytesseract

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# TESSERACT CONFIGURATION
# ─────────────────────────────────────────────

def configure_tesseract(tesseract_cmd: Optional[str] = None):
    """Set Tesseract executable path."""
    path = tesseract_cmd or os.getenv(
        "TESSERACT_CMD",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    )
    if Path(path).exists():
        pytesseract.pytesseract.tesseract_cmd = path
        logger.info(f"Tesseract configured: {path}")
    else:
        logger.warning(
            f"Tesseract not found at {path}. "
            "OCR will fall back to system PATH."
        )


TESSERACT_CONFIG = "--oem 3 --psm 6 -l eng"
"""
OEM 3 = LSTM + legacy engine
PSM 6 = Assume a single uniform block of text (good for certificates)
"""


# ─────────────────────────────────────────────
# IMAGE PRE-PROCESSOR
# ─────────────────────────────────────────────

class ImagePreprocessor:
    """Enhance image quality before OCR for better accuracy."""

    @staticmethod
    def preprocess(img: Image.Image) -> Image.Image:
        """Apply a processing pipeline optimized for document OCR."""
        # Convert to grayscale
        img = img.convert("L")

        # Increase resolution (300 DPI equivalent upscaling)
        scale = 2
        new_size = (img.width * scale, img.height * scale)
        img = img.resize(new_size, Image.LANCZOS)

        # Enhance sharpness
        sharpener = ImageEnhance.Sharpness(img)
        img = sharpener.enhance(2.0)

        # Enhance contrast
        contraster = ImageEnhance.Contrast(img)
        img = contraster.enhance(1.5)

        # Apply slight median filter to reduce noise
        img = img.filter(ImageFilter.MedianFilter(size=1))

        # Threshold (binarize) for clean black/white
        img = img.point(lambda x: 0 if x < 140 else 255, "1")
        img = img.convert("L")  # Back to grayscale for Tesseract

        return img


# ─────────────────────────────────────────────
# OCR SERVICE
# ─────────────────────────────────────────────

# Auto-detect local Poppler extracted next to this script
_SCRIPT_DIR = Path(__file__).parent
_LOCAL_POPPLER_CANDIDATES = [
    _SCRIPT_DIR / "poppler_extracted" / "poppler-24.08.0" / "Library" / "bin",
    _SCRIPT_DIR / "poppler" / "Library" / "bin",
]


def _find_poppler() -> Optional[str]:
    """Return Poppler bin path: env var → local folder → None (use system PATH)."""
    from_env = os.getenv("POPPLER_PATH", "").strip()
    if from_env and Path(from_env).exists():
        return from_env
    for candidate in _LOCAL_POPPLER_CANDIDATES:
        if candidate.exists():
            logger.info(f"Auto-detected local Poppler: {candidate}")
            return str(candidate)
    return None


class OCRService:
    """Handles OCR extraction from images and PDFs."""

    def __init__(self, tesseract_cmd: Optional[str] = None,
                 poppler_path: Optional[str] = None):
        configure_tesseract(tesseract_cmd)
        self.poppler_path = poppler_path or _find_poppler()
        if self.poppler_path:
            logger.info(f"Poppler path: {self.poppler_path}")
        else:
            logger.warning("Poppler not found — PDF OCR may fail on Windows")
        self.preprocessor = ImagePreprocessor()

    # ── Public API ─────────────────────────────

    def extract_from_image_bytes(self, image_bytes: bytes, filename: str = "") -> str:
        """Extract text from image file bytes."""
        try:
            img = Image.open(io.BytesIO(image_bytes))
            return self._ocr_image(img, filename)
        except Exception as e:
            logger.error(f"Image OCR failed for {filename}: {e}")
            raise

    def extract_from_pdf_bytes(self, pdf_bytes: bytes, filename: str = "") -> str:
        """
        Extract text from all pages of a PDF.
        Strategy:
          1. Try PyMuPDF direct text extraction (fast, no Tesseract needed)
          2. If page has too little text (scanned image PDF), fall back to Tesseract OCR
        """
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            all_text = []
            ocr_pages = []

            for page_num, page in enumerate(doc, 1):
                page_text = page.get_text().strip()
                if len(page_text) >= 80:
                    # Sufficient text extracted directly — no OCR needed
                    logger.info(f"PyMuPDF direct text: page {page_num} ({len(page_text)} chars)")
                    all_text.append(f"--- PAGE {page_num} ---\n{page_text}")
                else:
                    # Page appears to be a scanned image — mark for OCR
                    logger.info(f"Page {page_num} sparse ({len(page_text)} chars) — queued for OCR")
                    ocr_pages.append((page_num, page_text))

            # OCR fallback for scanned pages
            if ocr_pages:
                logger.info(f"Running Tesseract OCR on {len(ocr_pages)} scanned page(s)")
                ocr_images = self._pdf_to_images(pdf_bytes)
                for page_num, _ in ocr_pages:
                    img = ocr_images[page_num - 1]
                    ocr_text = self._ocr_image(img, f"{filename}_p{page_num}")
                    all_text.append(f"--- PAGE {page_num} (OCR) ---\n{ocr_text}")

            full_text = "\n\n".join(all_text)
            logger.info(f"PDF extraction complete: {len(doc)} pages, {len(full_text)} total chars")
            return full_text

        except ImportError:
            # PyMuPDF not available — go straight to Tesseract OCR
            logger.warning("PyMuPDF not available, using Tesseract OCR for all pages")
            return self._ocr_all_pages(pdf_bytes, filename)
        except Exception as e:
            logger.error(f"PDF extraction failed for {filename}: {e}")
            raise

    def _ocr_all_pages(self, pdf_bytes: bytes, filename: str) -> str:
        """Full OCR pipeline for all pages (fallback when PyMuPDF unavailable)."""
        images = self._pdf_to_images(pdf_bytes)
        all_text = []
        for page_num, img in enumerate(images, 1):
            logger.info(f"OCR processing page {page_num}/{len(images)}: {filename}")
            page_text = self._ocr_image(img, f"{filename}_p{page_num}")
            all_text.append(f"--- PAGE {page_num} ---\n{page_text}")
        return "\n\n".join(all_text)



    def extract_from_text(self, text: str) -> str:
        """Pass-through for raw OCR text (already extracted)."""
        return text.strip()

    # ── Internal ───────────────────────────────

    def _ocr_image(self, img: Image.Image, label: str = "") -> str:
        """Run Tesseract OCR on a PIL image after preprocessing."""
        processed = self.preprocessor.preprocess(img)
        text = pytesseract.image_to_string(processed, config=TESSERACT_CONFIG)
        char_count = len(text.strip())
        logger.info(f"OCR extracted {char_count} chars from {label or 'image'}")
        return text

    def _pdf_to_images(self, pdf_bytes: bytes) -> list:
        """Convert PDF pages to PIL Images using pdf2image/poppler."""
        from pdf2image import convert_from_bytes
        kwargs = {"dpi": 300, "fmt": "PNG"}
        if self.poppler_path:
            kwargs["poppler_path"] = self.poppler_path
        try:
            images = convert_from_bytes(pdf_bytes, **kwargs)
            logger.info(f"PDF converted to {len(images)} page images")
            return images
        except Exception as e:
            err_msg = str(e)
            if "poppler" in err_msg.lower() or "pdftoppm" in err_msg.lower() or "Unable to get page count" in err_msg:
                raise RuntimeError(
                    f"Poppler not found or failed.\n"
                    f"Poppler path tried: {self.poppler_path or 'system PATH'}\n"
                    f"Error: {err_msg}\n"
                    f"Fix: Poppler is at poppler_extracted/poppler-24.08.0/Library/bin — "
                    f"set POPPLER_PATH in .env or restart the server."
                )
            raise RuntimeError(f"PDF to image conversion failed: {err_msg}")


# ─────────────────────────────────────────────
# FILE TYPE DETECTOR
# ─────────────────────────────────────────────

class FileTypeDetector:
    """Detect document type from bytes signature."""

    PDF_MAGIC = b"%PDF"
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"}
    TEXT_EXTENSIONS = {".txt"}

    @classmethod
    def detect(cls, file_bytes: bytes, filename: str) -> str:
        """Returns: 'pdf', 'image', or 'text'"""
        ext = Path(filename).suffix.lower()
        if file_bytes[:4] == cls.PDF_MAGIC:
            return "pdf"
        if ext in cls.TEXT_EXTENSIONS:
            return "text"
        if ext in cls.IMAGE_EXTENSIONS:
            return "image"
        # Fallback: try image
        return "image"

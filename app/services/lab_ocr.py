"""
OCR service for lab result documents.

Extracts text from medical report files (PDF, PNG, JPEG) supporting
French, English, and Arabic scripts via Tesseract.

PDF handling: text layer is extracted first via pypdf; if the PDF is
scanned (no embedded text), pages are rendered to images with pdf2image
and passed through Tesseract.
"""

from __future__ import annotations

import io
import logging
import tempfile
from pathlib import Path
from typing import Tuple

import pytesseract
from PIL import Image

from app.config import settings

logger = logging.getLogger(__name__)

MIN_USEFUL_TEXT_LENGTH = 50  # chars — below this OCR is treated as failed


# ─── Core OCR function (mirrors the reference pattern) ───────────────────────

def perform_ocr(image_path: str | Path, lang: str | None = None) -> str:
    """Extract text from an image file using Tesseract OCR.

    Args:
        image_path: Path to the image file (PNG, JPEG, BMP, TIFF, …).
        lang: Tesseract language string (e.g. ``fra+eng+ara``).
              Defaults to ``settings.OCR_LANGUAGES``.

    Returns:
        Extracted text, or an error message prefixed with ``Error:``.
    """
    path = Path(image_path)

    if not path.exists():
        return f"Error: File not found at {path}"

    if lang is None:
        lang = settings.OCR_LANGUAGES

    if settings.TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD

    try:
        image = Image.open(path)
        return pytesseract.image_to_string(image, lang=lang)
    except Exception as exc:
        return f"Error during OCR: {exc}"


# ─── Confidence helper ────────────────────────────────────────────────────────

def _ocr_with_confidence(image: Image.Image, lang: str) -> Tuple[str, float]:
    """
    Run OCR on a PIL Image and return (text, avg_confidence 0-1).
    Uses image_to_data to collect per-word confidence scores.
    """
    if settings.TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD

    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT, lang=lang)
    confidences = [
        int(data["conf"][i])
        for i, word in enumerate(data["text"])
        if word.strip() and int(data["conf"][i]) > 0
    ]
    text = pytesseract.image_to_string(image, lang=lang)
    avg_conf = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
    return text.strip(), avg_conf


# ─── PDF handling ─────────────────────────────────────────────────────────────

def _extract_from_pdf_bytes(file_bytes: bytes) -> Tuple[str, float]:
    """
    Extract text from a PDF.

    Strategy:
      1. Try pypdf text layer (fast, high quality for digital PDFs).
      2. Fall back to pdf2image → per-page Tesseract OCR for scanned PDFs.
    """
    # 1. Text layer via pypdf
    try:
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        pages_text = [page.extract_text() or "" for page in reader.pages]
        full_text = "\n".join(pages_text).strip()
        if len(full_text) >= MIN_USEFUL_TEXT_LENGTH:
            logger.info("PDF text-layer extraction succeeded (%d chars)", len(full_text))
            return full_text, 0.95  # digital PDF → high confidence
    except Exception as exc:
        logger.warning("pypdf text extraction failed: %s", exc)

    # 2. Scanned PDF: render pages as images, then OCR each page
    try:
        from pdf2image import convert_from_bytes

        lang = settings.OCR_LANGUAGES
        images = convert_from_bytes(file_bytes, dpi=200)
        page_texts: list[str] = []
        page_confs: list[float] = []

        for img in images:
            # Write page to a temp file so perform_ocr can open it by path
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = Path(tmp.name)
                img.save(tmp_path, format="PNG")

            text_or_err = perform_ocr(tmp_path, lang=lang)
            tmp_path.unlink(missing_ok=True)

            if text_or_err.startswith("Error:"):
                logger.warning("Page OCR error: %s", text_or_err)
                page_confs.append(0.0)
            else:
                # Re-run with confidence data for this page
                _, conf = _ocr_with_confidence(img, lang)
                page_texts.append(text_or_err)
                page_confs.append(conf)

        full_text = "\n\n".join(page_texts).strip()
        avg_conf = sum(page_confs) / len(page_confs) if page_confs else 0.0
        logger.info("PDF image-OCR fallback: %d chars, conf=%.2f", len(full_text), avg_conf)
        return full_text, avg_conf

    except Exception as exc:
        logger.error("PDF image-OCR failed: %s", exc, exc_info=True)
        return "", 0.0


# ─── Public interface ─────────────────────────────────────────────────────────

def extract_text(file_bytes: bytes, content_type: str) -> Tuple[str, float]:
    """
    Extract text from an uploaded lab result document.

    Args:
        file_bytes: Raw bytes of the uploaded file.
        content_type: MIME type (``application/pdf``, ``image/jpeg``, ``image/png``).

    Returns:
        ``(extracted_text, confidence)`` where confidence is 0–1.
        Returns ``("", 0.0)`` when extraction fails or produces too little text.
    """
    if not file_bytes:
        return "", 0.0

    ct = content_type.lower()

    if "pdf" in ct:
        text, confidence = _extract_from_pdf_bytes(file_bytes)

    elif "image" in ct:
        lang = settings.OCR_LANGUAGES
        if settings.TESSERACT_CMD:
            pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD

        try:
            img = Image.open(io.BytesIO(file_bytes))
            text, confidence = _ocr_with_confidence(img, lang)
        except Exception as exc:
            logger.error("Image OCR failed: %s", exc, exc_info=True)
            return "", 0.0

    else:
        logger.warning("Unsupported content type for OCR: %s", content_type)
        return "", 0.0

    if len(text.strip()) < MIN_USEFUL_TEXT_LENGTH:
        logger.warning("OCR text too short (%d chars) — treating as failed", len(text))
        return "", 0.0

    logger.info("OCR complete: %d chars, confidence=%.2f", len(text), confidence)
    return text.strip(), confidence


def estimate_confidence_label(ocr_confidence: float) -> str:
    """Convert a 0–1 confidence score to a HIGH / MEDIUM / LOW label."""
    if ocr_confidence >= 0.75:
        return "HIGH"
    if ocr_confidence >= 0.45:
        return "MEDIUM"
    return "LOW"

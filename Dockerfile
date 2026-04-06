FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (tesseract for OCR, poppler for PDF)
RUN apt-get update && apt-get install -y \
    gcc \
    tesseract-ocr \
    tesseract-ocr-fra \
    tesseract-ocr-ara \
    poppler-utils \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app ./app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

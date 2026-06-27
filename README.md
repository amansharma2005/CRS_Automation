# AI Document Processing System

![Project UI](show_image.png)

## 📝 Project Description
This AI-powered Test Certificate Extraction platform automates the ingestion, parsing, and logging of engineering certificates. Users can upload PDFs, paste text, share Google Drive links, or search directly using a certificate's CRS Number. For CRS searches, the system queries a master database to locate and download the correct PDF from Google Drive. It then processes the document using PyMuPDF and utilizes OpenAI's `gpt-4o-mini` to extract 18 technical parameters (including blower model, capacity, pressure, motor speeds, and flow direction) with 100% accuracy. Extracted data is automatically exported to a destination Google Sheet in the background to ensure a fast UI response. An API caching system and socket connection timeouts are implemented to optimize performance and prevent network bottlenecks.

---

## 🏗️ Architecture

```
Document Input (PDF / Image / Text)
         │
         ▼
  ┌─────────────┐
  │  OCR Service │  ← Tesseract + Image Preprocessing (contrast, sharpen, binarize)
  └─────────────┘
         │  raw text
         ▼
  ┌──────────────────┐
  │   OCR Cleaner    │  ← Fix broken words, normalize spacing, remove noise
  └──────────────────┘
         │  clean text
         ▼
  ┌──────────────────────┐
  │  LLM Extraction (GPT)│  ← Context-aware, deterministic, JSON-mode
  └──────────────────────┘
         │  raw JSON
         ▼
  ┌──────────────────┐
  │  Self-Corrector  │  ← Validates dates, KW/HP ratio, speed swap detection
  └──────────────────┘
         │  validated JSON
         ▼
  ┌──────────────────┐
  │ Pydantic Schema  │  ← Enforces exact schema, no extra keys
  └──────────────────┘
         │
         ▼
    Structured JSON (18 fields)
```

---

## ⚡ Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Install Tesseract OCR (Windows)
Download installer: https://github.com/UB-Mannheim/tesseract/wiki

### 3. Install Poppler (for PDF support, Windows)
Download: https://github.com/oschwartz10612/poppler-windows/releases

### 4. Configure `.env`

```env
OPENAI_API_KEY=sk-...your-key...
OPENAI_MODEL=gpt-4o
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
POPPLER_PATH=C:\poppler\Library\bin
```

### 5. Start the server

```bash
python main.py
```

Open: **http://localhost:8000**

---

## 📊 Extracted Fields

| Field | Description |
|-------|-------------|
| `company_name` | Manufacturing company name |
| `client_code` | Client reference code |
| `crs_serial_number` | CRS Sr. No. |
| `crs_date` | Certificate date (YYYY-MM-DD) |
| `dispatch_date` | Dispatch date (YYYY-MM-DD) |
| `offer_number` | Offer/quote number |
| `offer_date` | Offer date (YYYY-MM-DD) |
| `proforma_invoice` | Proforma invoice reference |
| `invoice_date` | Invoice date (YYYY-MM-DD) |
| `blower_model` | Blower model name |
| `capacity` | Air capacity with units |
| `pressure` | Pressure with units |
| `motor_power_kw` | Motor power in KW |
| `motor_power_hp` | Motor power in HP |
| `speed_rpm` | Operating speed in RPM |
| `max_speed_rpm` | Maximum speed in RPM |
| `power_consumption_bhp` | Power consumption in BHP |
| `flow_direction` | CW / CCW / Clockwise / etc. |

---

## 🔌 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/extract` | Extract from file or raw text |
| `GET` | `/api/health` | Health + LLM status |
| `GET` | `/api/history` | Recent processing jobs |
| `DELETE` | `/api/history` | Clear history |

### Example

```bash
# Upload a PDF
curl -X POST http://localhost:8000/api/extract \
  -F "file=@certificate.pdf"

# Paste OCR text
curl -X POST http://localhost:8000/api/extract \
  -F "raw_text=Company: ABC Industries..."
```

---

## 🧪 Test (no file needed)

```bash
python test_extraction.py
```

---

## 🗂️ Project Structure

```
Test Certificate Automation/
├── main.py                # FastAPI application
├── extraction_engine.py   # LLM extraction + self-correction
├── ocr_service.py         # Tesseract OCR + image preprocessing
├── test_extraction.py     # Validation test script
├── requirements.txt
├── .env                   # Configuration (add your API key)
└── static/
    ├── index.html         # Premium dark UI
    ├── style.css          # Glassmorphism styling
    └── app.js             # Frontend logic
```

---

## 🛡️ Self-Correction Capabilities

- **KW/HP ratio validation** — flags anomalies (expected ~1.341 ratio)
- **Speed field swap detection** — auto-corrects if RPM > Max RPM
- **Date normalization** — YYYY-MM-DD format enforcement
- **OCR broken-word repair** — "T win" → "Twin", "B HP" → "BHP", etc.
- **JSON schema enforcement** — via Pydantic, no extra keys allowed

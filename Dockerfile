# Use official Python lightweight image
FROM python:3.11-slim

# Install system dependencies (Tesseract OCR and Poppler)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy python requirements
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application files
COPY . .

# Set default host and port environment variables
ENV HOST=0.0.0.0
ENV PORT=8000
ENV DEBUG=false

# Expose port
EXPOSE 8000

# Start server
CMD ["python", "main.py"]

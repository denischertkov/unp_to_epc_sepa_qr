# UNP->EPC QR mail service: IMAP inbox, convert PDF attachments, reply via SMTP
# Build from repo root: docker build -f service/Dockerfile .
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY epc_qr.py pdf_io.py pdf_qr_extract.py unp_qr_decode.py upn_parser.py ./
COPY service/mail_service.py ./

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "mail_service.py"]

# -*- coding: utf-8 -*-
"""
Mail service: IMAP fetch, process PDF attachments with UNP->EPC QR, reply via SMTP, delete from server.
"""
import email
import imaplib
import logging
import os
import smtplib
import sys
import tempfile
import time
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# Run from repo root so parent is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pdf_io import process_pdf, format_payment_register_text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name, default).strip()
    if not v and name in (
        "IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD",
        "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD",
    ):
        raise RuntimeError(f"Missing required env: {name}")
    return v


def get_config() -> dict:
    return {
        "imap_host": _env("IMAP_HOST"),
        "imap_port": int(_env("IMAP_PORT", "993")),
        "imap_user": _env("IMAP_USER"),
        "imap_password": _env("IMAP_PASSWORD"),
        "imap_mailbox": _env("IMAP_MAILBOX", "INBOX"),
        "smtp_host": _env("SMTP_HOST"),
        "smtp_port": int(_env("SMTP_PORT", "587")),
        "smtp_user": _env("SMTP_USER"),
        "smtp_password": _env("SMTP_PASSWORD"),
        "smtp_use_tls": _env("SMTP_USE_TLS", "1").lower() in ("1", "true", "yes"),
        "from_email": _env("FROM_EMAIL", _env("IMAP_USER")),
        "poll_interval": int(_env("POLL_INTERVAL", "60")),
    }


def fetch_attachments(imap: imaplib.IMAP4, mailbox: str) -> list:
    """Fetch unread emails and yield (message_id, from_addr, subject, list of (filename, pdf_bytes))."""
    imap.select(mailbox, readonly=False)
    _, nums = imap.search(None, "UNSEEN")
    if not nums[0]:
        return []
    result = []
    for num in nums[0].split():
        try:
            _, data = imap.fetch(num, "(RFC822)")
            if not data or not data[0]:
                continue
            raw = data[0][1]
            if isinstance(raw, bytes):
                msg = email.message_from_bytes(raw)
            else:
                msg = email.message_from_string(raw)
            from_addr = email.utils.parseaddr(msg.get("From", ""))[1] or ""
            subject = msg.get("Subject", "")
            attachments = []
            for part in msg.walk():
                if part.get_content_disposition() != "attachment":
                    continue
                filename = part.get_filename()
                if not filename:
                    continue
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                if filename.lower().endswith(".pdf"):
                    attachments.append((filename, payload))
            if attachments:
                result.append((num, from_addr, subject, attachments))
        except Exception as e:
            logger.exception("Error parsing message %s", num)
    return result


def process_attachment(pdf_bytes: bytes, original_name: str, out_dir: Path) -> tuple:
    """
    Save PDF to temp file, run converter, return (converted_path, payments) or (None, None) on failure.
    """
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, dir=out_dir) as f:
        f.write(pdf_bytes)
        input_path = f.name
    base = Path(original_name).stem
    converted_path = out_dir / f"{base}_epc_qr.pdf"
    try:
        payments, _ = process_pdf(input_path, str(converted_path))
        total = sum(p.amount for p in payments)
        logger.info(
            "Parsed %s: %d payment(s), total %.2f EUR",
            original_name, len(payments), total,
        )
        return str(converted_path), payments
    except Exception as e:
        logger.warning("Convert failed for %s: %s", original_name, e)
        return None, None
    finally:
        try:
            os.unlink(input_path)
        except Exception:
            pass


def send_reply(config: dict, to_addr: str, subject: str, body: str, attachments: list) -> None:
    """Send email via SMTP. attachments: list of (filename, filepath or bytes)."""
    msg = MIMEMultipart()
    msg["From"] = config["from_email"]
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    for name, payload in attachments:
        if isinstance(payload, (str, Path)):
            with open(payload, "rb") as f:
                data = f.read()
        else:
            data = payload
        part = MIMEApplication(data, _subtype="pdf")
        part.add_header("Content-Disposition", "attachment", filename=name)
        msg.attach(part)
    with smtplib.SMTP(config["smtp_host"], config["smtp_port"]) as smtp:
        if config["smtp_use_tls"]:
            smtp.starttls()
        smtp.login(config["smtp_user"], config["smtp_password"])
        smtp.sendmail(config["from_email"], [to_addr], msg.as_string())
    logger.info("Reply sent to %s | subject: %s", to_addr, subject)


def run_once(config: dict) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        imap = imaplib.IMAP4_SSL(config["imap_host"], config["imap_port"])
        try:
            imap.login(config["imap_user"], config["imap_password"])
        except imaplib.IMAP4.error as e:
            logger.error("IMAP login failed: %s", e)
            return
        try:
            messages = fetch_attachments(imap, config["imap_mailbox"])
            if not messages:
                return
            logger.info("Found %d message(s) with PDF attachment(s)", len(messages))
            for num, from_addr, subject, attachments in messages:
                logger.info(
                    "Processing message from %s | subject: %s | %d PDF(s)",
                    from_addr, subject or "(no subject)", len(attachments),
                )
                reply_attachments = []
                body_parts = []
                for filename, pdf_bytes in attachments:
                    converted_path, payments = process_attachment(
                        pdf_bytes, filename, out_dir
                    )
                    reply_attachments.append((filename, pdf_bytes))
                    if converted_path and payments:
                        conv_name = Path(filename).stem + "_epc_qr.pdf"
                        with open(converted_path, "rb") as f:
                            reply_attachments.append((conv_name, f.read()))
                        body_parts.append(
                            f"--- {filename} ---\n"
                            + format_payment_register_text(payments)
                        )
                if not body_parts:
                    body = "No UNP QR codes found in the attached PDF(s)."
                else:
                    body = "Payment register(s):\n\n" + "\n\n".join(body_parts)
                reply_subject = "RE: " + (subject or "(no subject)")
                try:
                    send_reply(
                        config,
                        from_addr,
                        reply_subject,
                        body,
                        reply_attachments,
                    )
                    try:
                        imap.store(num, "+FLAGS", "\\Deleted")
                        logger.info("Message deleted from mailbox (reply sent to %s)", from_addr)
                    except Exception as e:
                        logger.error("IMAP delete failed: %s", e)
                except Exception as e:
                    logger.exception("SMTP send failed to %s", from_addr)
        finally:
            try:
                imap.expunge()
            except Exception:
                pass
            imap.logout()


def main() -> int:
    try:
        config = get_config()
    except RuntimeError as e:
        logger.error("%s", e)
        return 1
    logger.info(
        "Started: IMAP %s, SMTP %s, poll every %ds",
        config["imap_host"], config["smtp_host"], config["poll_interval"],
    )
    while True:
        try:
            run_once(config)
        except Exception as e:
            logger.exception("Run error: %s", e)
        time.sleep(config["poll_interval"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

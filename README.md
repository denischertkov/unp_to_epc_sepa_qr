# UNP→EPC QR Mail Service

Docker service that monitors an IMAP mailbox, converts PDF attachments containing UNP QR codes to EPC QR (Revolut-compatible), and replies via SMTP. Processed messages are deleted from the server after a successful reply.

## Behaviour

1. Connects to IMAP and fetches **unread** messages from the configured mailbox.
2. For each message, collects **PDF attachments**.
3. For each PDF: runs the UNP→EPC QR converter. If UNP codes are found, produces a converted PDF.
4. Sends a **reply** to the sender (`From` address) with:
   - **Subject:** `RE: ` + original subject
   - **Body:** Plain-text payment register (list of payments and total)
   - **Attachments:** Original PDF(s) + converted PDF(s) (when conversion succeeded)
5. After successful send, **deletes** the message from the mailbox (IMAP `\Deleted` + expunge).

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `IMAP_HOST` | yes | — | IMAP server hostname |
| `IMAP_PORT` | no | `993` | IMAP port (SSL) |
| `IMAP_USER` | yes | — | Mailbox login |
| `IMAP_PASSWORD` | yes | — | Mailbox password |
| `IMAP_MAILBOX` | no | `INBOX` | Mailbox name to monitor |
| `SMTP_HOST` | yes | — | SMTP server hostname |
| `SMTP_PORT` | no | `587` | SMTP port |
| `SMTP_USER` | yes | — | SMTP login |
| `SMTP_PASSWORD` | yes | — | SMTP password |
| `SMTP_USE_TLS` | no | `1` | Use STARTTLS (`1`/`0`, `true`/`false`) |
| `FROM_EMAIL` | no | same as `IMAP_USER` | Sender address for replies |
| `POLL_INTERVAL` | no | `60` | Seconds between mailbox checks |

## Build and run

From the **repository root** (parent of `service/`):

```bash
docker build -f service/Dockerfile -t unp-epc-qr-mail .
docker run --rm -e IMAP_HOST=imap.example.com -e IMAP_USER=... -e IMAP_PASSWORD=... \
  -e SMTP_HOST=smtp.example.com -e SMTP_USER=... -e SMTP_PASSWORD=... \
  unp-epc-qr-mail
```

Example with `.env` file:

```bash
# .env
IMAP_HOST=imap.gmail.com
IMAP_USER=your@gmail.com
IMAP_PASSWORD=app-password
IMAP_MAILBOX=INBOX
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@gmail.com
SMTP_PASSWORD=app-password
SMTP_USE_TLS=1
POLL_INTERVAL=120
```

```bash
docker run --rm --env-file .env unp-epc-qr-mail
```

## Notes

- Only **unread** messages are processed. Read messages are left as-is.
- Only attachments whose filename ends in `.pdf` are considered.
- If a PDF has no UNP QR codes, the reply still includes the original PDF and a body line like "No UNP QR codes found in the attached PDF(s)."
- The service runs in an infinite loop with `POLL_INTERVAL` seconds between runs.

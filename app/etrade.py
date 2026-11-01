"""In-memory import of text-based E*TRADE statement PDFs."""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import re

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 500
MAX_EXTRACTED_TEXT_CHARS = 2_000_000


class StatementPdfError(ValueError):
    """A PDF could not be read as a text-based brokerage statement."""


TRANSFER_STATUSES = ("Scheduled", "Complete", "In process", "Cancelled", "Rejected", "Failed", "Action required")


def analyze_statement_text(text: str) -> dict:
    """Extract only the safe, structured fields available in a transfer-activity export."""
    if "transfer activity" not in text.lower():
        return {"document_type": "statement_text", "transactions": [], "summary": None}

    status_map = {
        icon: next(status for status in TRANSFER_STATUSES if status.lower() == label.lower())
        for icon, label in re.findall(
            r"([\ue000-\uf8ff]+)\s*(Scheduled|Complete|In process|Cancelled|Rejected|Failed|Action required)",
            text,
            flags=re.IGNORECASE,
        )
    }
    transactions = []
    for line in text.splitlines():
        date_match = re.search(r"(?P<date>\d{1,2}/\d{1,2}/\d{4})\s+", line)
        amount_match = re.search(r"\$(?P<amount>\d[\d,]*(?:\.\d{2})?)", line)
        if not date_match or not amount_match or amount_match.start() < date_match.end():
            continue

        try:
            transaction_date = datetime.strptime(date_match.group("date"), "%m/%d/%Y").date().isoformat()
        except ValueError:
            continue

        marker = line[:date_match.start()].strip().split()
        icon = marker[-1] if marker else ""
        transactions.append({
            "date": transaction_date,
            "type": "Transfer",
            "amount": float(amount_match.group("amount").replace(",", "")),
            "status": status_map.get(icon, "Unknown"),
        })

    summary = None
    if transactions:
        summary = {
            "transaction_count": len(transactions),
            "total_amount": round(sum(item["amount"] for item in transactions), 2),
            "completed_amount": round(sum(item["amount"] for item in transactions if item["status"] == "Complete"), 2),
            "scheduled_amount": round(sum(item["amount"] for item in transactions if item["status"] == "Scheduled"), 2),
        }
    return {"document_type": "transfer_activity", "transactions": transactions, "summary": summary}


def obfuscate_sensitive_text(text: str) -> str:
    """Mask common identifiers as defense in depth; display output is also allowlist-generated."""
    text = re.sub(
        r"(?im)^(\s*(?:name|account holder|account owner|customer name|client name|ssn|social security|"
        r"password|passcode|pwd|pin|address|mailing address|account|account number|account no\.?|acct\.?)"
        r"\s*[:#-]\s*).+$",
        r"\1[REDACTED]",
        text,
    )
    text = re.sub(r"\b\d{3}[- ]?\d{2}[- ]?\d{4}\b", "[REDACTED SSN]", text)
    text = re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[REDACTED EMAIL]", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)", "[REDACTED PHONE]", text)
    text = re.sub(
        r"\b(?:\d{1,6}\s+[\w.'-]+\s+){0,4}(?:street|st|road|rd|avenue|ave|boulevard|blvd|drive|dr|"
        r"lane|ln|court|ct|way)\b[^\n]*",
        "[REDACTED ADDRESS]",
        text,
        flags=re.IGNORECASE,
    )
    return text


def safe_statement_display(analysis: dict) -> str:
    """Build display text only from fields explicitly allowed for view-only transfer analytics."""
    if analysis["document_type"] != "transfer_activity":
        return "Statement text extracted. Personal and account details are not displayed. No analytics are available for this format."
    lines = ["Transfer Activity — redacted view", "Date | Activity | Status | Amount"]
    lines.extend(
        f"{transaction['date']} | Transfer | {transaction['status']} | ${transaction['amount']:,.2f}"
        for transaction in analysis["transactions"]
    )
    return obfuscate_sensitive_text("\n".join(lines))


def read_statement_pdf(filename: str, content: bytes) -> dict:
    if not content:
        raise StatementPdfError("The uploaded PDF is empty.")
    if len(content) > MAX_PDF_BYTES:
        raise StatementPdfError("The PDF exceeds the 20 MB upload limit.")
    if not content.startswith(b"%PDF-"):
        raise StatementPdfError("The uploaded file is not a valid PDF.")

    try:
        reader = PdfReader(BytesIO(content), strict=False)
        if reader.is_encrypted:
            raise StatementPdfError("Password-protected PDFs are not supported.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise StatementPdfError("The PDF exceeds the 500-page limit.")
        pages = [page.extract_text() or "" for page in reader.pages]
    except StatementPdfError:
        raise
    except (PdfReadError, OSError) as exc:
        raise StatementPdfError("The PDF could not be read. Please check that it is not damaged.") from exc

    text = "\n\n".join(f"--- Page {index} ---\n{page.strip()}" for index, page in enumerate(pages, 1)
                       if page.strip())
    if not text.strip():
        raise StatementPdfError(
            "No selectable text was found. Scanned/image-only PDFs are not supported yet; "
            "upload a text-based PDF statement."
        )
    if len(text) > MAX_EXTRACTED_TEXT_CHARS:
        raise StatementPdfError("The PDF contains too much text to keep in memory (2 million characters maximum).")

    analysis = analyze_statement_text(obfuscate_sensitive_text(text))
    display_text = safe_statement_display(analysis)
    return {
        "filename": "E*TRADE statement",
        "page_count": len(pages),
        "text": display_text,
        "character_count": len(display_text),
        "imported_at": datetime.now(timezone.utc).isoformat(),
        **analysis,
    }

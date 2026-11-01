import pytest

from app import deps
from app.etrade import (
    StatementPdfError,
    analyze_statement_text,
    obfuscate_sensitive_text,
    read_statement_pdf,
    safe_statement_display,
)


def test_statement_pdf_text_extraction_and_filename_sanitizing(monkeypatch):
    class Page:
        def extract_text(self):
            return "E*TRADE Account Statement\nTotal Account Value $123.45"

    class Reader:
        is_encrypted = False
        pages = [Page()]

        def __init__(self, _file, strict):
            assert strict is False

    monkeypatch.setattr("app.etrade.PdfReader", Reader)
    statement = read_statement_pdf(r"C:\private\statement.pdf", b"%PDF-test")

    assert statement["filename"] == "E*TRADE statement"
    assert statement["page_count"] == 1
    assert "Total Account Value $123.45" not in statement["text"]
    assert "Personal and account details are not displayed" in statement["text"]
    assert statement["character_count"] == len(statement["text"])


def test_statement_pdf_rejects_non_pdf_and_scanned_pdf(monkeypatch):
    with pytest.raises(StatementPdfError, match="not a valid PDF"):
        read_statement_pdf("statement.pdf", b"not a pdf")

    class Page:
        def extract_text(self):
            return ""

    class Reader:
        is_encrypted = False
        pages = [Page()]

        def __init__(self, _file, strict):
            pass

    monkeypatch.setattr("app.etrade.PdfReader", Reader)
    with pytest.raises(StatementPdfError, match="Scanned/image-only PDFs"):
        read_statement_pdf("scanned.pdf", b"%PDF-test")


def test_transfer_activity_extracts_cash_flow_without_account_details():
    text = (
        "Transfer Activity\n"
        "\ue000Scheduled \ue001Complete \ue002In process\n"
        "\ue000 10/13/2026 Transfer money $75,000.00 private bank ...1234 Savings ...9969 Once\n"
        "\ue001 10/05/2026 Transfer money $25,000.00 private bank ...1234 Savings ...9969 Once\n"
        "\ue001 09/28/2026 Transfer money $100.00 private bank ...1234 Savings ...9969 Once\n"
    )
    analysis = analyze_statement_text(text)

    assert analysis["document_type"] == "transfer_activity"
    assert analysis["summary"] == {
        "transaction_count": 3,
        "total_amount": 100100.0,
        "completed_amount": 25100.0,
        "scheduled_amount": 75000.0,
    }
    assert [row["status"] for row in analysis["transactions"]] == ["Scheduled", "Complete", "Complete"]
    assert "private bank" not in str(analysis)
    preview = safe_statement_display(analysis)
    assert "private bank" not in preview and "1234" not in preview and "Savings" not in preview
    assert "2026-10-13" in preview and "$75,000.00" in preview


def test_obfuscation_masks_common_sensitive_fields():
    private_text = (
        "Name: Jane Doe\n"
        "SSN: 123-45-6789\n"
        "Password: SecretPass123\n"
        "Address: 123 Main Street, Springfield, NY 10001\n"
        "Email: jane@example.com\n"
        "Phone: (212) 555-0199\n"
    )
    redacted = obfuscate_sensitive_text(private_text)

    for private_value in (
        "Jane Doe", "123-45-6789", "SecretPass123", "123 Main Street",
        "jane@example.com", "(212) 555-0199",
    ):
        assert private_value not in redacted
    assert redacted.count("[REDACTED]") >= 4
    assert "[REDACTED EMAIL]" in redacted
    assert "[REDACTED PHONE]" in redacted


def test_etrade_statement_upload_persists_in_memory_until_cleared(client, monkeypatch):
    deps.get_etrade_statement_store.cache_clear()
    session_a = {"X-Statement-Session": "browser-session-0123456789"}
    session_b = {"X-Statement-Session": "browser-session-9876543210"}
    parsed = {
        "filename": "statement.pdf",
        "page_count": 1,
        "text": "Account Value $123.45",
        "character_count": 21,
        "imported_at": "2026-10-31T12:00:00+00:00",
        "document_type": "statement_text",
        "transactions": [],
        "summary": None,
    }
    monkeypatch.setattr("app.routers.etrade.read_statement_pdf", lambda filename, content: parsed)

    assert client.get("/api/etrade/statement").status_code == 422
    assert client.get("/api/etrade/statement", headers=session_a).json() is None
    response = client.post(
        "/api/etrade/statement/upload",
        files={"file": ("statement.pdf", b"%PDF-test", "application/pdf")},
        headers=session_a,
    )
    assert response.status_code == 200 and response.json() == parsed
    stored = client.get("/api/etrade/statement", headers=session_a).json()
    assert stored["text"] == ""
    assert stored["summary"] == parsed["summary"]
    assert client.get("/api/etrade/statement", headers=session_b).json() is None
    assert client.delete("/api/etrade/statement", headers=session_a).json() == {"cleared": True}
    assert client.get("/api/etrade/statement", headers=session_a).json() is None
    assert client.get("/api/etrade/statement", headers=session_b).json() is None

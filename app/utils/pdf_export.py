"""Generate a PDF report from a QueryResponse.

Uses fpdf2 (pure-Python, no system deps). Falls back to a minimal
in-memory PDF if fpdf2 is not installed.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas import QueryResponse


def _fpdf_report(result: QueryResponse, *, ticker: str, question: str) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 12, f"BIST Agentic RAG Report - {ticker}", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 7, f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, f"As-of date: {result.as_of_date.strftime('%Y-%m-%d')}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Question
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Question", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 6, question)
    pdf.ln(4)

    # Answer (EN)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Answer (EN)", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 6, result.answer_en)
    pdf.ln(4)

    # Answer (TR)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Answer (TR)", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 6, result.answer_tr)
    pdf.ln(4)

    # Metadata
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Analysis Metadata", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Consistency: {result.consistency_assessment}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Confidence: {result.confidence:.2f}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Provider: {result.provider_used}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Route: {result.route_path}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Citation coverage: {result.citation_coverage_score:.2f}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Citations
    if result.citations:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, f"Citations ({len(result.citations)})", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        for idx, cit in enumerate(result.citations, start=1):
            pdf.multi_cell(
                0, 5,
                f"[{idx}] {cit.source_type.value} | {cit.institution} | {cit.date.strftime('%Y-%m-%d')}\n"
                f"    {cit.title}\n    {cit.snippet[:200]}",
            )
            pdf.ln(2)

    # Evidence gaps
    if result.evidence_gaps:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Evidence Gaps", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        for gap in result.evidence_gaps:
            pdf.multi_cell(0, 5, f"- {gap}")
        pdf.ln(2)

    # Disclaimer
    pdf.set_font("Helvetica", "I", 9)
    pdf.ln(6)
    pdf.multi_cell(0, 5, result.disclaimer)

    return bytes(pdf.output())


def _minimal_pdf(result: QueryResponse, *, ticker: str, question: str) -> bytes:
    """Bare-minimum PDF without fpdf2 — just enough to be a valid PDF."""
    lines = [
        f"BIST Agentic RAG Report - {ticker}",
        f"Date: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"Q: {question}",
        "",
        f"Answer (EN): {result.answer_en[:1000]}",
        "",
        f"Consistency: {result.consistency_assessment}",
        f"Confidence: {result.confidence:.2f}",
        f"Provider: {result.provider_used}",
        "",
        result.disclaimer,
    ]
    text = "\n".join(lines)
    stream = io.BytesIO()
    stream.write(b"%PDF-1.4\n")
    stream.write(b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n")
    stream.write(b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n")
    content = f"BT /F1 10 Tf 50 750 Td ({text[:800]}) Tj ET"
    content_bytes = content.encode("latin-1", errors="replace")
    stream.write(
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    )
    stream.write(f"4 0 obj<</Length {len(content_bytes)}>>stream\n".encode())
    stream.write(content_bytes)
    stream.write(b"\nendstream\nendobj\n")
    stream.write(b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n")
    xref_offset = stream.tell()
    stream.write(b"xref\n0 6\n")
    stream.write(b"0000000000 65535 f \n")
    for i in range(1, 6):
        stream.write(f"{i:010d} 00000 n \n".encode())
    stream.write(f"trailer<</Size 6/Root 1 0 R>>\nstartxref\n{xref_offset}\n%%EOF".encode())
    return stream.getvalue()


def generate_query_pdf(result: QueryResponse, *, ticker: str, question: str) -> bytes:
    try:
        return _fpdf_report(result, ticker=ticker, question=question)
    except ImportError:
        return _minimal_pdf(result, ticker=ticker, question=question)

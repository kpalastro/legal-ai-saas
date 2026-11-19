"""Document export formats: TXT, DOCX, PDF.

The compliance content (disclosure footer + citation verification record) is
already part of the rendered `content`; these exporters only serialise it. DOCX
uses python-docx; PDF uses PyMuPDF with a simple, deterministic A4 layout.
"""

from __future__ import annotations

import io

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MIME = "application/pdf"
TXT_MIME = "text/plain; charset=utf-8"

_SUPPORTED = {"txt": TXT_MIME, "docx": DOCX_MIME, "pdf": PDF_MIME}


def media_type(fmt: str) -> str:
    try:
        return _SUPPORTED[fmt]
    except KeyError:
        raise ValueError(f"unsupported export format {fmt!r} (use txt|docx|pdf)") from None


def to_txt(content: str) -> bytes:
    return content.encode("utf-8")


def to_docx(content: str) -> bytes:
    import docx

    document = docx.Document()
    for block in content.split("\n"):
        # Empty lines become spacing paragraphs; otherwise one paragraph per line
        # (the templates already carry their own numbering/headings).
        document.add_paragraph(block)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def to_pdf(content: str) -> bytes:
    import fitz  # PyMuPDF

    lines: list[str] = []
    for raw in content.splitlines():
        if not raw:
            lines.append("")
            continue
        while len(raw) > 95:
            lines.append(raw[:95])
            raw = raw[95:]
        lines.append(raw)

    doc = fitz.open()
    per_page = 58
    for start in range(0, len(lines), per_page):
        page = doc.new_page(width=595, height=842)  # A4 points
        y = 55
        for line in lines[start : start + per_page]:
            if line:
                # latin-1 fallback keeps a weird glyph from aborting the export
                page.insert_text((45, y), line.encode("latin-1", "replace").decode("latin-1"),
                                 fontsize=10, fontname="helv")
            y += 13
    data = doc.tobytes()
    doc.close()
    return data


def export_bytes(content: str, fmt: str) -> tuple[bytes, str]:
    """Return (bytes, media_type)."""
    fmt = fmt.lower()
    if fmt == "txt":
        return to_txt(content), media_type(fmt)
    if fmt == "docx":
        return to_docx(content), media_type(fmt)
    if fmt == "pdf":
        return to_pdf(content), media_type(fmt)
    raise ValueError(f"unsupported export format {fmt!r} (use txt|docx|pdf)")

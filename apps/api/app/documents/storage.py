"""Upload storage + text extraction for case documents.

Security shape:
  * allow-list MIME types, size cap, magic-byte sniffing;
  * filenames are reduced to a basename and never used as a path component;
  * files are written under STORAGE_DIR (default ./storage), outside the web root,
    with 0600 permissions;
  * extraction never executes anything — PDF via PyMuPDF, DOCX via python-docx.

The extracted text is what grounds the debate engine (app/agents/engine.py); the
raw file is kept for the user's records and future re-extraction.
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import uuid

from app.config import get_settings

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TEXT = "text/plain"
MARKDOWN = "text/markdown"
CSV = "text/csv"

ALLOWED_MIME: dict[str, str] = {
    PDF: ".pdf",
    DOCX: ".docx",
    TEXT: ".txt",
    MARKDOWN: ".md",
    CSV: ".csv",
}

MAX_EXTRACT_CHARS = 200_000
_SAFE_CASE = re.compile(r"^[0-9a-fA-F-]{36}$")


class UploadError(ValueError):
    """Rejected upload (client error -> 422/413)."""


def _normalise_mime(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def _sniff(content: bytes) -> str | None:
    if content[:5] == b"%PDF-":
        return PDF
    if content[:4] == b"PK\x03\x04":
        return DOCX
    try:
        content.decode("utf-8")
        return TEXT
    except UnicodeDecodeError:
        return None


def validate_upload(
    filename: str, content_type: str | None, content: bytes
) -> tuple[str, str]:
    """Return (mime, safe_filename) or raise UploadError."""
    settings = get_settings()
    if not content:
        raise UploadError("empty file")
    if len(content) > settings.max_upload_bytes:
        raise UploadError(
            f"file exceeds {settings.max_upload_bytes // (1024 * 1024)} MB limit"
        )

    mime = _normalise_mime(content_type)
    if mime not in ALLOWED_MIME:
        raise UploadError(
            "unsupported file type — allowed: PDF, DOCX, TXT, Markdown, CSV"
        )

    safe_name = pathlib.Path(filename or "upload").name
    if not safe_name or safe_name in {".", ".."}:
        raise UploadError("invalid filename")
    suffix = pathlib.Path(safe_name).suffix.lower()
    if suffix and suffix != ALLOWED_MIME[mime]:
        raise UploadError(f"extension {suffix} does not match content type {mime}")

    sniffed = _sniff(content)
    text_family = {TEXT, MARKDOWN, CSV}
    if sniffed != mime and not (mime in text_family and sniffed == TEXT):
        # A renamed PDF/DOCX is a common malformed-upload case; reject rather
        # than hand a surprising byte stream to the extractor. Markdown/CSV are
        # UTF-8 text, so their sniff is TEXT.
        raise UploadError("file content does not match its declared content type")
    return mime, safe_name


def storage_root() -> pathlib.Path:
    root = pathlib.Path(get_settings().storage_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_upload(case_id: str, filename: str, content_type: str | None, content: bytes) -> dict:
    """Persist the upload and return {path, mime_type, filename, size_bytes, sha256}."""
    if not _SAFE_CASE.fullmatch(case_id):
        raise UploadError("invalid case id")
    mime, safe_name = validate_upload(filename, content_type, content)

    case_dir = storage_root() / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    target = case_dir / f"{uuid.uuid4().hex}{ALLOWED_MIME[mime]}"
    target.write_bytes(content)
    try:
        target.chmod(0o600)
    except OSError:
        pass  # best effort on filesystems without POSIX permissions

    return {
        "path": str(target),
        "mime_type": mime,
        "filename": safe_name,
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def extract_text(path: str, mime_type: str) -> str:
    """Best-effort text extraction, bounded to MAX_EXTRACT_CHARS."""
    text = ""
    if mime_type == PDF:
        import fitz  # PyMuPDF

        with fitz.open(path) as doc:
            text = "\n".join(page.get_text("text") for page in doc)
    elif mime_type == DOCX:
        import docx

        document = docx.Document(path)
        lines = [p.text for p in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                lines.append(" | ".join(cell.text for cell in row.cells))
        text = "\n".join(lines)
    else:
        text = pathlib.Path(path).read_bytes().decode("utf-8", errors="replace")
    return text.strip()[:MAX_EXTRACT_CHARS]

"""Text extraction for Context Hub sources: pdf/docx/txt/csv files, and URL fetch + a minimal
stdlib HTML-to-text strip (no new HTML-parsing dependency)."""

import io
from html.parser import HTMLParser

import httpx
from docx import Document
from pypdf import PdfReader

from agentdrops.resilience.http_retry import HTTP_RETRY

_SKIP_TAGS = {"script", "style"}


class _TextExtractingParser(HTMLParser):
    """Collects text nodes outside `<script>`/`<style>`, joined with single spaces."""

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._chunks.append(data.strip())

    def get_text(self) -> str:
        return " ".join(self._chunks)


def _extract_pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


def _extract_docx_text(data: bytes) -> str:
    document = Document(io.BytesIO(data))
    return "\n".join(p.text for p in document.paragraphs)


def extract_file_text(content_type: str, data: bytes) -> str:
    """Dispatch on the document's stored `content_type` (`pdf`/`docx`/`txt`/`csv`)."""
    if content_type == "pdf":
        return _extract_pdf_text(data)
    if content_type == "docx":
        return _extract_docx_text(data)
    if content_type in ("txt", "csv"):
        return data.decode("utf-8", errors="replace")
    raise ValueError(f"unsupported content_type: {content_type!r}")


@HTTP_RETRY
async def fetch_url_text(url: str, client: httpx.AsyncClient) -> str:
    response = await client.get(url)
    response.raise_for_status()
    parser = _TextExtractingParser()
    parser.feed(response.text)
    return parser.get_text()

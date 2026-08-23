"""Sliding-window text chunking for Context Hub ingestion — plain character-based windows,
no tokenizer dependency, since exact token boundaries don't matter for retrieval snippets."""


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split `text` into overlapping `chunk_size`-character windows. Whitespace (including
    newlines) is collapsed to single spaces first, so chunk boundaries never depend on a
    source document's original line-wrapping."""
    normalized = " ".join(text.split())
    if not normalized:
        return []

    step = chunk_size - overlap
    chunks = []
    start = 0
    while True:
        end = start + chunk_size
        chunks.append(normalized[start:end])
        if end >= len(normalized):
            break
        start += step
    return chunks

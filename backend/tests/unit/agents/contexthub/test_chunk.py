from agentdrops.agents.contexthub.chunk import chunk_text


def test_short_text_returns_a_single_chunk() -> None:
    chunks = chunk_text("hello world", chunk_size=1000, overlap=150)

    assert chunks == ["hello world"]


def test_empty_text_returns_no_chunks() -> None:
    assert chunk_text("", chunk_size=1000, overlap=150) == []


def test_long_text_is_split_with_overlap() -> None:
    text = "x" * 2500

    chunks = chunk_text(text, chunk_size=1000, overlap=150)

    assert len(chunks) == 3
    assert all(len(c) <= 1000 for c in chunks)
    # the overlap region (last 150 chars of chunk N) reappears at the start of chunk N+1
    assert chunks[0][-150:] == chunks[1][:150]
    assert chunks[1][-150:] == chunks[2][:150]


def test_whitespace_is_normalized_before_chunking() -> None:
    chunks = chunk_text("hello\n\n   world  \t foo", chunk_size=1000, overlap=150)

    assert chunks == ["hello world foo"]

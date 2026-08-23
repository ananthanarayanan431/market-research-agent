"""Context Hub retrieval pipeline: embed the query, vector-search chunks, format for the
agent — the Context Hub counterpart of agents/research/methods.py::run_search_pipeline."""

from agentdrops.agents.contexthub.embeddings import EmbeddingClient
from agentdrops.repository.contexthub import ContextHubChunkMatch, ContextHubStore


def format_contexthub_output(matches: list[ContextHubChunkMatch]) -> str:
    if not matches:
        return "No relevant internal knowledge found."
    blocks = [
        f"DOCUMENT {i}: {match.document_title}\nEXCERPT: {match.content}"
        for i, match in enumerate(matches, start=1)
    ]
    return "\n\n".join(blocks)


async def run_contexthub_search_pipeline(
    store: ContextHubStore, embedder: EmbeddingClient, query: str, top_k: int
) -> str:
    [query_embedding] = await embedder.embed([query])
    matches = await store.search_chunks(query_embedding, top_k)
    return format_contexthub_output(matches)

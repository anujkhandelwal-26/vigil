"""
Populates policy_chunk.embedding for the copilot's POLICY_LOOKUP intent.

db/V3__seed_policy_chunks.sql inserts the policy corpus with NULL
embeddings; until this runs, retrieval.policy_lookup() (which filters
`WHERE embedding IS NOT NULL`) returns nothing. Chunks embedded with a
different model than the configured one are re-embedded too, so switching
EMBED_MODEL can't leave the corpus in a mixed vector space.

Run:  python -m app.training.embed_policy
It is also called at ml-service startup (main.py lifespan), so an existing
database heals itself on the next restart.
"""
from __future__ import annotations

from app.config import settings
from app.db import get_conn
from app.embeddings import get_embedding_provider


def embed_missing_policy_chunks() -> int:
    """Embed every chunk that is unembedded or embedded with another model.
    Returns the number of chunks written."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, content FROM policy_chunk "
            "WHERE embedding IS NULL OR embed_model IS DISTINCT FROM %s",
            (settings.embed_model,),
        ).fetchall()
    if not rows:
        return 0

    provider = get_embedding_provider()
    with get_conn() as conn:
        for chunk_id, content in rows:
            conn.execute(
                "UPDATE policy_chunk SET embedding = %s::vector, embed_model = %s WHERE id = %s",
                (provider.embed(content), settings.embed_model, chunk_id),
            )
        conn.commit()
    return len(rows)


if __name__ == "__main__":
    n = embed_missing_policy_chunks()
    print(f"embedded {n} policy chunk(s) with {settings.embed_model}")

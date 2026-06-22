"""Backfill embeddings for existing memory objects.

Usage:
    python -m scripts.backfill_embeddings --env-file .env [--batch-size 20] [--limit 1000]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from llm.config import LLMConfig
from llm.embedding import OpenAIEmbeddingClient
from memory.config import MemoryRuntimeConfig
from memory.embedding import MemoryEmbeddingService
from memory.persistence.postgres.connection import PostgresPersistentMemoryDatabase

LOGGER = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Backfill memory object embeddings")
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to .env file (default: .env)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Max texts per embedding API call (default: 20)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Max total objects to process (default: 1000)",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override CONVERSATION_DATABASE_URL from .env",
    )
    args = parser.parse_args()

    env_file = Path(args.env_file)
    if not env_file.exists():
        print(f"Error: .env file not found: {env_file}")
        sys.exit(1)

    llm_config = LLMConfig.from_env(env_file)
    memory_config = MemoryRuntimeConfig.from_env(env_file)

    # Resolve database URL
    from conversation.config import StorageConfig
    storage_config = StorageConfig.from_env(env_file)

    database_url = args.database_url or storage_config.database_url
    if not database_url:
        print("Error: No database URL configured (CONVERSATION_DATABASE_URL)")
        sys.exit(1)

    # Ensure schema (including pgvector extension + embeddings table)
    database = PostgresPersistentMemoryDatabase(database_url)
    database.ensure_schema()

    # Build embedding service
    embedding_client = OpenAIEmbeddingClient(llm_config)
    service = MemoryEmbeddingService(
        embedding_client=embedding_client,
        database_url=database_url,
        model=memory_config.embedding_model,
        dimensions=memory_config.embedding_dimensions,
        batch_size=args.batch_size,
    )

    total_processed = 0
    limit_remaining = args.limit

    LOGGER.info(
        "Starting embedding backfill (model=%s, batch_size=%d, limit=%d)",
        memory_config.embedding_model,
        args.batch_size,
        limit_remaining,
    )

    while limit_remaining > 0:
        chunk_limit = min(batch_size, limit_remaining)
        count = service.backfill_batch(limit=chunk_limit)
        if count == 0:
            LOGGER.info("No more objects without embeddings — backfill complete")
            break
        total_processed += count
        limit_remaining -= count
        LOGGER.info(
            "Processed %d objects (%d total, %d remaining)",
            count,
            total_processed,
            limit_remaining,
        )

    LOGGER.info(
        "Backfill finished: %d objects processed, %d remaining in limit",
        total_processed,
        limit_remaining,
    )


if __name__ == "__main__":
    main()

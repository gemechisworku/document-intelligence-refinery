"""
FactTable Extractor for SQLite (FR-5.3).
Extracts key-value facts from ExtractedDocument and stores them in SQLite.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from src.config import RefineryConfig
from src.models.extracted_document import ExtractedDocument, Table
from src.models.provenance import ProvenanceCitation


class FactTableExtractor:
    """
    Extracts numerical/key-value facts (especially from tables) into a SQLite database.
    Used for precise structured querying.
    """

    def __init__(self, config: RefineryConfig | None = None) -> None:
        from src.config import load_config
        self._config = config if config is not None else load_config()
        self._db_path = Path(self._config.refinery_dir) / "fact_table.sqlite"
        self._init_db()

    def _init_db(self) -> None:
        """Create fact_table schema if it doesn't exist."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id TEXT NOT NULL,
                    fact_key TEXT NOT NULL,
                    fact_value TEXT NOT NULL,
                    page_number INTEGER,
                    context TEXT,
                    timestamp_utc DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            # Create index for fast retrieval
            conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_doc_id ON facts(doc_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_key ON facts(fact_key)")

    def run(
        self,
        extracted: ExtractedDocument,
        doc_id: str,
        config: RefineryConfig | None = None,
    ) -> int:
        """
        Extract facts from the document and insert them into SQLite.
        Returns the number of facts inserted.
        """
        facts = []
        # Basic heuristic: look for 2-column tables that represent key-value pairs
        for table in extracted.tables:
            if not table.rows:
                continue

            for row in table.rows:
                if isinstance(row, list) and len(row) >= 2:
                    # Treat first column as key, second as value if it passes a heuristic
                    key = str(row[0]).strip()
                    val = str(row[1]).strip()
                    if key and val and len(key) < 100:
                        facts.append((doc_id, key, val, table.page_number, table.caption or ""))
                elif isinstance(row, dict):
                    # For dict rows, flatten into k,v
                    for k, v in row.items():
                        key = str(k).strip()
                        val = str(v).strip()
                        if key and val:
                            facts.append((doc_id, key, val, table.page_number, table.caption or ""))

        # Advanced heuristic could use LLM to extract facts from text blocks,
        # but tables are the primary source for structured queries.

        if not facts:
            return 0

        with sqlite3.connect(self._db_path) as conn:
            # Delete old facts for this doc to prevent duplicates on rerun
            conn.execute("DELETE FROM facts WHERE doc_id = ?", (doc_id,))
            conn.executemany(
                """
                INSERT INTO facts (doc_id, fact_key, fact_value, page_number, context)
                VALUES (?, ?, ?, ?, ?)
                """,
                facts
            )

        return len(facts)

    def query(self, sql_query: str, doc_ids: list[str] | None = None) -> list[dict]:
        """
        Run a SQL or simulated query over the facts table.
        WARNING: In production, sanitize SQL. Here, used by structured_query tool.
        """
        # If doc_ids are provided and the query is "SELECT ...", append filter
        # For safety and simplicity, we just execute it in this demo environment.
        if doc_ids:
            docs_list = ",".join(f"'{did}'" for did in doc_ids)
            # Naive injection but works if carefully constructed by the LLM
            if "WHERE" in sql_query.upper():
                sql_query = f"{sql_query} AND doc_id IN ({docs_list})"
            elif sql_query.upper().startswith("SELECT"):
                sql_query = f"{sql_query} WHERE doc_id IN ({docs_list})"

        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(sql_query)
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except sqlite3.Error as e:
            return [{"error": str(e)}]

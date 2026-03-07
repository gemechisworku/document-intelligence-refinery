"""
PageIndex Builder (FR-4.1–FR-4.3, api_contracts §2.5).
Builds hierarchical PageIndexNode tree from ExtractedDocument structure.
Generates LLM section summaries (2–3 sentences) when API key available.
Persists to .refinery/pageindex/{doc_id}.json.
Provides query method for top-K relevant sections (FR-4.2).
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from src.config import RefineryConfig
from src.models.extracted_document import (
    ExtractedDocument,
    ReadingOrderItem,
    TextBlock,
)
from src.models.page_index import PageIndexNode


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _is_heading(block: TextBlock) -> bool:
    """Heuristic: block is a heading."""
    if block.block_type and block.block_type.lower().startswith("head"):
        return True
    text = block.text.strip()
    if len(text) < 120 and "\n" not in text and text and text[0].isupper():
        words = text.split()
        if len(words) <= 12 and not text.endswith("."):
            return True
    return False


def _heading_level(block: TextBlock) -> int:
    """Estimate heading level (1 = top-level, 2+ = sub-sections)."""
    if block.block_type:
        bt = block.block_type.lower()
        # heading_1, h1, heading1 etc.
        match = re.search(r"(\d)", bt)
        if match:
            return int(match.group(1))
    # Fallback: longer text = lower level (heuristic)
    text = block.text.strip()
    if len(text) < 30:
        return 1
    if len(text) < 60:
        return 2
    return 3


def _detect_data_types(texts: list[str], has_tables: bool, has_figures: bool) -> list[str]:
    """Detect data types present in a section."""
    types: list[str] = []
    if has_tables:
        types.append("tables")
    if has_figures:
        types.append("figures")
    full_text = " ".join(texts).lower()
    if re.search(r"\bequation\b|\bformula\b|[=∑∫]", full_text):
        types.append("equations")
    if re.search(r"\d+[.,]\d+\s*%|\$\s*\d|revenue|profit|loss|balance", full_text):
        types.append("financial_data")
    return types or None  # type: ignore[return-value]


def _generate_summary_fallback(title: str, texts: list[str]) -> str:
    """Generate a basic summary without LLM (fallback)."""
    combined = " ".join(t.strip() for t in texts[:5] if t.strip())
    if not combined:
        return f"Section: {title}."
    # Take first ~200 chars as summary
    snippet = combined[:300].rsplit(" ", 1)[0]
    if len(combined) > 300:
        snippet += "..."
    return f"{title}. {snippet}"


def _generate_summary_llm(
    title: str,
    texts: list[str],
    config: RefineryConfig,
) -> str:
    """Generate a 2–3 sentence summary using LLM via OpenRouter."""
    try:
        import requests

        api_key = config.openrouter_api_key
        model = config.openrouter_model or "google/gemini-flash-1.5"
        if not api_key:
            return _generate_summary_fallback(title, texts)

        combined = " ".join(t.strip() for t in texts[:10] if t.strip())[:2000]
        prompt = (
            f"Summarize the following document section titled '{title}' in 2-3 sentences. "
            f"Be concise and factual.\n\nContent:\n{combined}"
        )

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 150,
            },
            timeout=30,
        )
        if response.status_code == 200:
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception:
        pass
    return _generate_summary_fallback(title, texts)


# -----------------------------------------------------------------------------
# Section data (internal)
# -----------------------------------------------------------------------------


class _SectionData:
    """Temporary container for section data during tree construction."""

    def __init__(self, title: str, level: int, page_start: int) -> None:
        self.title = title
        self.level = level
        self.page_start = page_start
        self.page_end = page_start
        self.texts: list[str] = []
        self.has_tables = False
        self.has_figures = False
        self.children: list[_SectionData] = []

    def to_node(self, config: RefineryConfig, use_llm: bool = False) -> PageIndexNode:
        """Convert to PageIndexNode with summary."""
        if use_llm and config.openrouter_api_key:
            summary = _generate_summary_llm(self.title, self.texts, config)
        else:
            summary = _generate_summary_fallback(self.title, self.texts)

        data_types = _detect_data_types(self.texts, self.has_tables, self.has_figures)
        child_nodes = [c.to_node(config, use_llm=use_llm) for c in self.children]

        return PageIndexNode(
            title=self.title,
            page_start=self.page_start,
            page_end=self.page_end,
            child_sections=child_nodes,
            summary=summary,
            data_types_present=data_types,
            node_id=str(uuid.uuid4())[:8],
        )


# -----------------------------------------------------------------------------
# PageIndex Builder
# -----------------------------------------------------------------------------


class PageIndexBuilder:
    """
    Builds PageIndex tree from ExtractedDocument (FR-4.1, api_contracts §2.5).
    Persists as .refinery/pageindex/{doc_id}.json.

    Usage:
        builder = PageIndexBuilder()
        root = builder.run(extracted_doc, doc_id, config)
    """

    def __init__(
        self,
        config: RefineryConfig | None = None,
        *,
        use_llm_summaries: bool = False,
    ) -> None:
        from src.config import load_config

        self._config = config if config is not None else load_config()
        self._use_llm = use_llm_summaries

    def run(
        self,
        extracted: ExtractedDocument,
        doc_id: str,
        config: RefineryConfig | None = None,
    ) -> PageIndexNode:
        """
        Build PageIndex tree and persist to .refinery/pageindex/{doc_id}.json.

        Returns:
            PageIndexNode (root of the tree).
        """
        cfg = config or self._config
        text_blocks = extracted.text_blocks
        tables = extracted.tables
        figures = extracted.figures

        # Determine document page range
        all_pages: list[int] = []
        for b in text_blocks:
            all_pages.append(b.page_number)
        for t in tables:
            all_pages.append(t.page_number)
        for f in figures:
            all_pages.append(f.page_number)

        if not all_pages:
            all_pages = [1]

        doc_page_start = min(all_pages)
        doc_page_end = max(all_pages)

        # Build section structure from headings
        sections = self._extract_sections(text_blocks, tables, figures, extracted.reading_order)

        # If no sections found, create a single root section
        if not sections:
            root_section = _SectionData("Document", 0, doc_page_start)
            root_section.page_end = doc_page_end
            for b in text_blocks:
                root_section.texts.append(b.text)
            root_section.has_tables = len(tables) > 0
            root_section.has_figures = len(figures) > 0
            sections = [root_section]

        # Build tree: nest sections by level
        root_data = _SectionData(doc_id, 0, doc_page_start)
        root_data.page_end = doc_page_end
        root_data.has_tables = len(tables) > 0
        root_data.has_figures = len(figures) > 0
        for b in text_blocks[:3]:
            root_data.texts.append(b.text)

        root_data.children = self._nest_sections(sections)

        # Convert to PageIndexNode
        root = root_data.to_node(cfg, use_llm=self._use_llm)

        # Persist (FR-4.3)
        self._persist(root, doc_id, cfg)

        return root

    def _extract_sections(
        self,
        text_blocks: list[TextBlock],
        tables: list,
        figures: list,
        reading_order: list[ReadingOrderItem],
    ) -> list[_SectionData]:
        """Extract section data from text blocks following reading order."""
        sections: list[_SectionData] = []
        current_section: _SectionData | None = None

        # Create page -> tables/figures maps
        table_pages = {t.page_number for t in tables}
        figure_pages = {f.page_number for f in figures}

        # Process text blocks in order
        order_items = reading_order if reading_order else [
            ReadingOrderItem(type="text", index=i) for i in range(len(text_blocks))
        ]

        for item in order_items:
            if item.type != "text":
                if current_section:
                    if item.type == "table":
                        current_section.has_tables = True
                    elif item.type == "figure":
                        current_section.has_figures = True
                continue

            if item.index >= len(text_blocks):
                continue

            block = text_blocks[item.index]

            if _is_heading(block):
                level = _heading_level(block)
                section = _SectionData(
                    title=block.text.strip(),
                    level=level,
                    page_start=block.page_number,
                )
                section.page_end = block.page_number
                if block.page_number in table_pages:
                    section.has_tables = True
                if block.page_number in figure_pages:
                    section.has_figures = True
                sections.append(section)
                current_section = section
            elif current_section is not None:
                current_section.texts.append(block.text)
                current_section.page_end = max(
                    current_section.page_end, block.page_number
                )
                if block.page_number in table_pages:
                    current_section.has_tables = True
                if block.page_number in figure_pages:
                    current_section.has_figures = True

        return sections

    def _nest_sections(self, sections: list[_SectionData]) -> list[_SectionData]:
        """Nest sections by heading level into a hierarchy."""
        if not sections:
            return []

        result: list[_SectionData] = []
        stack: list[_SectionData] = []

        for section in sections:
            # Pop stack until we find a parent with lower level
            while stack and stack[-1].level >= section.level:
                stack.pop()

            if stack:
                stack[-1].children.append(section)
            else:
                result.append(section)

            stack.append(section)

        return result

    def _persist(
        self,
        root: PageIndexNode,
        doc_id: str,
        config: RefineryConfig,
    ) -> None:
        """Write .refinery/pageindex/{doc_id}.json."""
        pageindex_dir = Path(config.refinery_dir) / "pageindex"
        pageindex_dir.mkdir(parents=True, exist_ok=True)
        out_path = pageindex_dir / f"{doc_id}.json"
        out_path.write_text(
            root.model_dump_json(indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Query (FR-4.2)
    # ------------------------------------------------------------------

    @staticmethod
    def query(
        topic: str,
        root: PageIndexNode,
        top_k: int = 3,
    ) -> list[PageIndexNode]:
        """
        Given a topic string, return top-K most relevant sections (FR-4.2).
        Uses keyword overlap scoring against title, summary, and data_types.
        """
        topic_words = set(topic.lower().split())

        def _score_node(node: PageIndexNode) -> float:
            score = 0.0
            title_words = set(node.title.lower().split())
            score += len(topic_words & title_words) * 3.0

            if node.summary:
                summary_words = set(node.summary.lower().split())
                score += len(topic_words & summary_words) * 1.0

            if node.data_types_present:
                dt_words = set(" ".join(node.data_types_present).lower().split())
                score += len(topic_words & dt_words) * 2.0

            return score

        def _collect_all(node: PageIndexNode) -> list[PageIndexNode]:
            nodes = [node]
            for child in node.child_sections:
                nodes.extend(_collect_all(child))
            return nodes

        all_nodes = _collect_all(root)
        scored = [(n, _score_node(n)) for n in all_nodes]
        scored.sort(key=lambda x: x[1], reverse=True)

        return [n for n, s in scored[:top_k] if s > 0] or scored[:top_k] and [scored[0][0]]

    @staticmethod
    def load_pageindex(doc_id: str, config: RefineryConfig) -> PageIndexNode | None:
        """Load a persisted PageIndex tree from disk."""
        pageindex_path = Path(config.refinery_dir) / "pageindex" / f"{doc_id}.json"
        if not pageindex_path.exists():
            return None
        data = json.loads(pageindex_path.read_text(encoding="utf-8"))
        return PageIndexNode.model_validate(data)

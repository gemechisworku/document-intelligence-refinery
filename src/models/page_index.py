"""
PageIndexNode — hierarchical page/section index (api_contracts §3.5, FR-4.1).
Recursive tree: root is the document; children are sections.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class PageIndexNode(BaseModel):
    """
    Tree node for PageIndex. Root is the document; child_sections are
    recursive (same type). Invariant: page_start <= page_end.
    """

    title: str = Field(description="Section title.")
    page_start: int = Field(description="First page (inclusive).")
    page_end: int = Field(description="Last page (inclusive).")
    child_sections: list[PageIndexNode] = Field(
        default_factory=list,
        description="Child nodes (recursive).",
    )
    key_entities: list[str] | None = Field(
        default=None,
        description="Optional named entities.",
    )
    summary: str | None = Field(
        default=None,
        description="LLM-generated 2–3 sentences.",
    )
    data_types_present: list[str] | None = Field(
        default=None,
        description='E.g. ["tables", "figures", "equations"].',
    )
    node_id: str | None = Field(
        default=None,
        description="Optional stable id for traversal.",
    )

    @model_validator(mode="after")
    def check_page_range(self) -> "PageIndexNode":
        if self.page_end < self.page_start:
            raise ValueError("Invariant: page_end >= page_start")
        return self

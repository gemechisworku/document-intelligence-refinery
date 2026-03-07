"""
Query Agent (FR-5.1–FR-5.5, api_contracts §2.6).
LangGraph agent with three tools (pageindex_navigate, semantic_search, structured_query).
Always attaches a ProvenanceChain to answers.
Includes Audit Mode (verify_claim).
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel, Field

from src.config import RefineryConfig
from src.agents.fact_extractor import FactTableExtractor
from src.agents.indexer import PageIndexBuilder
from src.models.provenance import (
    AuditResult,
    ProvenanceChain,
    ProvenanceCitation,
    QueryResponse,
)


class QueryAgent:
    """
    RAG Agent using LangGraph and tools to query extracted data.
    """

    def __init__(
        self,
        config: RefineryConfig | None = None,
        *,
        vector_store: Any | None = None,
    ) -> None:
        from src.config import load_config
        self._config = config if config is not None else load_config()
        self._vector_store = vector_store
        self._fact_extractor = FactTableExtractor(config=self._config)

        # Set up LangChain LLM
        if self._config.openrouter_api_key:
            try:
                from langchain_openai import ChatOpenAI
                self._llm = ChatOpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=self._config.openrouter_api_key,
                    model=self._config.openrouter_model or "google/gemini-flash-1.5",
                    temperature=0.0,
                )
            except ImportError:
                self._llm = None
        else:
            self._llm = None


        if self._llm:
            # We use LangGraph's prebuilt ReAct agent
            self._agent_executor = create_react_agent(self._llm, self._tools)
        else:
            self._agent_executor = None

        # Tools (FR-5.1)
        @tool
        def pageindex_navigate(topic: str, doc_ids: list[str] | None = None, top_k: int = 3) -> list[dict]:
            """
            Navigate the document sections based on a topic string.
            Returns top relevant sections (title, page range, and summary).
            """
            results = []
            paths = list(self._config.get_pageindex_dir().glob("*.json"))
            for p in paths:
                doc_id = p.stem
                if doc_ids and doc_id not in doc_ids:
                    continue
                root = PageIndexBuilder.load_pageindex(doc_id, self._config)
                if root:
                    nodes = PageIndexBuilder.query(topic, root, top_k=top_k)
                    for n in nodes:
                        results.append({
                            "doc_id": doc_id,
                            "title": n.title,
                            "page_start": n.page_start,
                            "page_end": n.page_end,
                            "summary": n.summary,
                        })
            return results

        @tool
        def semantic_search(query: str, doc_ids: list[str] | None = None, top_k: int = 3) -> list[dict]:
            """
            Search exact text chunks in the document using vector retrieval.
            Returns text chunks with their page_number and content_hash.
            """
            if not self._vector_store:
                return [{"error": "Vector store not configured or empty"}]
            try:
                where = {"doc_id": doc_ids[0]} if doc_ids and len(doc_ids) == 1 else (
                    {"doc_id": {"$in": doc_ids}} if doc_ids else None
                )
                res = self._vector_store.query(
                    query_texts=[query],
                    n_results=top_k,
                    where=where
                )
                out = []
                if res and res["documents"] and res["documents"][0]:
                    for doc, meta in zip(res["documents"][0], res["metadatas"][0]):
                        item = {
                            "content": doc,
                            "doc_id": meta.get("doc_id"),
                            "page_refs": meta.get("page_refs"),
                            "content_hash": meta.get("content_hash"),
                        }
                        if "bbox" in meta and meta["bbox"]:
                            item["bbox"] = json.loads(meta["bbox"])
                        out.append(item)
                return out
            except Exception as e:
                return [{"error": f"Vector search failed: {e}"}]

        @tool
        def structured_query(sql_query: str, doc_ids: list[str] | None = None) -> list[dict]:
            """
            Run a SQL query over extracted fact tables to answer numerical/structured questions.
            Table schema: facts(id, doc_id, fact_key, fact_value, page_number, context).
            Example: SELECT * FROM facts WHERE fact_key LIKE '%revenue%'
            """
            return self._fact_extractor.query(sql_query, doc_ids)

        self._tools = [
            pageindex_navigate,
            semantic_search,
            structured_query,
        ]

        if self._llm:
            self._agent_executor = create_react_agent(self._llm, self._tools)
        else:
            self._agent_executor = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, question: str, doc_ids: list[str] | None = None) -> QueryResponse:
        """
        Run query agent to answer a question and generate provenance.
        Returns QueryResponse containing the answer and ProvenanceChain.
        """
        if not self._agent_executor:
            # Fallback when no LLM
            ans = "No LLM configured. Please set openrouter_api_key in config to use QueryAgent."
            return QueryResponse(answer=ans, provenance_chain=ProvenanceChain(citations=[]))

        # Setup context
        context_msg = f"User question: {question}\n"
        if doc_ids:
            context_msg += f"Limit search to these documents: {doc_ids}\n"

        # Invoke LangGraph ReAct agent
        response = self._agent_executor.invoke({"messages": [HumanMessage(content=context_msg)]})
        messages = response["messages"]
        final_answer = messages[-1].content if messages else "No answer generated."

        # Extract provenance from ToolMessages
        citations = self._extract_provenance(messages, final_answer)

        return QueryResponse(
            answer=str(final_answer),
            provenance_chain=ProvenanceChain(citations=citations)
        )

    def verify_claim(self, claim: str, doc_ids: list[str] | None = None) -> AuditResult:
        """
        Audit Mode (FR-5.4). Verify a claim against documents.
        Returns AuditResult with boolean verified and supporting citation.
        """
        if not self._agent_executor:
            return AuditResult(
                verified=False,
                message="No LLM configured.",
                citation=None
            )

        prompt = (
            f"Please verify this claim: '{claim}'.\n"
            "Use the tools to search the documents. "
            "Reply strictly with EXACTLY 'VERIFIED' or 'REFUTED' or 'UNVERIFIABLE' on the first line, "
            "followed by a short explanation of why."
        )
        if doc_ids:
            prompt += f"\nLimit search to: {doc_ids}."

        response = self._agent_executor.invoke({"messages": [HumanMessage(content=prompt)]})
        messages = response["messages"]
        final_ans = messages[-1].content if messages else ""

        ans_upper = str(final_ans).upper()
        verified = ans_upper.startswith("VERIFIED")

        message_lines = str(final_ans).split("\n", 1)
        msg_out = message_lines[1].strip() if len(message_lines) > 1 else final_ans

        citations = self._extract_provenance(messages, final_ans)
        citation = citations[0] if citations else None

        if not verified and not ans_upper.startswith("REFUTED"):
            msg_out = "not found / unverifiable. " + str(msg_out)

        return AuditResult(
            verified=verified,
            citation=citation,
            message=str(msg_out)
        )

    def _extract_provenance(self, messages: Sequence[BaseMessage], final_answer: str) -> list[ProvenanceCitation]:
        """
        Heuristically extract provenance from ToolMessages and LLM usage.
        Reads the tool call outputs to build the ProvenanceChain.
        """
        citations = []
        for msg in messages:
            if isinstance(msg, ToolMessage):
                try:
                    data = json.loads(msg.content)
                    if isinstance(data, list):
                        for item in data[:3]: # Cap
                            if isinstance(item, dict):
                                doc_id = item.get("doc_id", "unknown")
                                page_refs = item.get("page_refs") or item.get("page_number") or item.get("page_start") or 1
                                # If page_refs is a string like "1,2", parse it
                                if isinstance(page_refs, str) and "," in page_refs:
                                    page_number = int(page_refs.split(",")[0])
                                elif isinstance(page_refs, list) and page_refs:
                                    page_number = page_refs[0]
                                else:
                                    page_number = int(page_refs)

                                content_hash = item.get("content_hash")
                                snippet = (
                                    item.get("content") or 
                                    item.get("summary") or 
                                    item.get("fact_value")
                                )
                                if snippet:
                                    snippet = str(snippet)[:100] + "..."
                                    
                                bbox_data = item.get("bbox")
                                bbox = None
                                if bbox_data and isinstance(bbox_data, dict):
                                    from src.models.document_profile import BoundingBox
                                    try:
                                        bbox = BoundingBox(**bbox_data)
                                    except Exception:
                                        pass

                                cit = ProvenanceCitation(
                                    document_name=doc_id,
                                    page_number=page_number,
                                    bbox=bbox,
                                    content_hash=content_hash,
                                    content_snippet=snippet,
                                )
                                citations.append(cit)
                except Exception:
                    pass
        
        # Deduplicate while preserving order
        unique = []
        seen = set()
        for c in citations:
            key = (c.document_name, c.page_number, c.content_hash)
            if key not in seen:
                seen.add(key)
                unique.append(c)

        return unique

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from typing import Any

from core.models import DocumentChunk, Finding, ParsedDocument

LOGGER = logging.getLogger(__name__)

MODEL = "gpt-4o"


def get_api_key() -> str | None:
    """Resolve the OpenAI API key from the environment, then Streamlit secrets.

    Checked in order so the same code works locally (env var) and on Streamlit
    Community Cloud (st.secrets). Streamlit is imported lazily so the CLI scripts
    that import this module never require streamlit, and any streamlit error
    (not installed, or no secrets file present) degrades to ``None``.
    """
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key
    try:
        import streamlit as st

        return st.secrets.get("OPENAI_API_KEY")
    except Exception:
        return None

NARRATIVE_FALLBACK = (
    "Narrative generation unavailable. Review finding details and required "
    "documents above."
)

NARRATIVE_TOPIC_MAP: dict[str, list[str]] = {
    "AR_DEREG_001": [
        "project_status",
        "project_identity",
        "issuance_completeness",
        "deregistration",
        "cancellations",
    ],
    "AR_ISS_GAP_001": [
        "issuance_completeness",
        "monitoring_coverage_period_2",
        "project_status",
        "issuance",
        "monitoring",
        "cancellations",
        "deregistration",
    ],
    "AR_ADD_001": ["additionality_demonstration", "additionality"],
    "AR_BASE_001": ["baseline_methodology"],
    "AR_MON_001": ["monitoring_coverage_period_2", "monitoring"],
    "AR_VAL_001": ["validator"],
    "AR_REG_001": ["registration"],
    "AR_PERM_001": ["permanence_risk", "permanence"],
    "GEN_METH_001": ["baseline_methodology", "project_identity"],
    "GEN_VAL_001": ["validator"],
    "GEN_ADD_001": ["additionality_demonstration", "additionality"],
    "GEN_MON_001": ["monitoring_coverage_period_2", "monitoring"],
    "GEN_REG_001": ["registration", "project_identity"],
    "GEN_CRED_001": ["crediting_period"],
    "GEN_TITLE_001": ["project_identity"],
    "GEN_COUNTRY_001": ["project_identity"],
}

NARRATIVE_SYSTEM_PROMPT = """
You are a carbon market due diligence analyst writing a professional review memo.

You are given:
- A risk finding with a flag code and severity
- Confirmed facts from the project documents
- Evidence cards linking facts to claims
- Source text excerpts from the documents

Write ONE paragraph (4-6 sentences) explaining:
1. What this finding means for this project specifically — not generically
2. What the evidence shows about this issue
3. What remains uncertain or unresolved
4. What a reviewer should investigate next

Rules:
- Ground every claim in the provided facts or source excerpts
- Do not introduce information not present in the inputs
- Do not make a legal determination or investment recommendation
- Do not state whether the finding is resolved — that is the human reviewer's judgment
- Write in plain professional English
- Do not use bullet points or headers
- Do not repeat the flag code or severity label in the paragraph
""".strip()
KEYWORDS = [
    "methodology",
    "additionality",
    "baseline",
    "emission",
    "reduction",
    "validation",
    "registration",
    "monitoring",
    "verification",
    "issuance",
    "crediting",
    "permanence",
    "cancellation",
    "deregistration",
    "approval",
    "validator",
    "verifier",
    "dnv",
    "aenor",
    "bureau veritas",
    "tuv",
    "carbon",
    "co2",
    "tco2",
    "cer",
    "vcu",
    "gold standard",
    "verra",
    "unfccc",
]

SYSTEM_PROMPT = """
You are a carbon market due diligence analyst.
You extract structured facts from carbon project documents.

Extract ONLY facts that are explicitly stated in the text. Do not infer,
estimate, or add information not present in the chunk.

For each fact found, return a JSON object with:
  label: short descriptive name (snake_case)
  value: the extracted value as a string
  unit: unit of measurement if applicable, else null
  claim_topic: one of:
    baseline_methodology | additionality | emission_reductions |
    crediting_period | validator | verifier | registration |
    deregistration | issuance | monitoring | permanence |
    host_party_approval | cancellations | project_identity | other
  confidence: float 0.0-1.0 based on how explicitly the fact is stated
  evidence_quote: the exact phrase from the chunk text that supports this
    fact, under 100 characters
  page_number: the page number from the chunk

Return ONLY a JSON object with a single key 'facts' containing an array of
fact objects. Example: {"facts": [...]}
If no facts are found, return {"facts": []}.
No preamble. No markdown. No explanation.
""".strip()


def extract_facts_from_chunk(
    chunk: DocumentChunk,
    document: ParsedDocument,
    project_context: dict,
) -> list[dict]:
    api_key = get_api_key()
    if not api_key:
        LOGGER.info("OPENAI_API_KEY not set; skipping AI extraction")
        return []
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        user_message = (
            f"Project context: {json.dumps(project_context, sort_keys=True)}\n\n"
            f"Document type: {document.document_type}\n"
            f"Page: {chunk.page_number}\n\n"
            f"Text:\n{chunk.text[:2000]}"
        )
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0,
            max_tokens=1000,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        payload = json.loads(_strip_markdown_fences(content))
        facts = payload.get("facts", [])
        return facts if isinstance(facts, list) else []
    except json.JSONDecodeError as exc:
        LOGGER.warning("Could not parse OpenAI extraction response: %s", exc)
        return []
    except Exception as exc:  # pragma: no cover - defensive API boundary
        LOGGER.error("OpenAI extraction failed: %s", exc)
        return []


def extract_facts_from_document(
    document: ParsedDocument,
    chunks: list[DocumentChunk],
    project_context: dict,
    max_chunks: int = 30,
    min_confidence: float = 0.7,
) -> list[dict]:
    selected = _select_chunks(chunks, max_chunks)
    facts: list[dict] = []
    for chunk in selected:
        for fact in extract_facts_from_chunk(chunk, document, project_context):
            fact["chunk_id"] = chunk.chunk_id
            fact["document_id"] = document.document_id
            facts.append(fact)
    return _dedupe_and_filter(facts, min_confidence)


def build_proposals(facts: list[dict], project_id: str) -> list[dict]:
    return [
        {
            "proposal_id": f"prop-{uuid.uuid4().hex[:8]}",
            "project_id": project_id,
            "status": "pending",
            "ai_extracted": fact,
            "human_edit": None,
            "reviewer_action": None,
            "reviewed_at": None,
            "audit_note": None,
        }
        for fact in facts
    ]


def _select_chunks(chunks: list[DocumentChunk], max_chunks: int) -> list[DocumentChunk]:
    if len(chunks) <= max_chunks:
        return chunks
    selected: list[DocumentChunk] = []
    selected_ids: set[str] = set()
    for chunk in chunks:
        probe = f"{chunk.heading or ''}\n{_first_line(chunk.text)}".lower()
        if any(keyword in probe for keyword in KEYWORDS):
            selected.append(chunk)
            selected_ids.add(chunk.chunk_id)
        if len(selected) >= max_chunks:
            return selected
    remaining = [chunk for chunk in chunks if chunk.chunk_id not in selected_ids]
    slots = max_chunks - len(selected)
    if slots <= 0:
        return selected
    if slots >= len(remaining):
        return selected + remaining
    step = max(len(remaining) / slots, 1)
    for index in range(slots):
        selected.append(remaining[min(int(index * step), len(remaining) - 1)])
    return selected[:max_chunks]


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _dedupe_and_filter(facts: list[dict], min_confidence: float) -> list[dict]:
    by_key: dict[tuple[str, str], dict] = {}
    for fact in facts:
        confidence = _float(fact.get("confidence", 0))
        if confidence < min_confidence:
            continue
        key = (str(fact.get("label", "")).lower(), str(fact.get("value", "")).lower())
        if key not in by_key or confidence > _float(by_key[key].get("confidence", 0)):
            fact["confidence"] = confidence
            by_key[key] = fact
    return list(by_key.values())


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.IGNORECASE)


def generate_finding_narrative(
    finding: Finding,
    relevant_facts: list[dict],
    relevant_cards: list[dict],
    relevant_chunks: list[dict],
    project_context: dict,
) -> str:
    api_key = get_api_key()
    if not api_key:
        return NARRATIVE_FALLBACK
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        facts_payload = json.dumps(relevant_facts[:5], sort_keys=True, default=str)
        cards_payload = json.dumps(relevant_cards[:3], sort_keys=True, default=str)
        excerpt_lines = []
        for chunk in relevant_chunks[:3]:
            text = str(chunk.get("text", ""))[:500]
            page = chunk.get("page_number", "?")
            excerpt_lines.append(f"- (page {page}) {text}")
        excerpts = "\n".join(excerpt_lines) if excerpt_lines else "(none)"

        user_message = (
            f"Project: {project_context.get('title')}\n"
            f"Host country: {project_context.get('host_country')}\n"
            f"Methodology: {project_context.get('methodology')}\n\n"
            f"Finding:\n"
            f"  Flag: {finding.flag_code}\n"
            f"  Severity: {finding.severity}\n"
            f"  Description: {finding.description}\n"
            f"  Evidence gap: {finding.evidence_gap}\n"
            f"  Required documents: {finding.required_documents}\n\n"
            f"Confirmed facts relevant to this finding:\n{facts_payload}\n\n"
            f"Evidence cards:\n{cards_payload}\n\n"
            f"Source excerpts:\n{excerpts}\n\n"
            "Write the narrative paragraph now."
        )
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": NARRATIVE_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
            max_tokens=400,
        )
        content = response.choices[0].message.content or ""
        text = content.strip()
        return text or NARRATIVE_FALLBACK
    except Exception as exc:  # pragma: no cover - defensive API boundary
        LOGGER.error("Narrative generation failed for %s: %s", finding.flag_code, exc)
        return NARRATIVE_FALLBACK


def generate_all_narratives(
    findings: list[Finding],
    facts: list[dict],
    evidence_cards: list[dict],
    chunks_by_document: dict,
    project_context: dict,
) -> dict[str, str]:
    if not get_api_key():
        LOGGER.info("Narrative generation skipped — OPENAI_API_KEY not set")
        return {finding.flag_code: NARRATIVE_FALLBACK for finding in findings}

    chunk_index = _build_chunk_index(chunks_by_document)
    narratives: dict[str, str] = {}
    for finding in findings:
        topics = NARRATIVE_TOPIC_MAP.get(finding.flag_code)
        if topics is None:
            selected_facts = list(facts)
            selected_cards = list(evidence_cards)
        else:
            selected_facts = [
                fact for fact in facts if fact.get("claim_topic") in topics
            ]
            selected_cards = [
                card for card in evidence_cards if card.get("claim_topic") in topics
            ]

        selected_chunks = _select_relevant_chunks(selected_facts, chunk_index)

        narratives[finding.flag_code] = generate_finding_narrative(
            finding,
            selected_facts,
            selected_cards,
            selected_chunks,
            project_context,
        )
    return narratives


def _build_chunk_index(chunks_by_document: dict) -> dict[str, dict]:
    index: dict[str, dict] = {}
    if not chunks_by_document:
        return index
    for chunks in chunks_by_document.values():
        for chunk in chunks or []:
            if isinstance(chunk, dict):
                chunk_id = chunk.get("chunk_id")
                if chunk_id:
                    index[chunk_id] = chunk
            else:
                chunk_id = getattr(chunk, "chunk_id", None)
                if chunk_id:
                    index[chunk_id] = {
                        "chunk_id": chunk_id,
                        "text": getattr(chunk, "text", ""),
                        "page_number": getattr(chunk, "page_number", None),
                        "document_id": getattr(chunk, "document_id", ""),
                    }
    return index


def _select_relevant_chunks(
    facts: list[dict], chunk_index: dict[str, dict]
) -> list[dict]:
    seen: set[str] = set()
    ranked: list[tuple[float, dict]] = []
    for fact in facts:
        confidence = _float(fact.get("confidence", 0))
        for citation_id in fact.get("citation_ids", []) or []:
            chunk = chunk_index.get(citation_id)
            if chunk is None:
                continue
            chunk_id = chunk.get("chunk_id", citation_id)
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            ranked.append((confidence, chunk))
        chunk_id = fact.get("chunk_id")
        if chunk_id and chunk_id in chunk_index and chunk_id not in seen:
            seen.add(chunk_id)
            ranked.append((confidence, chunk_index[chunk_id]))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [chunk for _confidence, chunk in ranked[:3]]

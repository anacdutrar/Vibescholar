"""Lazy single-process composition of the real evidence-search runtime."""

from dataclasses import dataclass
from functools import lru_cache

from app.agents.evidence_evaluator import EvidenceEvaluator
from app.agents.search_agent import SearchAgent
from app.core.config import settings
from app.llm.exceptions import LLMConfigurationError
from app.llm.factory import create_evidence_evaluator_client
from app.llm.ollama_client import LLMComponent, OllamaClient
from app.services.academic_search_executor import AcademicSearchExecutor
from app.services.citation_resolution_executor import CitationResolutionExecutor
from app.services.evidence_search_state import EvidenceSearchSessionStore
from app.services.evidence_search_workflow import EvidenceSearchWorkflow
from app.services.reference_filter_service import ReferenceFilterService


@dataclass(frozen=True)
class EvidenceSearchRuntime:
    """Workflow and its shared in-memory session store."""

    workflow: EvidenceSearchWorkflow
    session_store: EvidenceSearchSessionStore


@lru_cache(maxsize=1)
def get_evidence_search_runtime() -> EvidenceSearchRuntime:
    """Compose the real runtime lazily without performing network calls."""
    if settings.USE_MOCK:
        raise LLMConfigurationError(
            "The real evidence-search runtime is disabled while USE_MOCK=true."
        )
    search_client = OllamaClient(component=LLMComponent.SEARCH_AGENT)
    evaluator_client = create_evidence_evaluator_client(settings)
    session_store = EvidenceSearchSessionStore(
        ttl_seconds=settings.SEARCH_SESSION_TTL_SECONDS,
        max_sessions=settings.MAX_IN_MEMORY_SEARCH_SESSIONS,
    )
    academic_executor = AcademicSearchExecutor()
    citation_executor = CitationResolutionExecutor()
    workflow = EvidenceSearchWorkflow(
        search_agent=SearchAgent(search_client),
        evidence_evaluator=EvidenceEvaluator(evaluator_client),
        reference_filter=ReferenceFilterService(),
        session_store=session_store,
        academic_search_executor=academic_executor,
        citation_resolution_executor=citation_executor,
    )
    return EvidenceSearchRuntime(workflow=workflow, session_store=session_store)

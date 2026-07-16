"""Public facade for legacy mock or real workflow-backed evidence search."""

from __future__ import annotations

import time
from typing import Iterable

from sqlalchemy.orm import Session

from app.agents.schemas import CitationHint, EvidenceVerdict
from app.core.config import settings
from app.core.logging import logger
from app.models.reference import EvidenceSuggestion, ProjectReference
from app.repositories.project_settings_repository import ProjectSettingsRepository
from app.repositories.reference_repository import ReferenceRepository
from app.schemas.response import EvidenceSuggestionOut
from app.services.evidence_search_state import EvidenceSearchSessionStore, SearchSessionKey
from app.services.evidence_search_workflow import EvidenceSearchRoundResult, EvidenceSearchWorkflow
from app.services.legacy_mock_evidence_search import LegacyMockEvidenceSearch
from app.services.reference_filter_service import ReferenceFilterCriteria


class EvidenceService:
    """Validate, delegate, persist, and adapt evidence results to the public schema."""

    def __init__(
        self,
        *,
        workflow: EvidenceSearchWorkflow | None = None,
        session_store: EvidenceSearchSessionStore | None = None,
        legacy_search: LegacyMockEvidenceSearch | None = None,
    ) -> None:
        if (workflow is None) != (session_store is None):
            raise ValueError("workflow and session_store must be supplied together")
        self._workflow = workflow
        self._session_store = session_store
        self._legacy_search = legacy_search

    async def search(
        self,
        db: Session,
        sentence_text: str,
        project_id: int,
        *,
        user_id: int,
        document_version_id: int,
        sentence_uuid: str,
        citation_hints: list[CitationHint] | None = None,
        excluded_reference_ids: set[int] | None = None,
    ) -> list[EvidenceSuggestionOut]:
        """Return the existing public suggestion contract for one sentence search."""
        started_at = time.perf_counter()
        self._validate_input(
            sentence_text, project_id, user_id, document_version_id, sentence_uuid
        )
        project_settings = ProjectSettingsRepository.get_by_project_id(db, project_id)
        if project_settings is None:
            project_settings = ProjectSettingsRepository.create_default(db, project_id)

        excluded = excluded_reference_ids or set()
        mode = "mock" if settings.USE_MOCK else "real"
        logger.info(
            "ai.pipeline.evidence_service.started mode=%s user_id=%s project_id=%s "
            "version_id=%s citation_hints=%s excluded_references=%s",
            mode,
            user_id,
            project_id,
            document_version_id,
            len(citation_hints or []),
            len(excluded),
        )
        if settings.USE_MOCK:
            suggestions = self._search_mock(
                db,
                sentence_text,
                project_id,
                document_version_id,
                sentence_uuid,
                project_settings,
                citation_hints or [],
                excluded,
            )
            logger.info(
                "ai.pipeline.evidence_service.completed mode=mock suggestions=%s "
                "duration=%.4f termination=%s",
                len(suggestions),
                time.perf_counter() - started_at,
                "suggestions_returned" if suggestions else "no_suggestions",
            )
            return suggestions

        workflow, session_store = self._real_runtime()
        result = await workflow.execute_round(
            user_id=user_id,
            document_version_id=document_version_id,
            sentence_uuid=sentence_uuid,
            sentence=sentence_text,
            citation_hints=citation_hints or None,
            filter_criteria=ReferenceFilterCriteria(
                publication_year_min=project_settings.publication_year_min,
                publication_year_max=project_settings.publication_year_max,
                only_open_access=project_settings.only_open_access,
            ),
        )
        logger.info(
            "ai.pipeline.evidence_service.workflow_result source=%s status=%s round=%s "
            "evaluated=%s strong=%s partial=%s failure_code=%s",
            result.source.value,
            result.session_status.value,
            result.round_number,
            result.evaluation_summary.evaluated_candidates,
            result.evaluation_summary.strong_support_count,
            result.evaluation_summary.partial_support_count,
            result.failure_code or "none",
        )
        suggestions = await self._persist_real_result(
            db=db,
            session_store=session_store,
            key=(user_id, document_version_id, sentence_uuid),
            project_id=project_id,
            document_version_id=document_version_id,
            sentence_uuid=sentence_uuid,
            max_suggestions=project_settings.max_suggestions,
            result=result,
        )
        logger.info(
            "ai.pipeline.evidence_service.completed mode=real suggestions=%s duration=%.4f "
            "termination=%s source=%s status=%s",
            len(suggestions),
            time.perf_counter() - started_at,
            "suggestions_returned" if suggestions else "no_public_suggestions",
            result.source.value,
            result.session_status.value,
        )
        return suggestions

    def _real_runtime(self) -> tuple[EvidenceSearchWorkflow, EvidenceSearchSessionStore]:
        if self._workflow is not None and self._session_store is not None:
            return self._workflow, self._session_store
        from app.services.evidence_search_runtime import get_evidence_search_runtime

        runtime = get_evidence_search_runtime()
        return runtime.workflow, runtime.session_store

    async def _persist_real_result(
        self,
        *,
        db: Session,
        session_store: EvidenceSearchSessionStore,
        key: SearchSessionKey,
        project_id: int,
        document_version_id: int,
        sentence_uuid: str,
        max_suggestions: int,
        result: EvidenceSearchRoundResult,
    ) -> list[EvidenceSuggestionOut]:
        """Persist support and mark only successfully validated public items."""
        evaluation_keys = {item.candidate_key for item in result.evaluations}
        async with session_store.search_guard(key) as session:
            support_keys = session.strong_support_keys | session.partial_support_keys
            persisted: dict[str, ProjectReference] = {}
            try:
                for candidate_key, transient in session.candidates.items():
                    if candidate_key not in support_keys:
                        continue
                    reference, _ = ReferenceRepository.get_or_create_candidate(
                        db, project_id, transient.reference
                    )
                    persisted[candidate_key] = reference
                db.commit()
                for candidate_key, reference in persisted.items():
                    db.refresh(reference)
                    session.candidates[candidate_key] = session.candidates[
                        candidate_key
                    ].model_copy(update={"persisted_reference_id": reference.id})
            except Exception as exc:
                db.rollback()
                logger.warning(
                    "ai.pipeline.evidence_service.failed stage=reference_persistence "
                    "project_id=%s version_id=%s error_type=%s rollback=true",
                    project_id,
                    document_version_id,
                    type(exc).__name__,
                )
                raise

            existing = ReferenceRepository.get_suggestions_by_version_and_sentence(
                db, document_version_id, sentence_uuid
            )
            approved = [item for item in existing if item.status == "APPROVED"]
            rejected_reference_ids = {
                item.reference_id for item in existing if item.status == "REJECTED"
            }
            selectable_keys: list[str] = []
            for evaluation in result.evaluations:
                if evaluation.verdict not in {
                    EvidenceVerdict.STRONG_SUPPORT,
                    EvidenceVerdict.PARTIAL_SUPPORT,
                }:
                    continue
                reference = persisted.get(evaluation.candidate_key)
                if reference is None or reference.id in rejected_reference_ids:
                    continue
                selectable_keys.append(evaluation.candidate_key)
            selectable_keys = selectable_keys[:max(max_suggestions, 0)]

            staged: list[EvidenceSuggestion] = []
            try:
                for candidate_key in selectable_keys:
                    reference = persisted[candidate_key]
                    suggestion, _ = ReferenceRepository.get_or_stage_pending_suggestion(
                        db, document_version_id, sentence_uuid, reference.id
                    )
                    if suggestion.status == "REJECTED":
                        continue
                    suggestion.reference = reference
                    staged.append(suggestion)

                public_result = [
                    EvidenceSuggestionOut.model_validate(item)
                    for item in self._unique_suggestions([*approved, *staged])
                ]
                db.commit()
            except Exception as exc:
                db.rollback()
                logger.warning(
                    "ai.pipeline.evidence_service.failed stage=suggestion_persistence "
                    "version_id=%s error_type=%s rollback=true",
                    document_version_id,
                    type(exc).__name__,
                )
                raise

            included_reference_ids = {item.reference_id for item in public_result}
            presented_keys = {
                candidate_key
                for candidate_key in selectable_keys
                if persisted[candidate_key].id in included_reference_ids
                and candidate_key in evaluation_keys
            }
            logger.info(
                "evidence.real.completed version_id=%s evaluated=%s persisted=%s presented=%s public=%s",
                document_version_id,
                len(result.evaluations),
                len(persisted),
                len(presented_keys),
                len(public_result),
            )
            for candidate_key in presented_keys:
                session.candidates[candidate_key] = session.candidates[
                    candidate_key
                ].model_copy(update={"shown_to_user": True})
            session.presented_candidate_keys.update(presented_keys)
            session.touch()
            return public_result

    def _search_mock(
        self,
        db: Session,
        sentence_text: str,
        project_id: int,
        document_version_id: int,
        sentence_uuid: str,
        project_settings,
        citation_hints: list[CitationHint],
        excluded_reference_ids: set[int],
    ) -> list[EvidenceSuggestionOut]:
        """Preserve the legacy offline path without constructing the real runtime."""
        legacy = self._legacy_search or LegacyMockEvidenceSearch()
        existing = ReferenceRepository.get_suggestions_by_version_and_sentence(
            db, document_version_id, sentence_uuid
        )
        existing_by_reference = {item.reference_id: item for item in existing}
        citation_matches: list[ProjectReference] = []
        for hint in citation_hints:
            citation_matches.extend(
                ReferenceRepository.find_citation_matches(
                    db,
                    project_id,
                    doi=hint.doi,
                    author=hint.author,
                    year=hint.year,
                )
            )
        matches = legacy.search_references(
            db,
            sentence_text,
            project_id,
            project_settings,
            excluded_reference_ids,
        )
        provider_count = len(matches)
        matches = list({item.id: item for item in [*citation_matches, *matches]}.values())
        if provider_count:
            matches = matches[:provider_count]

        suggestions = [item for item in existing if item.status == "APPROVED"]
        returned_ids = {item.id for item in suggestions}
        citation_ids = {item.id for item in citation_matches}
        for reference in matches:
            suggestion = existing_by_reference.get(reference.id)
            if suggestion is None:
                suggestion = EvidenceSuggestion(
                    document_version_id=document_version_id,
                    sentence_uuid=sentence_uuid,
                    reference_id=reference.id,
                    status="PENDING",
                )
                ReferenceRepository.create_suggestion(db, suggestion)
                existing_by_reference[reference.id] = suggestion
            suggestion.reference = reference
            if (
                suggestion.status != "REJECTED" or reference.id in citation_ids
            ) and suggestion.id not in returned_ids:
                suggestions.append(suggestion)
                returned_ids.add(suggestion.id)
        return [EvidenceSuggestionOut.model_validate(item) for item in suggestions]

    @staticmethod
    def _unique_suggestions(
        suggestions: Iterable[EvidenceSuggestion],
    ) -> list[EvidenceSuggestion]:
        return list({item.id: item for item in suggestions}.values())

    @staticmethod
    def _validate_input(
        sentence_text: str,
        project_id: int,
        user_id: int,
        document_version_id: int,
        sentence_uuid: str,
    ) -> None:
        if not isinstance(sentence_text, str) or not sentence_text.strip():
            raise ValueError("sentence_text must contain non-whitespace text")
        if min(project_id, user_id, document_version_id) <= 0:
            raise ValueError("project, user, and document-version IDs must be positive")
        if not isinstance(sentence_uuid, str) or not sentence_uuid.strip():
            raise ValueError("sentence_uuid must contain non-whitespace text")

"""Deterministic filtering of transient academic reference candidates.

Qualis filtering will be implemented only after ISSN/e-ISSN enrichment by the
future QualisLookupService. This module does not infer or simulate Qualis data.
"""

from collections import Counter
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.tools.schemas import ReferenceCandidate


class FilterReason(str, Enum):
    """Deterministic reason why a transient reference candidate was rejected."""

    PUBLICATION_BEFORE_MINIMUM = "publication_before_minimum"
    PUBLICATION_AFTER_MAXIMUM = "publication_after_maximum"
    NOT_OPEN_ACCESS = "not_open_access"


class ReferenceFilterCriteria(BaseModel):
    """Database-independent criteria derived later from project settings."""

    model_config = ConfigDict(frozen=True)

    publication_year_min: int | None = Field(
        default=None,
        description="Minimum accepted publication year when candidate metadata is known.",
    )
    publication_year_max: int | None = Field(
        default=None,
        description="Maximum accepted publication year when candidate metadata is known.",
    )
    only_open_access: bool = Field(
        default=False,
        description="Reject candidates explicitly identified as not open access.",
    )

    @model_validator(mode="after")
    def validate_year_range(self) -> "ReferenceFilterCriteria":
        """Reject an inverted publication-year interval."""
        if (
            self.publication_year_min is not None
            and self.publication_year_max is not None
            and self.publication_year_min > self.publication_year_max
        ):
            raise ValueError("publication_year_min cannot exceed publication_year_max")
        return self


class RejectedReferenceCandidate(BaseModel):
    """Safe rejection record containing identity and deterministic reasons only."""

    model_config = ConfigDict(frozen=True)

    candidate_key: str = Field(
        min_length=1,
        description="Canonical transient candidate identity.",
    )
    reasons: tuple[FilterReason, ...] = Field(
        min_length=1,
        description="Unique deterministic rejection reasons in evaluation order.",
    )

    @model_validator(mode="after")
    def validate_unique_reasons(self) -> "RejectedReferenceCandidate":
        """Prevent duplicate reasons for one rejected candidate."""
        if len(set(self.reasons)) != len(self.reasons):
            raise ValueError("rejection reasons must be unique")
        return self


class ReferenceFilterResult(BaseModel):
    """Typed partition of accepted candidates and safe rejection records."""

    accepted: list[ReferenceCandidate] = Field(
        description="Candidates accepted in their original relative order.",
    )
    rejected: list[RejectedReferenceCandidate] = Field(
        description="Safe rejection records in their original relative order.",
    )
    total_received: int = Field(ge=0, description="Number of candidates evaluated.")
    total_accepted: int = Field(ge=0, description="Number of accepted candidates.")
    total_rejected: int = Field(ge=0, description="Number of rejected candidates.")
    reason_counts: dict[FilterReason, int] = Field(
        description="Number of rejected candidates associated with each reason.",
    )

    @model_validator(mode="after")
    def validate_counts(self) -> "ReferenceFilterResult":
        """Keep aggregate counts aligned with the result partition."""
        if self.total_accepted != len(self.accepted):
            raise ValueError("total_accepted must equal the accepted list length")
        if self.total_rejected != len(self.rejected):
            raise ValueError("total_rejected must equal the rejected list length")
        if self.total_received != self.total_accepted + self.total_rejected:
            raise ValueError("total_received must equal accepted plus rejected")

        expected_counts = Counter(
            reason
            for rejected_candidate in self.rejected
            for reason in rejected_candidate.reasons
        )
        normalized_counts = {reason: count for reason, count in self.reason_counts.items() if count}
        if normalized_counts != dict(expected_counts):
            raise ValueError("reason_counts must match the rejection records")
        return self


class ReferenceFilterService:
    """Apply deterministic project criteria without I/O or candidate mutation."""

    def filter_candidates(
        self,
        candidates: list[ReferenceCandidate],
        criteria: ReferenceFilterCriteria,
    ) -> ReferenceFilterResult:
        """Partition candidates while preserving order and unknown metadata.

        Missing years are not treated as zero. Unknown open-access status is not
        treated as closed. Such candidates remain accepted unless another known
        metadata field violates an enabled criterion.
        """
        validated_criteria = ReferenceFilterCriteria.model_validate(criteria)
        accepted: list[ReferenceCandidate] = []
        rejected: list[RejectedReferenceCandidate] = []
        reason_counts: Counter[FilterReason] = Counter()

        for item in candidates:
            candidate = ReferenceCandidate.model_validate(item)
            reasons = self._rejection_reasons(candidate, validated_criteria)
            if reasons:
                rejected.append(
                    RejectedReferenceCandidate(
                        candidate_key=candidate.candidate_key,
                        reasons=reasons,
                    )
                )
                reason_counts.update(reasons)
            else:
                accepted.append(candidate)

        return ReferenceFilterResult(
            accepted=accepted,
            rejected=rejected,
            total_received=len(candidates),
            total_accepted=len(accepted),
            total_rejected=len(rejected),
            reason_counts=dict(reason_counts),
        )

    @staticmethod
    def _rejection_reasons(
        candidate: ReferenceCandidate,
        criteria: ReferenceFilterCriteria,
    ) -> tuple[FilterReason, ...]:
        """Return all deterministic reasons applicable to one candidate."""
        reasons: list[FilterReason] = []
        if candidate.year is not None:
            if (
                criteria.publication_year_min is not None
                and candidate.year < criteria.publication_year_min
            ):
                reasons.append(FilterReason.PUBLICATION_BEFORE_MINIMUM)
            if (
                criteria.publication_year_max is not None
                and candidate.year > criteria.publication_year_max
            ):
                reasons.append(FilterReason.PUBLICATION_AFTER_MAXIMUM)
        if criteria.only_open_access and candidate.is_open_access is False:
            reasons.append(FilterReason.NOT_OPEN_ACCESS)
        return tuple(reasons)

"""Database-independent public contracts for local Qualis lookups."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class QualisLookupStatus(str, Enum):
    """Possible deterministic outcomes of an ISSN-only local Qualis lookup."""

    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    INVALID_ISSN = "INVALID_ISSN"
    DATASET_UNAVAILABLE = "DATASET_UNAVAILABLE"
    AMBIGUOUS = "AMBIGUOUS"


class QualisRecord(BaseModel):
    """One traceable classification imported from the local official dataset."""

    model_config = ConfigDict(frozen=True)

    issn: str = Field(description="Canonical journal ISSN in NNNN-NNNX form.")
    title: str = Field(description="Journal title supplied by the imported dataset.")
    stratum: str = Field(description="Qualis stratum supplied by the imported dataset.")
    parent_area: str = Field(description="Parent evaluation area supplied by the dataset.")
    quadrennium: str = Field(description="Evaluation quadrennium represented by the dataset.")


class QualisLookupResult(BaseModel):
    """Typed lookup result that never equates absence with low quality."""

    model_config = ConfigDict(frozen=True)

    status: QualisLookupStatus = Field(description="Deterministic lookup outcome.")
    record: QualisRecord | None = Field(
        default=None,
        description="Unique reliable classification, present only when status is FOUND.",
    )

    @model_validator(mode="after")
    def validate_record_status(self) -> "QualisLookupResult":
        """Keep the optional record coherent with the lookup status."""
        if self.status is QualisLookupStatus.FOUND and self.record is None:
            raise ValueError("FOUND requires a QualisRecord")
        if self.status is not QualisLookupStatus.FOUND and self.record is not None:
            raise ValueError("only FOUND may include a QualisRecord")
        return self

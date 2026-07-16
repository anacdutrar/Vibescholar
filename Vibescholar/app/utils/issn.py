"""Public ISSN normalization shared by providers and the local Qualis dataset."""

import re


def normalize_issn(value: str | None) -> str | None:
    """Return canonical ``NNNN-NNNX`` form or ``None`` for invalid input."""
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    normalized = re.sub(
        r"^(?:e\s*)?issn\s*:\s*",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    compact = re.sub(r"[\s-]", "", normalized).upper()
    if not re.fullmatch(r"\d{7}[\dX]", compact):
        return None
    return f"{compact[:4]}-{compact[4:]}"

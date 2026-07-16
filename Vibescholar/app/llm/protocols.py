"""Minimal typed contracts shared by structured LLM consumers."""

from collections.abc import Sequence
from typing import Protocol, TypeVar

from pydantic import BaseModel


ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


class StructuredChatClient(Protocol):
    """Backend-neutral structured-output operation required by the evaluator."""

    async def structured_chat(
        self,
        messages: Sequence[dict[str, object]],
        response_model: type[ResponseModelT],
    ) -> ResponseModelT:
        """Return one response validated as the requested Pydantic model."""
        ...

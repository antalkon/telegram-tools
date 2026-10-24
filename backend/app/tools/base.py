"""Tool plug-in contract. Every panel tool registers a Tool; the job runner executes it."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.jobs.runner import JobContext


class Tool(ABC):
    id: ClassVar[str]
    title: ClassVar[str]
    description: ClassVar[str] = ""
    Input: ClassVar[type[BaseModel]]

    @abstractmethod
    async def run(self, ctx: "JobContext", params: BaseModel) -> dict[str, Any]:
        """Do the work, report progress via ctx.update(), return a JSON-able result summary."""


_registry: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    _registry[tool.id] = tool
    return tool


def get_tool(tool_id: str) -> Tool:
    return _registry[tool_id]


def all_tools() -> list[Tool]:
    return list(_registry.values())

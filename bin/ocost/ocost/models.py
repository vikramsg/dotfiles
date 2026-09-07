"""Validate consumed API fields without dropping unconsumed response data."""

from dataclasses import dataclass
from datetime import date
from math import fsum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator


class APIModel(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True, allow_inf_nan=False)


class Cache(APIModel):
    read: int | float
    write: int | float


class Tokens(APIModel):
    input: int | float
    output: int | float
    reasoning: int | float
    cache: Cache

    def values(self) -> list[int | float]:
        return [self.input, self.output, self.reasoning, self.cache.read, self.cache.write]


class ModelRef(APIModel):
    providerID: str
    id: str
    variant: str | None = None


class ModelUsage(APIModel):
    model: ModelRef
    cost: int | float
    steps: Annotated[int, Field(ge=0)]
    tokens: Tokens


class Activity(APIModel):
    date: date
    steps: Annotated[int, Field(ge=0)]

    @field_validator("date", mode="before")
    @classmethod
    def parse_date(cls, value: object) -> object:
        return date.fromisoformat(value) if isinstance(value, str) else value


class ToolTotals(APIModel):
    calls: Annotated[int, Field(ge=0)]
    succeeded: Annotated[int, Field(ge=0)]
    failed: Annotated[int, Field(ge=0)]
    unfinished: Annotated[int, Field(ge=0)]


class Tools(APIModel):
    mode: str
    totals: ToolTotals


class TimeRange(APIModel):
    start: int | float = Field(alias="from")
    to: int | float


class Stats(APIModel):
    range: TimeRange
    cost: int | float
    sessions: Annotated[int, Field(ge=0)]
    subagents: Annotated[int, Field(ge=0)]
    prompts: Annotated[int, Field(ge=0)]
    steps: Annotated[int, Field(ge=0)]
    tokens: Tokens
    models: list[ModelUsage]
    activity: list[Activity] | None = None
    activeDays: Annotated[int, Field(ge=0)] | None = None
    streak: Annotated[int, Field(ge=0)] | None = None
    tools: Tools | None = None

    def has_usage(self) -> bool:
        return any([self.cost, self.sessions, self.subagents, self.prompts, self.steps, *self.tokens.values()]) or bool(
            self.models
        )


class StatsResponse(APIModel):
    data: Stats


class Project(APIModel):
    id: Annotated[str, Field(min_length=1)]
    canonical: Annotated[str, Field(min_length=1)]


@dataclass(frozen=True)
class ProjectUsage:
    project: Project
    usage: StatsResponse


@dataclass(frozen=True)
class Report:
    overall: StatsResponse
    projects: list[ProjectUsage]

    def ordered_projects(self) -> list[ProjectUsage]:
        return sorted(self.projects, key=lambda row: (-row.usage.data.cost, row.project.canonical, row.project.id))

    def cost_difference(self) -> float:
        return fsum(row.usage.data.cost for row in self.projects) - self.overall.data.cost

    def json_data(self) -> dict[str, JsonValue]:
        result = self.overall.model_dump(mode="json", by_alias=True, exclude_unset=True)
        result["projects"] = [
            {
                "project": row.project.model_dump(mode="json", by_alias=True, exclude_unset=True),
                "usage": row.usage.model_dump(mode="json", by_alias=True, exclude_unset=True),
            }
            for row in self.ordered_projects()
        ]
        return result

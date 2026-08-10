from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RepositoryCatalogueEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    github_repository: str = Field(min_length=1)
    default_branch: str = Field(min_length=1)

    @field_validator("name", "description", "github_repository", "default_branch")
    @classmethod
    def reject_blank_metadata(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("repository catalogue metadata must not be blank")
        return value


class CoordinatorWorkspaceConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    root: Path
    repositories: tuple[RepositoryCatalogueEntry, ...]

    @model_validator(mode="after")
    def unique_repository_names(self) -> CoordinatorWorkspaceConfig:
        names = [repository.name for repository in self.repositories]
        if len(names) != len(set(names)):
            raise ValueError("coordinator repository names must be unique")
        return self

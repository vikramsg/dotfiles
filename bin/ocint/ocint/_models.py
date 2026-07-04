from pathlib import Path

from pydantic import BaseModel, ConfigDict


class OutputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResolvedPaths(OutputModel):
    config_path: Path
    db_path: Path
    config_exists: bool
    db_exists: bool

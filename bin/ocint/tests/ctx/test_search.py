import inspect

from ocint.ctx.models import CtxSearchRequest
from ocint.ctx.search import CtxSearch
from ocint.ctx.service import CtxService
from ocint.opencode.repository import OpenCodeRepository

from tests.fixtures.opencode_db import create_opencode_db


def test_search_defaults_to_primary_sessions(tmp_path) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")
    search = CtxSearch(OpenCodeRepository(db_path))

    results = search.search(CtxSearchRequest(query="subagent only marker"))

    assert results == []

    subagent_results = search.search(CtxSearchRequest(query="subagent only marker", include_subagents=True))
    assert {result.session_id for result in subagent_results} == {"s-sub"}


def test_search_filters_by_file_workspace_session_and_terms(tmp_path) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")
    search = CtxSearch(OpenCodeRepository(db_path))

    results = search.search(CtxSearchRequest(query="native event marker", workspace="repo-directory-only", file="AGENTS.md", session_id="s-primary", terms=["stable"]))

    assert results
    assert all(result.session_id == "s-primary" for result in results)
    assert {result.workspace for result in results} == {"/work/repo-directory-only"}
    assert all("AGENTS.md" in result.source_path for result in results if result.source_path)


def test_search_file_filter_matches_all_payload_paths(tmp_path) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")
    search = CtxSearch(OpenCodeRepository(db_path))

    for file_filter in [
        "bin/ocint/ocint/ctx/search.py",
        "implementation_notes.md",
        "bin/ocint/tests/ctx/test_sql.py",
    ]:
        results = search.search(CtxSearchRequest(query="file.patch", file=file_filter))

        assert [result.event_id for result in results] == ["evt_native_patch"]


def test_ctx_service_search_contract_is_explicit() -> None:
    signature = inspect.signature(CtxService.search)

    assert list(signature.parameters) == ["self", "request"]
    assert all(parameter.kind is not inspect.Parameter.VAR_POSITIONAL for parameter in signature.parameters.values())
    assert all(parameter.kind is not inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values())

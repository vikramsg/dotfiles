import copy
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from ocost.models import Project, ProjectUsage, Report, StatsResponse


@pytest.fixture
def stats_payload():
    tokens = {"input": 1200, "output": 250, "reasoning": 90, "cache": {"read": 8000, "write": 500}}
    return {
        "requestMetadata": {"preserve": True},
        "data": {
            "range": {"from": 0, "to": 1000},
            "cost": 12.1250004,
            "sessions": 3,
            "subagents": 1,
            "prompts": 8,
            "steps": 20,
            "tokens": copy.deepcopy(tokens),
            "activity": [{"date": "2026-09-05", "extra": 42}],
            "models": [
                {
                    "model": {"providerID": "azure", "id": "same-model", "variant": "medium"},
                    "cost": 2.1250004,
                    "steps": 5,
                    "tokens": copy.deepcopy(tokens),
                },
                {
                    "model": {"providerID": "other", "id": "same-model"},
                    "cost": 10,
                    "steps": 15,
                    "tokens": copy.deepcopy(tokens),
                },
            ],
        },
    }


@pytest.fixture
def report(stats_payload):
    return Report(
        StatsResponse.model_validate(stats_payload),
        [ProjectUsage(Project(id="p&1", canonical="/work/dotfiles"), StatsResponse.model_validate(stats_payload))],
    )


@pytest.fixture
def cli_environment(tmp_path):
    return {**os.environ, "HOME": str(tmp_path / "home"), "XDG_STATE_HOME": str(tmp_path), "NO_COLOR": "1"}


@pytest.fixture
def executable():
    return str(Path(sys.executable).with_name("ocost"))


@pytest.fixture
def api_server(stats_payload, tmp_path):
    """A real local HTTP fixture for CLI behaviour, never the user's service."""
    state = {
        "requests": [],
        "status": 200,
        "project_status": 200,
        "projects": [{"id": "p&1", "canonical": "/work/dotfiles", "sandboxes": []}],
        "payload": stats_payload,
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlsplit(self.path)
            query = parse_qs(url.query)
            state["requests"].append((url.path, query, self.headers.get("Authorization")))
            status = state["project_status"] if "project" in query else state["status"]
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if status != 200:
                self.wfile.write(b'{"error":"do not echo response bodies"}')
                return
            if url.path == "/api/project":
                body = state["projects"]
            else:
                body = copy.deepcopy(state["payload"])
                body["data"]["range"] = {"from": int(query["from"][0]), "to": int(query["to"][0])}
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{server.server_port}"
    registration = tmp_path / "opencode/service.json"
    registration.parent.mkdir()
    registration.write_text(json.dumps({"url": state["url"], "password": "fixture-password"}))
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

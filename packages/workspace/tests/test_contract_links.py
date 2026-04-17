"""Integration tests for contract-based link detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from contracts.models import RepoDescriptor
from workspace import detect_contract_links


OPENAPI_YAML = """\
openapi: 3.0.3
info: { title: svc-a, version: "1.0.0" }
paths:
  /users/{id}:
    get:
      operationId: getUserById
      responses:
        "200": { description: OK }
"""


def _write_repo(
    root: Path,
    name: str,
    files: dict[str, str],
) -> RepoDescriptor:
    path = root / name
    path.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        fp = path / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
    return RepoDescriptor(name=name, path=path)


class TestContractLinks:
    def test_emits_consumes_link_for_matching_request(self, tmp_path: Path):
        repo_a = _write_repo(
            tmp_path,
            "svc-a",
            {"openapi.yaml": OPENAPI_YAML},
        )
        consumer_code = """\
import requests

def fetch_user(user_id: str):
    return requests.get(f\"/users/{user_id}\")
"""
        repo_b = _write_repo(
            tmp_path,
            "svc-b",
            {"client.py": consumer_code},
        )

        links = detect_contract_links([repo_a, repo_b])
        assert len(links) == 1
        cl = links[0]
        assert cl.from_repo == "svc-b"
        assert cl.to_repo == "svc-a"
        assert cl.kind == "consumes"
        assert cl.endpoint == {"method": "GET", "path": "/users/{id}"}

    def test_no_links_when_no_consumer(self, tmp_path: Path):
        repo_a = _write_repo(tmp_path, "svc-a", {"openapi.yaml": OPENAPI_YAML})
        repo_b = _write_repo(tmp_path, "svc-b", {"main.py": "def hi():\n    pass\n"})
        links = detect_contract_links([repo_a, repo_b])
        assert links == []

    def test_does_not_self_link(self, tmp_path: Path):
        repo = _write_repo(
            tmp_path,
            "svc-a",
            {
                "openapi.yaml": OPENAPI_YAML,
                "client.py": "requests.get(\"/users/123\")\n",
            },
        )
        links = detect_contract_links([repo])
        assert links == []

    def test_js_fetch_matches(self, tmp_path: Path):
        repo_a = _write_repo(tmp_path, "svc-a", {"openapi.yaml": OPENAPI_YAML})
        repo_b = _write_repo(
            tmp_path,
            "svc-b",
            {"app.js": "fetch('/users/abc').then(r => r.json());\n"},
        )
        links = detect_contract_links([repo_a, repo_b])
        assert len(links) == 1
        assert links[0].from_repo == "svc-b"

    def test_dedup_across_files(self, tmp_path: Path):
        repo_a = _write_repo(tmp_path, "svc-a", {"openapi.yaml": OPENAPI_YAML})
        files = {
            "a.py": "requests.get('/users/1')\n",
            "b.py": "requests.get('/users/2')\n",
            "c.py": "requests.get('/users/3')\n",
        }
        repo_b = _write_repo(tmp_path, "svc-b", files)
        links = detect_contract_links([repo_a, repo_b])
        assert len(links) == 1

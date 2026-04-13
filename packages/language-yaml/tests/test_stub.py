"""Tests for language_yaml.YamlAnalyzer."""

from __future__ import annotations

from pathlib import Path

from contracts.interfaces import DependencyEdge, LanguageAnalyzer, Symbol
from language_yaml import YamlAnalyzer

K8S_DEPLOYMENT = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
  namespace: default
spec:
  replicas: 3
"""

GITHUB_ACTIONS = """\
name: CI
on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
"""

HELM_CHART = """\
apiVersion: v2
name: my-chart
description: A test Helm chart
version: 0.1.0
"""

GENERIC_YAML = """\
database:
  host: localhost
  port: 5432
server:
  port: 8080
"""


def test_import():
    import language_yaml  # noqa: F401


def test_implements_protocol():
    assert isinstance(YamlAnalyzer(), LanguageAnalyzer)


def test_returns_list(tmp_path: Path):
    result = YamlAnalyzer().analyze(tmp_path / "nonexistent.yaml")
    assert isinstance(result, list)


def test_k8s_resource_detection(tmp_path: Path):
    f = tmp_path / "deployment.yaml"
    f.write_text(K8S_DEPLOYMENT)
    results = YamlAnalyzer().analyze(f)

    k8s = [s for s in results if isinstance(s, Symbol) and s.kind == "k8s_resource"]
    assert len(k8s) == 1
    assert "Deployment" in k8s[0].name


def test_github_actions_workflow_detection(tmp_path: Path):
    f = tmp_path / "ci.yaml"
    f.write_text(GITHUB_ACTIONS)
    results = YamlAnalyzer().analyze(f)

    workflows = [s for s in results if isinstance(s, Symbol) and s.kind == "github_actions_workflow"]
    assert len(workflows) == 1
    assert workflows[0].name == "CI"


def test_github_actions_job_detection(tmp_path: Path):
    f = tmp_path / "ci.yaml"
    f.write_text(GITHUB_ACTIONS)
    results = YamlAnalyzer().analyze(f)

    jobs = [s for s in results if isinstance(s, Symbol) and s.kind == "github_actions_job"]
    job_names = {j.name for j in jobs}
    assert "test" in job_names
    assert "lint" in job_names


def test_helm_chart_detection(tmp_path: Path):
    chart_dir = tmp_path / "mychart"
    chart_dir.mkdir()
    f = chart_dir / "Chart.yaml"
    f.write_text(HELM_CHART)
    results = YamlAnalyzer().analyze(f)

    helm = [s for s in results if isinstance(s, Symbol) and s.kind == "helm_chart"]
    assert len(helm) == 1
    assert helm[0].name == "my-chart"


def test_generic_yaml_returns_no_symbols(tmp_path: Path):
    """Generic YAML files (not k8s/helm/GHA) no longer emit yaml_key noise."""
    f = tmp_path / "config.yaml"
    f.write_text(GENERIC_YAML)
    results = YamlAnalyzer().analyze(f)

    # yaml_key symbols removed — generic config YAML is noise for code context
    keys = [s for s in results if isinstance(s, Symbol) and s.kind == "yaml_key"]
    assert keys == [], "generic YAML should not emit yaml_key symbols"
    assert results == [], "generic YAML should return an empty list"


def test_non_dict_yaml_returns_empty(tmp_path: Path):
    f = tmp_path / "list.yaml"
    f.write_text("- item1\n- item2\n")
    results = YamlAnalyzer().analyze(f)
    assert results == []


def test_invalid_yaml_returns_empty(tmp_path: Path):
    f = tmp_path / "bad.yaml"
    f.write_text("{ invalid: yaml: content")
    results = YamlAnalyzer().analyze(f)
    assert results == []


def test_invalid_path_returns_empty():
    results = YamlAnalyzer().analyze(Path("/nonexistent/file.yaml"))
    assert results == []


DOCKER_COMPOSE = """\
version: "3.9"
services:
  web:
    image: nginx:latest
    ports:
      - "80:80"
  db:
    image: postgres:15
    environment:
      POSTGRES_DB: app
  redis:
    image: redis:7
"""

GITHUB_ACTIONS_WITH_NEEDS = """\
name: Deploy
on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

  test:
    runs-on: ubuntu-latest
    needs: build
    steps:
      - uses: actions/checkout@v3

  deploy:
    runs-on: ubuntu-latest
    needs: [build, test]
    steps:
      - uses: actions/checkout@v3
"""


def test_docker_compose_detection(tmp_path: Path):
    f = tmp_path / "docker-compose.yaml"
    f.write_text(DOCKER_COMPOSE)
    results = YamlAnalyzer().analyze(f)

    compose_files = [s for s in results if isinstance(s, Symbol) and s.kind == "compose_file"]
    assert len(compose_files) == 1

    services = [s for s in results if isinstance(s, Symbol) and s.kind == "compose_service"]
    names = {s.name for s in services}
    assert "web" in names
    assert "db" in names
    assert "redis" in names


def test_github_actions_needs_edges(tmp_path: Path):
    f = tmp_path / "deploy.yaml"
    f.write_text(GITHUB_ACTIONS_WITH_NEEDS)
    results = YamlAnalyzer().analyze(f)

    dep_edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "depends_on"]
    assert len(dep_edges) >= 1

    from_to = {(e.from_symbol, e.to_symbol) for e in dep_edges}
    # test depends on build
    assert ("test", "build") in from_to
    # deploy depends on both
    assert ("deploy", "build") in from_to
    assert ("deploy", "test") in from_to


def test_line_numbers_nonzero_for_k8s(tmp_path: Path):
    f = tmp_path / "deployment.yaml"
    f.write_text(K8S_DEPLOYMENT)
    results = YamlAnalyzer().analyze(f)

    k8s = [s for s in results if isinstance(s, Symbol) and s.kind == "k8s_resource"]
    assert k8s[0].line_start > 0


def test_line_numbers_nonzero_for_workflow(tmp_path: Path):
    f = tmp_path / "ci.yaml"
    f.write_text(GITHUB_ACTIONS)
    results = YamlAnalyzer().analyze(f)

    workflows = [s for s in results if isinstance(s, Symbol) and s.kind == "github_actions_workflow"]
    assert workflows[0].line_start > 0

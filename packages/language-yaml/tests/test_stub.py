"""Tests for language_yaml.YamlAnalyzer."""

from __future__ import annotations

from pathlib import Path

from contracts.interfaces import LanguageAnalyzer, Symbol
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


def test_generic_yaml_top_level_keys(tmp_path: Path):
    f = tmp_path / "config.yaml"
    f.write_text(GENERIC_YAML)
    results = YamlAnalyzer().analyze(f)

    keys = [s for s in results if isinstance(s, Symbol) and s.kind == "yaml_key"]
    names = {k.name for k in keys}
    assert "database" in names
    assert "server" in names


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

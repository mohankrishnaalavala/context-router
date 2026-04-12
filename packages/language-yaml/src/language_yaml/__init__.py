"""context-router-language-yaml: YAML language analyzer plugin.

Uses PyYAML to extract structural symbols from YAML files. Detects
Kubernetes resources, GitHub Actions workflows/jobs, Helm charts, and
generic top-level key paths.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from contracts.interfaces import DependencyEdge, Symbol

_K8S_KINDS = {
    "Deployment", "Service", "ConfigMap", "Secret", "Pod",
    "StatefulSet", "DaemonSet", "Ingress", "Namespace",
    "CronJob", "Job", "HorizontalPodAutoscaler",
    "PersistentVolumeClaim", "ServiceAccount", "Role", "ClusterRole",
}


class YamlAnalyzer:
    """Language analyzer for YAML files.

    Registered under the 'context_router.language_analyzers' entry-points
    group with key 'yaml'. Uses PyYAML for parsing since YAML is structured
    data rather than code — Tree-sitter adds no value here.
    """

    def analyze(self, path: Path) -> list[Symbol | DependencyEdge]:
        """Analyze a YAML file and return structural symbols.

        Args:
            path: Absolute path to the .yaml/.yml file.

        Returns:
            List of Symbol objects (no DependencyEdge for YAML in Phase 1).
        """
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            data = yaml.safe_load(text)
        except Exception:
            return []

        if not isinstance(data, dict):
            return []

        results: list[Symbol | DependencyEdge] = []

        # Helm chart detection
        if path.name == "Chart.yaml":
            name = data.get("name", path.parent.name)
            results.append(
                Symbol(
                    name=str(name),
                    kind="helm_chart",
                    file=path,
                    line_start=0,
                    line_end=0,
                    language="yaml",
                    signature=f"chart: {name}",
                )
            )
            return results

        # Kubernetes resource detection
        if "apiVersion" in data and "kind" in data:
            kind = str(data.get("kind", "Resource"))
            resource_name = ""
            metadata = data.get("metadata", {})
            if isinstance(metadata, dict):
                resource_name = str(metadata.get("name", ""))
            display = f"{kind}/{resource_name}" if resource_name else kind
            results.append(
                Symbol(
                    name=display,
                    kind="k8s_resource",
                    file=path,
                    line_start=0,
                    line_end=0,
                    language="yaml",
                    signature=f"apiVersion: {data.get('apiVersion')} kind: {kind}",
                )
            )
            return results

        # GitHub Actions workflow detection
        if "on" in data or True in data:  # YAML parses 'on' as True key
            jobs = data.get("jobs") or (data.get(True, {}) if True in data else None)
            # Disambiguate: must also have 'jobs' to be a workflow
            if "jobs" in data:
                # Workflow-level symbol
                workflow_name = data.get("name", path.stem)
                results.append(
                    Symbol(
                        name=str(workflow_name),
                        kind="github_actions_workflow",
                        file=path,
                        line_start=0,
                        line_end=0,
                        language="yaml",
                        signature=f"workflow: {workflow_name}",
                    )
                )
                # One symbol per job
                jobs_data = data.get("jobs", {})
                if isinstance(jobs_data, dict):
                    for job_id, job_def in jobs_data.items():
                        job_name = job_id
                        if isinstance(job_def, dict):
                            job_name = job_def.get("name", job_id)
                        results.append(
                            Symbol(
                                name=str(job_name),
                                kind="github_actions_job",
                                file=path,
                                line_start=0,
                                line_end=0,
                                language="yaml",
                                signature=f"job: {job_name}",
                            )
                        )
                return results

        # Generic YAML without a recognised schema (e.g. Helm values.yaml,
        # plain config files): emit nothing.  Top-level key names are not
        # meaningful context for code navigation and only add noise.
        return results

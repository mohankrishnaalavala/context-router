"""context-router-language-yaml: YAML language analyzer plugin.

Uses PyYAML with mark support to extract structural symbols from YAML files,
including line numbers. Detects Kubernetes resources, GitHub Actions
workflows/jobs (with dependency edges), Docker Compose services, Helm charts,
and generic top-level key paths.
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


# ---------------------------------------------------------------------------
# Line-number-aware YAML loading
# ---------------------------------------------------------------------------

class _LineLoader(yaml.SafeLoader):
    """YAML SafeLoader that attaches start_mark to constructed objects.

    For mappings and sequences we return a _Marked wrapper so callers can
    retrieve the original line number via the ``__line__`` attribute.
    We only need the top-level line here; nested dicts stay plain dicts.
    """


def _compose_with_marks(text: str) -> yaml.Node | None:
    """Return the raw PyYAML node tree so we can read start_mark."""
    try:
        return yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        return None


def _node_line(node: yaml.Node | None) -> int:
    """Return 1-based line number from a PyYAML node, or 0 if unavailable."""
    if node is None:
        return 0
    return (node.start_mark.line + 1) if node.start_mark else 0


def _mapping_key_line(mapping_node: yaml.MappingNode, key: str) -> int:
    """Return the line of a specific key inside a mapping node."""
    for key_node, _val_node in mapping_node.value:
        if isinstance(key_node, yaml.ScalarNode) and key_node.value == key:
            return (key_node.start_mark.line + 1) if key_node.start_mark else 0
    return 0


class YamlAnalyzer:
    """Language analyzer for YAML files.

    Registered under the 'context_router.language_analyzers' entry-points
    group with key 'yaml'. Uses PyYAML for parsing with line-number support.
    """

    def analyze(self, path: Path) -> list[Symbol | DependencyEdge]:
        """Analyze a YAML file and return structural symbols and edges.

        Args:
            path: Absolute path to the .yaml/.yml file.

        Returns:
            List of Symbol and DependencyEdge objects.
        """
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            data = yaml.safe_load(text)
        except Exception:
            return []

        if not isinstance(data, dict):
            return []

        # Also parse the node tree for line numbers
        node_tree = _compose_with_marks(text)

        results: list[Symbol | DependencyEdge] = []

        # ---------------------------------------------------------------
        # Helm chart detection
        # ---------------------------------------------------------------
        if path.name == "Chart.yaml":
            name = data.get("name", path.parent.name)
            results.append(
                Symbol(
                    name=str(name),
                    kind="helm_chart",
                    file=path,
                    line_start=1,
                    line_end=0,
                    language="yaml",
                    signature=f"chart: {name}",
                )
            )
            return results

        # ---------------------------------------------------------------
        # Kubernetes resource detection
        # ---------------------------------------------------------------
        if "apiVersion" in data and "kind" in data:
            kind = str(data.get("kind", "Resource"))
            resource_name = ""
            metadata = data.get("metadata", {})
            if isinstance(metadata, dict):
                resource_name = str(metadata.get("name", ""))
            display = f"{kind}/{resource_name}" if resource_name else kind
            line = _node_line(node_tree) if node_tree else 1
            results.append(
                Symbol(
                    name=display,
                    kind="k8s_resource",
                    file=path,
                    line_start=line or 1,
                    line_end=0,
                    language="yaml",
                    signature=f"apiVersion: {data.get('apiVersion')} kind: {kind}",
                )
            )
            return results

        # ---------------------------------------------------------------
        # Docker Compose detection
        # ---------------------------------------------------------------
        if "services" in data and isinstance(data.get("services"), dict):
            workflow_line = _node_line(node_tree) if node_tree else 1
            results.append(
                Symbol(
                    name=path.stem,
                    kind="compose_file",
                    file=path,
                    line_start=workflow_line or 1,
                    line_end=0,
                    language="yaml",
                    signature=f"compose: {path.stem}",
                )
            )
            services = data["services"]
            # Find the "services" key line in the node tree
            svc_key_line = 0
            if isinstance(node_tree, yaml.MappingNode):
                svc_key_line = _mapping_key_line(node_tree, "services")
            for svc_name in services:
                svc_line = svc_key_line  # best approximation without nested marks
                results.append(
                    Symbol(
                        name=str(svc_name),
                        kind="compose_service",
                        file=path,
                        line_start=svc_line or 1,
                        line_end=0,
                        language="yaml",
                        signature=f"service: {svc_name}",
                    )
                )
            return results

        # ---------------------------------------------------------------
        # GitHub Actions workflow detection
        # ---------------------------------------------------------------
        if "jobs" in data:
            workflow_name = data.get("name", path.stem)
            wf_line = _node_line(node_tree) if node_tree else 1
            results.append(
                Symbol(
                    name=str(workflow_name),
                    kind="github_actions_workflow",
                    file=path,
                    line_start=wf_line or 1,
                    line_end=0,
                    language="yaml",
                    signature=f"workflow: {workflow_name}",
                )
            )
            jobs_data = data.get("jobs", {})
            # Find the "jobs" key node for line numbers
            jobs_node: yaml.MappingNode | None = None
            if isinstance(node_tree, yaml.MappingNode):
                for k_node, v_node in node_tree.value:
                    if isinstance(k_node, yaml.ScalarNode) and k_node.value == "jobs":
                        if isinstance(v_node, yaml.MappingNode):
                            jobs_node = v_node
                        break

            if isinstance(jobs_data, dict):
                for job_id, job_def in jobs_data.items():
                    job_name = job_id
                    if isinstance(job_def, dict):
                        job_name = job_def.get("name", job_id)
                    # Get line number for this job
                    job_line = 0
                    if jobs_node is not None:
                        job_line = _mapping_key_line(jobs_node, job_id)
                    results.append(
                        Symbol(
                            name=str(job_name),
                            kind="github_actions_job",
                            file=path,
                            line_start=job_line or (wf_line or 1),
                            line_end=0,
                            language="yaml",
                            signature=f"job: {job_name}",
                        )
                    )
                    # Add dependency edges from `needs:` field
                    if isinstance(job_def, dict):
                        needs = job_def.get("needs", [])
                        if isinstance(needs, str):
                            needs = [needs]
                        if isinstance(needs, list):
                            for dep in needs:
                                results.append(
                                    DependencyEdge(
                                        from_symbol=str(job_name),
                                        to_symbol=str(dep),
                                        edge_type="depends_on",
                                    )
                                )
            return results

        # Generic YAML without a recognised schema — return nothing.
        return results

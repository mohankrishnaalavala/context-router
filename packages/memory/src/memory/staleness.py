"""Git-based staleness detection for memory observation files_touched paths."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

_DORMANT_DAYS = 90


class ObservationStalenessChecker:
    """Checks whether observation files_touched paths are still present in git HEAD.

    Uses batch git ls-files for efficiency; caches per (repo_root, path) pair so
    repeated calls within one retrieve_observations() call cost only one subprocess.
    """

    def __init__(self) -> None:
        self._present_cache: dict[tuple[str, str], bool] = {}

    def check_batch(self, files_touched: list[str], repo_root: Path) -> None:
        """Pre-populate the presence cache for a list of files in one git call.

        Call before a loop of check() calls to avoid N separate subprocesses.
        """
        if not files_touched:
            return
        root_key = str(repo_root)
        to_check = [f for f in files_touched if (root_key, f) not in self._present_cache]
        if not to_check:
            return
        try:
            result = subprocess.run(
                ["git", "ls-files", "--", *to_check],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                # Not a git repo or other error — assume all present (no false positives)
                for f in to_check:
                    self._present_cache[(root_key, f)] = True
                return
            present_set = set(result.stdout.splitlines())
            for f in to_check:
                self._present_cache[(root_key, f)] = f in present_set
        except Exception:  # noqa: BLE001
            for f in to_check:
                self._present_cache[(root_key, f)] = True

    def check(
        self,
        files_touched: list[str],
        repo_root: Path,
        created_at: datetime | None = None,
    ) -> tuple[bool, str]:
        """Return ``(is_stale, reason)`` for an observation.

        Detection order (per design spec §3.2):
        1. missing_file — any path fails git ls-files → hard-stale.
        2. renamed — git log --follow --diff-filter=R finds a rename (also hard-stale;
           the caller should use ``reason`` to attempt path migration).
        3. dormant — age > 90 days (informational: is_stale=False, reason set).

        Returns ``(False, "")`` when all files are present and the observation is not dormant.
        """
        if not files_touched:
            return False, ""

        root_key = str(repo_root)
        missing = [f for f in files_touched if not self._is_present(f, repo_root, root_key)]

        if missing:
            first = missing[0]
            new_path = self._find_rename(first, repo_root)
            if new_path:
                return True, f"renamed: {first} -> {new_path}"
            return True, f"missing_file: {first}"

        # Dormant: informational only — is_stale stays False
        if created_at is not None:
            now = datetime.now(tz=timezone.utc)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            age_days = (now - created_at).days
            if age_days > _DORMANT_DAYS:
                return False, f"dormant: {age_days}d old"

        return False, ""

    def _is_present(self, file_path: str, repo_root: Path, root_key: str) -> bool:
        if (root_key, file_path) not in self._present_cache:
            self.check_batch([file_path], repo_root)
        return self._present_cache.get((root_key, file_path), True)

    def _find_rename(self, file_path: str, repo_root: Path) -> str | None:
        """Return the new path if ``file_path`` was renamed in git history, else None."""
        try:
            result = subprocess.run(
                [
                    "git", "log",
                    "--follow", "--diff-filter=R",
                    "--name-status", "--format=",
                    "--", file_path,
                ],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                for line in result.stdout.splitlines():
                    parts = line.split("\t")
                    if len(parts) >= 3 and parts[0].startswith("R"):
                        return parts[2]
        except Exception:  # noqa: BLE001
            pass
        return None

"""Resolve Cobertura ``class/@filename`` values into repo-relative paths.

Coverage.py records one ``<source>`` root per ``--cov=`` target. With
``--cov=modules --cov=auto_deinterlancer`` the report therefore carries two
roots (the repo itself and ``modules/``) and each filename is stored relative
to the *longest* matching root -- ``modules/core/config.py`` is written as
``core/config.py`` and ``modules/__init__.py`` collapses to ``__init__.py``.
Consumers that treat those strings as repo-relative silently mis-attribute or
drop files, so every reader goes through :func:`resolve_repo_relative` first.
"""

from __future__ import annotations

from pathlib import Path


def normalize_path(value: str) -> str:
    """Return ``value`` with Windows separators folded to forward slashes."""
    return value.replace("\\", "/").strip()


def _trim_trailing_separators(path: str) -> str:
    """Trim trailing separators without changing filesystem root paths."""
    if path == "/" or (len(path) == 3 and path[0].isalpha() and path[1:] == ":/"):
        return path
    return path.rstrip("/")


def extract_source_roots(root) -> list[str]:
    """Return the normalized ``<sources>`` roots declared by a Cobertura root."""
    roots = []
    for source in root.findall(".//sources/source"):
        text = (source.text or "").strip()
        if text:
            roots.append(_trim_trailing_separators(normalize_path(text)))
    return roots


def _relative_to_root(candidate: Path, repo_root: str, fallback: str) -> str:
    """Express ``candidate`` against ``repo_root``, falling back when unrelated."""
    try:
        return normalize_path(str(candidate.relative_to(repo_root)))
    except ValueError:
        return fallback


def _probe_source_roots(normalized: str, source_roots: list[str]) -> str | None:
    """Return the repo-relative path of the first source root holding ``normalized``."""
    repo_root = min(source_roots, key=len)
    for candidate_root in sorted(source_roots, key=len, reverse=True):
        candidate = Path(candidate_root) / normalized
        if candidate.is_file():
            return _relative_to_root(candidate, repo_root, normalized)
    return None


def resolve_repo_relative(filename: str, source_roots: list[str]) -> str | None:
    """Return ``filename`` as a repo-relative path, or ``None`` when unresolvable.

    Each source root is joined with ``filename`` longest-root-first and probed on
    disk; the first hit is re-expressed against the shortest (repository) root.
    Reports whose filenames are already repo-relative -- no ``<sources>``, or a
    synthetic report whose files are absent -- are passed through unchanged.
    """
    normalized = normalize_path(filename)
    if not normalized:
        return None
    if not source_roots:
        return normalized
    return _probe_source_roots(normalized, source_roots) or normalized

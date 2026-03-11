from __future__ import annotations

import re
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


_URL_RE = re.compile(r"^(https?://|git@)")

# Clone settings: shallow clone for speed; longer timeout for slow networks
_CLONE_DEPTH = 50
_CLONE_TIMEOUT_SEC = 300

# Clone directory under project: .cartography/_temp_clones/<repo_name>
_TEMP_CLONES_DIR = "_temp_clones"


def is_git_url(value: str) -> bool:
    v = value.strip()
    return bool(_URL_RE.match(v))


def _repo_name_from_url(repo_url: str) -> str:
    """
    Derive a safe directory name from the repo URL (e.g. org/repo -> org_repo).
    Used so clone path is .cartography/_temp_clones/org_repo instead of a random id.
    """
    url = repo_url.strip().rstrip("/")
    # Remove .git suffix
    if url.lower().endswith(".git"):
        url = url[:-4]
    # https://github.com/dbt-labs/jaffle-shop -> dbt-labs/jaffle-shop
    # git@github.com:dbt-labs/jaffle-shop.git -> dbt-labs/jaffle-shop
    for prefix in ("https://github.com/", "http://github.com/", "https://gitlab.com/", "http://gitlab.com/"):
        if url.lower().startswith(prefix):
            path = url[len(prefix):].strip("/")
            break
    else:
        if url.startswith("git@") and ":" in url:
            # git@github.com:org/repo
            path = url.split(":", 1)[1].strip("/")
        else:
            # Fallback: use last path segment or sanitize whole URL
            path = url.split("/")[-1] if "/" in url else url
    # Sanitize: only alphanumeric, dash, underscore
    safe = re.sub(r"[^\w\-]", "_", path).strip("_") or "repo"
    return safe[:200]  # avoid overly long paths


def _assert_clone_has_content(clone_root: Path) -> None:
    """Raise if the clone directory is missing or has no visible content (avoids empty graph)."""
    if not clone_root.is_dir():
        raise RuntimeError(f"Clone path is not a directory: {clone_root}")
    # Expect at least one non-.git entry (file or dir)
    entries = [p for p in clone_root.iterdir() if p.name != ".git"]
    if not entries:
        raise RuntimeError(f"Clone directory appears empty (only .git): {clone_root}")


def _temp_clones_root() -> Path:
    """
    Return .cartography/_temp_clones inside the project directory.
    """
    project_root = Path(__file__).resolve().parents[1]
    tmp_root = project_root / ".cartography" / _TEMP_CLONES_DIR
    tmp_root.mkdir(parents=True, exist_ok=True)
    return tmp_root


@contextmanager
def resolve_repo(repo: str, *, keep_clone: bool = False) -> Iterator[tuple[str, str | None]]:
    """
    Resolve a repo argument to a local filesystem path.

    - If `repo` is a local path, yield (resolved_path, None).
    - If `repo` is a Git URL, clone it into a workspace-local temp dir and yield (clone_path, None).
      Clone uses a bounded depth and propagates auth / network errors with clear messages.
    """
    repo = repo.strip()

    # Local path: just normalize and return.
    if not is_git_url(repo):
        p = str(Path(repo).expanduser().resolve())
        yield (p, None)
        return

    # Basic validation similar to the reference clone_repo_sandboxed example.
    if not (
        repo.startswith("https://")
        or repo.startswith("http://")
        or repo.startswith("git@")
    ):
        raise ValueError("repo must be an https or git SSH URL")

    tmp_root = _temp_clones_root()
    repo_name = _repo_name_from_url(repo)
    clone_dir = tmp_root / repo_name

    # Clone into a directory named after the repo (e.g. dbt-labs_jaffle-shop), not a random id.
    # Remove existing dir so git clone has an empty target.
    if clone_dir.exists():
        shutil.rmtree(clone_dir, ignore_errors=True)
    clone_dir.mkdir(parents=True)

    try:
        result = subprocess.run(
            ["git", "clone", "--depth", str(_CLONE_DEPTH), repo, str(clone_dir)],
            capture_output=True,
            text=True,
            timeout=_CLONE_TIMEOUT_SEC,
        )
        if result.returncode != 0:
            err = result.stderr or result.stdout or "Unknown error"
            if "Authentication failed" in err or "Permission denied" in err:
                raise PermissionError(f"Git authentication failed: {err}")
            raise RuntimeError(f"git clone failed: {err}")

        resolved_root = clone_dir.resolve()
        _assert_clone_has_content(resolved_root)
        yield (str(resolved_root), None)
    finally:
        if not keep_clone:
            shutil.rmtree(clone_dir, ignore_errors=True)


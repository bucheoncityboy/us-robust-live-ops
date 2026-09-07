"""Local secrets loader for KR-Hybrid ops (no secret printing)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent

# Keys used by this repo's ETL/runner path
KNOWN_KEYS = (
    "KRX_API_KEY",
    "KRX_ID",
    "KRX_PW",
    "DART_API_KEY",
    "TOSS_API_KEY",
    "TOSS_SECRET_KEY",
    "TOSS_ACCOUNT_SEQ",
)


def _parse_dotenv(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            out[key] = val
    return out


def candidate_env_paths(extra: Optional[Iterable[Path]] = None) -> list[Path]:
    """Ordered search paths for .env files (project first)."""
    paths: list[Path] = [
        ROOT / ".env",
        ROOT / ".env.local",
    ]
    # Optional nearby historical project (name may be Korean folder)
    ai_root = ROOT.parent
    if ai_root.exists():
        for child in ai_root.iterdir():
            if not child.is_dir():
                continue
            env = child / ".env"
            if env.exists():
                try:
                    txt = env.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if "DART_API_KEY" in txt or "KRX_API_KEY" in txt:
                    paths.append(env)
    if extra:
        paths.extend(Path(p) for p in extra)
    # de-dupe preserving order
    seen: set[str] = set()
    ordered: list[Path] = []
    for p in paths:
        key = str(p.resolve()) if p.exists() else str(p)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(p)
    return ordered


def load_env(
    *,
    override: bool = False,
    extra_paths: Optional[Iterable[Path]] = None,
    into_os: bool = True,
) -> Dict[str, str]:
    """Load key=value pairs from project .env first.

    Priority (project-local wins):
      1) ROOT/.env  and ROOT/.env.local  (always override OS for known keys)
      2) optional nearby AI project .env files (only fill missing keys)
      3) already-present OS env for any still-missing known keys

    - Does not print secret values.
    - ``override=True`` also forces nearby files over project values (rare).
    - Returns a dict of known keys only.
    """
    loaded: Dict[str, str] = {}

    def _apply(path: Path, *, force: bool) -> bool:
        """Apply one dotenv file. Returns True if file had any known keys."""
        if not path.exists() or not path.is_file():
            return False
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return False
        parsed = _parse_dotenv(raw)
        hit = False
        for k, v in parsed.items():
            if k not in KNOWN_KEYS:
                continue
            hit = True
            if not force and k in loaded and loaded.get(k):
                continue
            if not force and not override and k in loaded and loaded.get(k):
                continue
            loaded[k] = v
            if into_os and (force or override or not os.environ.get(k)):
                # project files: always write through so stale OS secrets cannot shadow
                if force or override:
                    os.environ[k] = v
                elif not os.environ.get(k):
                    os.environ[k] = v
            elif into_os and force:
                os.environ[k] = v
        return hit

    # 1) project env — authoritative for this repo
    project_paths = [ROOT / ".env", ROOT / ".env.local"]
    for path in project_paths:
        if _apply(path, force=True):
            # keep scanning .env.local after .env so local can refine
            pass
    # ensure project values are in OS even if OS had stale values
    for k, v in list(loaded.items()):
        if into_os and v:
            os.environ[k] = v

    # 2) nearby optional envs — fill only missing
    for path in candidate_env_paths(extra_paths):
        if path in project_paths or path.resolve() in {p.resolve() for p in project_paths if p.exists()}:
            continue
        _apply(path, force=False)

    # 3) residual OS env
    for k in KNOWN_KEYS:
        if k not in loaded and os.environ.get(k):
            loaded[k] = os.environ[k]
    return loaded


def get_secret(name: str, default: str = "") -> str:
    """Fetch one secret after load_env(); never logs value."""
    if name not in os.environ:
        load_env()
    return os.environ.get(name, default)


def secrets_status() -> Dict[str, bool]:
    """Presence map only (True if non-empty). Safe to print."""
    load_env()
    return {k: bool(os.environ.get(k, "").strip()) for k in KNOWN_KEYS}


def require_keys(*names: str) -> None:
    """Raise RuntimeError listing missing key *names* only."""
    load_env()
    missing = [n for n in names if not os.environ.get(n, "").strip()]
    if missing:
        raise RuntimeError(f"Missing required env keys: {', '.join(missing)}")


if __name__ == "__main__":
    st = secrets_status()
    print("env_paths_checked:")
    for p in candidate_env_paths():
        print(" -", p, "exists=" + str(p.exists()))
    print("secrets_present:")
    for k, ok in st.items():
        print(f" - {k}: {'yes' if ok else 'no'}")

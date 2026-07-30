from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PERSONAL = (
    re.compile(r"(?i)[A-Z]:\\Users\\[^\\\r\n]+"),
    re.compile(r"(?i)/(?:Users|home)/[^/\r\n]+"),
)


def main() -> int:
    errors: list[str] = []
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
    ).decode("utf-8").split("\0")
    for relative in filter(None, tracked):
        path = ROOT / relative
        normalized = relative.replace("\\", "/").casefold()
        if normalized.startswith("config/runtime/") or normalized.startswith("config/validation/"):
            errors.append(f"tracked runtime/validation evidence: {relative}")
        if normalized.startswith("nis_logs/") and path.name != ".gitkeep":
            errors.append(f"tracked NIS log data: {relative}")
        if path.name.casefold() in {".env", "credentials.json", "secrets.json", "id_rsa", "id_ed25519"}:
            errors.append(f"secret-like tracked file: {relative}")
        if path.suffix.casefold() not in {
            ".bat", ".cmd", ".json", ".md", ".ps1", ".py", ".toml", ".txt", ".yaml", ".yml"
        }:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        defines_sanitization = normalized in {
            "scripts/static_release_checks.py",
            "syringe_perfusion/diagnostics.py",
        }
        if not defines_sanitization and any(pattern.search(text) for pattern in PERSONAL):
            errors.append(f"personal path leakage: {relative}")
        if normalized.startswith("nis_cmd/") and re.search(r"(?i)\bCOM\d+\b", text):
            errors.append(f"numeric COM in wrapper: {relative}")
        if normalized == "config/pumps.json" and re.search(r'(?i)"port"\s*:\s*"COM\d+"', text):
            errors.append(f"numeric COM in public default: {relative}")
    for test in (ROOT / "tests").glob("test_*.py"):
        text = test.read_text(encoding="utf-8", errors="replace")
        if re.search(r"\bserial\.Serial\s*\(", text):
            errors.append(f"test may open a real serial port: {test.name}")
    if errors:
        raise SystemExit("\n".join(errors))
    print("Static release safety checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

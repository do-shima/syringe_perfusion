from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 1
STARTABLE_STATE = "ARMED"
TERMINAL_PENDING_STATES = {"CANCELLED", "STALE", "STARTED", "FAULT"}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    state: Path
    pending: Path
    run_lock: Path
    log: Path


def runtime_paths(config_dir: str | Path) -> RuntimePaths:
    root = Path(config_dir).resolve() / "runtime"
    return RuntimePaths(
        root=root,
        state=root / "perfusion_state.json",
        pending=root / "pending_run.json",
        run_lock=root / "run.lock",
        log=root / "protocol_runner.log",
    )


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else None
    except FileNotFoundError:
        return None


def read_state(config_dir: str | Path) -> dict[str, Any] | None:
    return read_json(runtime_paths(config_dir).state)


def read_pending(config_dir: str | Path) -> dict[str, Any] | None:
    return read_json(runtime_paths(config_dir).pending)


def write_state(config_dir: str | Path, state: dict[str, Any]) -> Path:
    document = {"schema_version": SCHEMA_VERSION, **state, "updated_at": now_iso()}
    path = runtime_paths(config_dir).state
    atomic_write_json(path, document)
    return path


def write_pending(config_dir: str | Path, pending: dict[str, Any]) -> Path:
    document = {"schema_version": SCHEMA_VERSION, **pending, "updated_at": now_iso()}
    path = runtime_paths(config_dir).pending
    atomic_write_json(path, document)
    return path


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def config_fingerprint(config_dir: str | Path) -> str:
    root = Path(config_dir).resolve()
    digest = hashlib.sha256()
    for filename in ("pumps.json", "profiles.json", "syringes.json", "recipes.json"):
        path = root / filename
        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def invalidate_armed(config_dir: str | Path, reason: str) -> dict[str, Any] | None:
    state = read_state(config_dir)
    if state is None:
        cancel_pending(config_dir, reason)
        return None
    if state.get("state") in {"ARMED", "PENDING", "STARTING", "DRY_RUN_PREVIEW"}:
        state["state"] = "DIRTY"
        state["invalidated_at"] = now_iso()
        state["invalidation_reason"] = reason
        write_state(config_dir, state)
    cancel_pending(config_dir, reason)
    return state


def cancel_pending(config_dir: str | Path, reason: str = "cancel requested") -> dict[str, Any]:
    pending = read_pending(config_dir)
    if pending is None:
        return {"state": "CANCELLED", "cancelled": False, "reason": reason}
    if pending.get("state") not in TERMINAL_PENDING_STATES:
        pending["state"] = "CANCELLED"
        pending["cancelled_at"] = now_iso()
        pending["reason"] = reason
        write_pending(config_dir, pending)
    return {**pending, "cancelled": True}


def new_run_id() -> str:
    return str(uuid.uuid4())


@contextmanager
def exclusive_run_lock(config_dir: str | Path, owner: str) -> Iterator[Path]:
    path = runtime_paths(config_dir).run_lock
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"owner": owner, "created_at": now_iso()}, ensure_ascii=False) + "\n"
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError("another pending or active perfusion run holds the run lock") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        yield path
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def append_protocol_log(config_dir: str | Path, event: dict[str, Any]) -> Path:
    path = runtime_paths(config_dir).log
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": now_iso(), **event}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return path

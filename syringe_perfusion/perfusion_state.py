from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
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
    command_lock: Path
    log_lock: Path
    log: Path


def runtime_paths(config_dir: str | Path) -> RuntimePaths:
    root = Path(config_dir).resolve() / "runtime"
    return RuntimePaths(
        root=root,
        state=root / "perfusion_state.json",
        pending=root / "pending_run.json",
        run_lock=root / "run.lock",
        command_lock=root / "command.lock",
        log_lock=root / "protocol.log.lock",
        log=root / "protocol_runner.log",
    )


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
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
def process_file_lock(
    path: str | Path,
    *,
    owner: str,
    run_id: str = "",
    operation: str = "transition",
    timeout_s: float = 5.0,
    poll_s: float = 0.02,
) -> Iterator[Path]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "owner": owner,
        "pid": os.getpid(),
        "created_at": now_iso(),
        "run_id": run_id,
        "operation": operation,
    }
    deadline = time.monotonic() + max(0.0, timeout_s)
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            existing = read_json(path)
            pid = int(existing.get("pid", 0)) if existing else 0
            if pid and process_exists(pid):
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        f"live process {pid} holds {operation} lock for run "
                        f"{(existing or {}).get('run_id', '')}"
                    ) from exc
                time.sleep(min(poll_s, max(0.0, deadline - time.monotonic())))
                continue
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"could not recover stale {operation} lock: {path}") from exc
                time.sleep(poll_s)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        yield path
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        if os.name == "nt":
            try:
                import ctypes

                process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
                if process:
                    ctypes.windll.kernel32.CloseHandle(process)
                    return True
                return False
            except Exception:
                return True
        return False
    return True


@contextmanager
def exclusive_run_lock(
    config_dir: str | Path,
    owner: str,
    *,
    run_id: str = "",
    operation: str = "transition",
    timeout_s: float = 5.0,
) -> Iterator[Path]:
    with process_file_lock(
        runtime_paths(config_dir).run_lock,
        owner=owner,
        run_id=run_id,
        operation=operation,
        timeout_s=timeout_s,
    ) as path:
        yield path


@contextmanager
def command_emission_lock(
    config_dir: str | Path,
    owner: str,
    *,
    run_id: str,
    timeout_s: float = 5.0,
) -> Iterator[Path]:
    with process_file_lock(
        runtime_paths(config_dir).command_lock,
        owner=owner,
        run_id=run_id,
        operation="command_emission",
        timeout_s=timeout_s,
    ) as path:
        yield path


def append_protocol_log(config_dir: str | Path, event: dict[str, Any]) -> Path:
    path = runtime_paths(config_dir).log
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": now_iso(), **event}
    try:
        with process_file_lock(
            runtime_paths(config_dir).log_lock,
            owner=f"log:{os.getpid()}",
            operation="protocol_log",
            timeout_s=2.0,
        ):
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
    except Exception:
        # Logging must never prevent safety transitions or STOP attempts.
        return path
    return path

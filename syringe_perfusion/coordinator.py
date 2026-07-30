from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Any, Callable, Iterator, Literal

from .a4 import A4Pump, pump_from_config
from .config import ConfigResolution, load_config, resolve_config, user_settings_path
from .perfusion_state import (
    append_protocol_log,
    atomic_write_json,
    command_emission_lock,
    exclusive_run_lock,
    now_iso,
    read_pending,
    read_state,
    write_pending,
    write_state,
)


ACTIVE_STATES = {
    "PROGRAMMING",
    "PENDING",
    "STARTING",
    "STARTED",
    "RECIPE_RUNNING",
    "REHEARSAL_PENDING",
    "STOPPING",
}
STARTABLE_ARMED_STATE = "ARMED"
TERMINAL_STATES = {
    "STOPPED",
    "CANCELLED",
    "FAULT",
    "STOP_FAILED",
    "DIRTY",
    "COMPLETED_ESTIMATED",
    "DRY_RUN_PREVIEW",
}
WaitResult = Literal["completed", "cancelled", "stale"]
PumpFactory = Callable[[str, dict[str, Any]], A4Pump]


def system_boot_marker() -> int:
    # time.monotonic() is system uptime on supported Windows/Python builds.
    # Rounding tolerates small cross-process wall-clock sampling differences.
    return int((time.time() - time.monotonic()) // 10)


@dataclass(frozen=True)
class RunToken:
    run_id: str
    operation_id: str
    cancellation_generation: int
    state_revision: int
    operation_type: str
    plan_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "operation_id": self.operation_id,
            "cancellation_generation": self.cancellation_generation,
            "state_revision": self.state_revision,
            "operation_type": self.operation_type,
            "plan_id": self.plan_id,
        }


def owner_metadata(operation: str, run_id: str = "") -> dict[str, Any]:
    return {
        "pid": os.getpid(),
        "operation": operation,
        "run_id": run_id,
        "claimed_at": now_iso(),
    }


def state_revision(state: dict[str, Any] | None) -> int:
    return int((state or {}).get("state_revision", 0))


def cancellation_generation(state: dict[str, Any] | None) -> int:
    return int((state or {}).get("cancellation_generation", 0))


def transition_document(
    state: dict[str, Any] | None,
    *,
    new_state: str,
    operation_id: str | None = None,
    run_id: str | None = None,
    operation_type: str | None = None,
    **updates: Any,
) -> dict[str, Any]:
    previous = dict(state or {})
    revision = state_revision(previous) + 1
    result = {
        **previous,
        "state": new_state,
        "state_revision": revision,
        "last_transition_at": now_iso(),
        **updates,
    }
    if operation_id is not None:
        result["operation_id"] = operation_id
    if run_id is not None:
        result["run_id"] = run_id
    if operation_type is not None:
        result["operation_type"] = operation_type
    return result


def targets_from_config(
    data: dict[str, Any],
    *,
    plan_id: str = "",
    run_id: str = "",
    include_disabled: bool = False,
) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for role, cfg in data.get("pumps", {}).items():
        if not include_disabled and not cfg.get("enabled", True):
            continue
        port = str(cfg.get("port", "")).strip()
        if not port:
            continue
        targets.append(
            {
                "role": role,
                "port": port,
                "baudrate": int(cfg.get("baudrate", 9600)),
                "terminator": str(cfg.get("terminator", "\\r\\n")),
                "timeout": float(cfg.get("timeout", 1.0)),
                "direction": "forward" if role == "IN" else "reverse",
                "enabled_at_snapshot": bool(cfg.get("enabled", True)),
                "required": True,
                "hardware_identity": dict(cfg.get("hardware_identity") or {}),
                "commands": dict(cfg.get("commands") or {}),
                "plan_id": plan_id,
                "run_id": run_id,
            }
        )
    return deduplicate_targets(targets)


def targets_from_plan(plan: dict[str, Any], *, run_id: str = "") -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    plan_id = str(plan.get("plan_id", ""))
    for role, cfg in (plan.get("pumps") or {}).items():
        port = str(cfg.get("port", "")).strip()
        if not port:
            continue
        targets.append(
            {
                "role": role,
                "port": port,
                "baudrate": int(cfg.get("baudrate", 9600)),
                "terminator": str(cfg.get("terminator", "\\r\\n")),
                "timeout": float(cfg.get("timeout", 1.0)),
                "direction": str(cfg.get("direction", "forward" if role == "IN" else "reverse")),
                "enabled_at_snapshot": bool(cfg.get("enabled", True)),
                "required": True,
                "hardware_identity": dict(cfg.get("hardware_identity") or {}),
                "commands": dict(cfg.get("commands") or {}),
                "plan_id": plan_id,
                "run_id": run_id,
            }
        )
    return deduplicate_targets(targets)


def deduplicate_targets(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for target in targets:
        port = str(target.get("port", "")).strip()
        identity = port.casefold()
        if not port or identity in seen:
            continue
        seen.add(identity)
        result.append(dict(target))
    return result


class OperationCoordinator:
    def __init__(
        self,
        config: str | Path | ConfigResolution,
        *,
        pump_factory: PumpFactory | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        registry_path: str | Path | None = None,
    ) -> None:
        self.resolution = config if isinstance(config, ConfigResolution) else resolve_config(config)
        self.root = self.resolution.active_config_dir
        self.pump_factory = pump_factory or (
            lambda role, target: pump_from_config(role, target, dry_run=False)
        )
        self.monotonic = monotonic
        self.registry_path = (
            Path(registry_path).resolve()
            if registry_path is not None
            else user_settings_path().with_name("safety_runtime.json")
        )

    @contextmanager
    def transition_lock(self, operation: str, run_id: str = "") -> Iterator[None]:
        with exclusive_run_lock(
            self.root,
            owner=f"{operation}:{os.getpid()}:{uuid.uuid4()}",
            run_id=run_id,
            operation=operation,
        ):
            yield

    def begin_program(
        self,
        *,
        plan_id: str,
        targets: list[dict[str, Any]],
        plan: dict[str, Any],
    ) -> RunToken:
        operation_id = str(uuid.uuid4())
        with self.transition_lock("program", operation_id):
            current = read_state(self.root)
            if current and current.get("state") in ACTIVE_STATES:
                raise RuntimeError(f"cannot program while state={current.get('state')}")
            generation = cancellation_generation(current)
            document = transition_document(
                current,
                new_state="PROGRAMMING",
                operation_id=operation_id,
                run_id="",
                operation_type="program",
                plan_id=plan_id,
                plan=plan,
                armed_targets=deduplicate_targets(targets),
                last_known_targets=deduplicate_targets(targets),
                cancellation_generation=generation,
                stop_requested=False,
                owner=owner_metadata("program"),
            )
            write_state(self.root, document)
            self._update_registry(document)
        self._log_transition(current, document)
        return self._token(document)

    def finish_arm(
        self,
        token: RunToken,
        *,
        plan: dict[str, Any],
        programming_results: dict[str, Any],
        dry_run: bool,
    ) -> dict[str, Any]:
        with self.transition_lock("finish_arm", token.operation_id):
            current = self._require_token(token, {"PROGRAMMING"})
            name = "DRY_RUN_PREVIEW" if dry_run else "ARMED"
            document = transition_document(
                current,
                new_state=name,
                operation_type="armed_plan",
                armed_at=None if dry_run else now_iso(),
                message=(
                    "DRY-RUN PREVIEW — NOT PROGRAMMED"
                    if dry_run
                    else "PROGRAMMED — NOT READ BACK"
                ),
                plan=plan,
                programming_results=programming_results,
                stop_requested=False,
                owner=owner_metadata("armed_plan"),
            )
            write_state(self.root, document)
            self._update_registry(document)
        self._log_transition(current, document)
        return document

    def reserve_start(
        self,
        *,
        operation_type: str = "armed_start",
        run_id: str | None = None,
        expected_plan_id: str | None = None,
    ) -> tuple[RunToken, dict[str, Any]]:
        actual_run_id = run_id or str(uuid.uuid4())
        operation_id = str(uuid.uuid4())
        with self.transition_lock("reserve_start", actual_run_id):
            current = read_state(self.root)
            if not current or current.get("state") != STARTABLE_ARMED_STATE:
                raise ValueError(f"perfusion plan is not startable: state={(current or {}).get('state')}")
            plan = current.get("plan")
            if not isinstance(plan, dict) or plan.get("dry_run"):
                raise ValueError("DRY_RUN_PREVIEW cannot be started")
            plan_id = str(plan.get("plan_id", current.get("plan_id", "")))
            if expected_plan_id and plan_id != expected_plan_id:
                raise ValueError("armed plan changed before start reservation")
            targets = targets_from_plan(plan, run_id=actual_run_id)
            document = transition_document(
                current,
                new_state="STARTING",
                operation_id=operation_id,
                run_id=actual_run_id,
                operation_type=operation_type,
                active_targets=targets,
                pending_targets=[],
                cancellation_generation=cancellation_generation(current),
                stop_requested=False,
                started_roles=[],
                owner=owner_metadata(operation_type, actual_run_id),
                started_at=now_iso(),
            )
            write_state(self.root, document)
            self._update_registry(document)
        self._log_transition(current, document)
        return self._token(document), document

    def reserve_pending(
        self,
        *,
        delay_s: float,
        metadata: dict[str, Any],
    ) -> tuple[RunToken, dict[str, Any]]:
        if delay_s < 0:
            raise ValueError("delay_s must be zero or positive")
        run_id = str(uuid.uuid4())
        operation_id = str(uuid.uuid4())
        with self.transition_lock("reserve_pending", run_id):
            current = read_state(self.root)
            if not current or current.get("state") != "ARMED":
                raise ValueError(f"perfusion plan is not schedulable: state={(current or {}).get('state')}")
            plan = current.get("plan")
            if not isinstance(plan, dict) or plan.get("dry_run"):
                raise ValueError("DRY_RUN_PREVIEW cannot be scheduled")
            targets = targets_from_plan(plan, run_id=run_id)
            scheduled_for = (
                datetime.now(timezone.utc).timestamp() + float(delay_s)
            )
            pending = {
                "run_id": run_id,
                "operation_id": operation_id,
                "plan_id": str(plan.get("plan_id", "")),
                "state": "PENDING",
                "created_at": now_iso(),
                "delay_s": float(delay_s),
                "scheduled_for_epoch": scheduled_for,
                "scheduled_for": datetime.fromtimestamp(
                    scheduled_for, timezone.utc
                ).astimezone().isoformat(timespec="seconds"),
                "cancellation_generation": cancellation_generation(current),
                "boot_marker": system_boot_marker(),
                **metadata,
            }
            document = transition_document(
                current,
                new_state="PENDING",
                operation_id=operation_id,
                run_id=run_id,
                operation_type="scheduled_start",
                pending=pending,
                pending_targets=targets,
                active_targets=[],
                stop_requested=False,
                owner=owner_metadata("scheduled_start", run_id),
            )
            write_pending(self.root, pending)
            write_state(self.root, document)
            self._update_registry(document)
        self._log_transition(current, document)
        return self._token(document), pending

    def claim_pending(self, token: RunToken) -> dict[str, Any]:
        with self.transition_lock("claim_pending", token.run_id):
            current = self._require_token(token, {"PENDING"})
            pending = read_pending(self.root)
            if (
                not pending
                or pending.get("run_id") != token.run_id
                or pending.get("state") != "PENDING"
                or int(pending.get("cancellation_generation", -1))
                != token.cancellation_generation
            ):
                raise ValueError("scheduled run is stale or cancelled")
            document = transition_document(
                current,
                new_state="STARTING",
                operation_type="scheduled_start",
                active_targets=list(current.get("pending_targets") or []),
                pending_targets=[],
                started_roles=[],
                owner=owner_metadata("scheduled_start", token.run_id),
                started_at=now_iso(),
            )
            write_state(self.root, document)
            self._update_registry(document)
        self._log_transition(current, document)
        return document

    def begin_recipe(
        self,
        data: dict[str, Any],
        *,
        operation_type: str = "recipe",
    ) -> RunToken:
        run_id = str(uuid.uuid4())
        operation_id = str(uuid.uuid4())
        targets = targets_from_config(data, run_id=run_id)
        with self.transition_lock("recipe", run_id):
            current = read_state(self.root)
            if current and current.get("state") in ACTIVE_STATES:
                raise RuntimeError(f"cannot run recipe while state={current.get('state')}")
            document = transition_document(
                current,
                new_state="RECIPE_RUNNING",
                operation_id=operation_id,
                run_id=run_id,
                operation_type=operation_type,
                active_targets=targets,
                last_known_targets=targets,
                cancellation_generation=cancellation_generation(current),
                stop_requested=False,
                owner=owner_metadata(operation_type, run_id),
            )
            write_state(self.root, document)
            self._update_registry(document)
        self._log_transition(current, document)
        return self._token(document)

    def begin_rehearsal(
        self,
        data: dict[str, Any],
        *,
        delay_s: float,
    ) -> RunToken:
        if delay_s < 0 or delay_s > 600:
            raise ValueError("rehearsal delay must be bounded to 0–600 seconds")
        run_id = str(uuid.uuid4())
        operation_id = str(uuid.uuid4())
        targets = targets_from_config(data, run_id=run_id)
        scheduled_epoch = datetime.now(timezone.utc).timestamp() + float(delay_s)
        with self.transition_lock("commissioning_rehearsal", run_id):
            current = read_state(self.root)
            if current and current.get("state") in ACTIVE_STATES:
                raise RuntimeError(f"cannot run rehearsal while state={current.get('state')}")
            document = transition_document(
                current,
                new_state="REHEARSAL_PENDING",
                operation_id=operation_id,
                run_id=run_id,
                operation_type="commissioning_rehearsal",
                active_targets=targets,
                last_known_targets=targets,
                cancellation_generation=cancellation_generation(current),
                stop_requested=False,
                scheduled_for_epoch=scheduled_epoch,
                scheduled_for=datetime.fromtimestamp(
                    scheduled_epoch, timezone.utc
                ).astimezone().isoformat(timespec="seconds"),
                rehearsal=True,
                start_authorization_permitted=False,
                owner=owner_metadata("commissioning_rehearsal", run_id),
            )
            write_state(self.root, document)
            self._update_registry(document)
        self._log_transition(current, document)
        return self._token(document)

    def invalidate_plan(self, reason: str) -> dict[str, Any] | None:
        with self.transition_lock("invalidate_plan"):
            current = read_state(self.root)
            if current is None:
                return None
            if current.get("state") in {
                "PROGRAMMING", "STARTING", "STARTED", "RECIPE_RUNNING",
                "REHEARSAL_PENDING", "STOPPING",
            }:
                raise RuntimeError(
                    f"cannot change calibration while state={current.get('state')}"
                )
            if current.get("state") in {"ARMED", "PENDING", "DRY_RUN_PREVIEW"}:
                document = transition_document(
                    current,
                    new_state="DIRTY",
                    cancellation_generation=cancellation_generation(current) + 1,
                    stop_requested=True,
                    invalidated_at=now_iso(),
                    invalidation_reason=reason,
                    active_targets=[],
                    pending_targets=[],
                )
                write_state(self.root, document)
                pending = read_pending(self.root)
                if pending and pending.get("state") == "PENDING":
                    write_pending(
                        self.root,
                        {
                            **pending,
                            "state": "CANCELLED",
                            "cancelled_at": now_iso(),
                            "reason": reason,
                        },
                    )
                self._update_registry(document)
            else:
                document = current
        if document is not current:
            self._log_transition(current, document)
        return document

    @contextmanager
    def config_change_guard(self, reason: str) -> Iterator[None]:
        """Serialize a short atomic config update with runtime invalidation."""
        with self.transition_lock("config_change"):
            current = read_state(self.root)
            if current and current.get("state") in {
                "PROGRAMMING", "STARTING", "STARTED", "RECIPE_RUNNING",
                "REHEARSAL_PENDING", "STOPPING",
            }:
                raise RuntimeError(
                    f"cannot change calibration while state={current.get('state')}"
                )
            yield
            latest = read_state(self.root)
            if latest and latest.get("state") in {"ARMED", "PENDING", "DRY_RUN_PREVIEW"}:
                document = transition_document(
                    latest,
                    new_state="DIRTY",
                    cancellation_generation=cancellation_generation(latest) + 1,
                    stop_requested=True,
                    invalidated_at=now_iso(),
                    invalidation_reason=reason,
                    active_targets=[],
                    pending_targets=[],
                )
                write_state(self.root, document)
                pending = read_pending(self.root)
                if pending and pending.get("state") == "PENDING":
                    write_pending(
                        self.root,
                        {
                            **pending,
                            "state": "CANCELLED",
                            "cancelled_at": now_iso(),
                            "reason": reason,
                        },
                    )
                self._update_registry(document)
            else:
                document = latest
        if latest and document and document is not latest:
            self._log_transition(latest, document)

    @contextmanager
    def start_command_guard(self, token: RunToken, role: str) -> Iterator[None]:
        with command_emission_lock(
            self.root,
            owner=f"start:{role}:{os.getpid()}",
            run_id=token.run_id,
        ):
            with self.transition_lock("authorize_start", token.run_id):
                current = self._require_token(token, {"STARTING", "RECIPE_RUNNING"})
                if current.get("stop_requested"):
                    raise RuntimeError("start cancelled before command emission")
                if current.get("state") == "STARTING":
                    roles = list(current.get("started_roles") or [])
                    if role in roles:
                        raise RuntimeError(f"duplicate {role} START rejected")
                    current = transition_document(
                        current,
                        new_state="STARTING",
                        start_inflight_role=role,
                    )
                    write_state(self.root, current)
            try:
                yield
            except BaseException:
                with self.transition_lock("start_command_failed", token.run_id):
                    latest = read_state(self.root)
                    if latest and latest.get("run_id") == token.run_id:
                        latest = transition_document(
                            latest,
                            new_state=str(latest.get("state", "STARTING")),
                            start_inflight_role=None,
                        )
                        write_state(self.root, latest)
                raise
            else:
                with self.transition_lock("start_command_emitted", token.run_id):
                    latest = self._require_token(token, {"STARTING", "RECIPE_RUNNING"})
                    if latest.get("state") == "STARTING":
                        roles = list(latest.get("started_roles") or [])
                        if role not in roles:
                            roles.append(role)
                        latest = transition_document(
                            latest,
                            new_state="STARTING",
                            started_roles=roles,
                            start_inflight_role=None,
                            last_start_command_at=now_iso(),
                        )
                        write_state(self.root, latest)

    def emit_start(self, token: RunToken, role: str, pump: Any, direction: str) -> dict[str, Any]:
        method_name = "start_reverse" if direction == "reverse" else "start_forward"
        guarded_name = method_name + "_guarded"
        guarded = getattr(pump, guarded_name, None)
        if callable(guarded):
            return guarded(lambda: self.start_command_guard(token, role))
        with self.start_command_guard(token, role):
            return getattr(pump, method_name)()

    def emit_manual(
        self,
        token: RunToken,
        role: str,
        pump: Any,
        direction: str,
    ) -> dict[str, Any]:
        method_name = "manual_reverse" if direction == "reverse" else "manual_forward"
        guarded = getattr(pump, method_name + "_guarded", None)
        if callable(guarded):
            return guarded(lambda: self.start_command_guard(token, role))
        with self.start_command_guard(token, role):
            return getattr(pump, method_name)()

    def wait(
        self,
        token: RunToken,
        seconds: float,
        *,
        allowed_states: set[str],
        event: Event | None = None,
        poll_s: float = 0.05,
        before_final_check: Callable[[], None] | None = None,
    ) -> WaitResult:
        if seconds < 0:
            raise ValueError("wait duration must be zero or positive")
        waiter = event or Event()
        deadline = self.monotonic() + seconds
        while True:
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                break
            if waiter.wait(min(poll_s, remaining)):
                return "cancelled"
            status = self.token_status(token, allowed_states)
            if status != "valid":
                return "cancelled" if status == "cancelled" else "stale"
        if before_final_check is not None:
            before_final_check()
        status = self.token_status(token, allowed_states)
        if status == "valid":
            return "completed"
        return "cancelled" if status == "cancelled" else "stale"

    def token_status(self, token: RunToken, allowed_states: set[str]) -> str:
        current = read_state(self.root)
        if not current or current.get("run_id") != token.run_id:
            return "stale"
        if current.get("operation_id") != token.operation_id:
            return "stale"
        if state_revision(current) < token.state_revision:
            return "stale"
        if (
            current.get("stop_requested")
            or cancellation_generation(current) != token.cancellation_generation
            or current.get("state") in {"STOPPING", "STOPPED", "CANCELLED", "FAULT", "STOP_FAILED"}
        ):
            return "cancelled"
        if current.get("state") not in allowed_states:
            return "stale"
        return "valid"

    def mark_started(
        self,
        token: RunToken,
        *,
        duration_s: int,
        results: dict[str, Any],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        with self.transition_lock("mark_started", token.run_id):
            current = self._require_token(token, {"STARTING"})
            roles = set(current.get("started_roles") or [])
            if not {"IN", "OUT"} <= roles:
                raise RuntimeError("cannot mark STARTED before both START commands")
            expected_epoch = datetime.now(timezone.utc).timestamp() + int(duration_s)
            expected_end = datetime.fromtimestamp(
                expected_epoch, timezone.utc
            ).astimezone().isoformat(timespec="seconds")
            document = transition_document(
                current,
                new_state="STARTED",
                actual_started_at=now_iso(),
                expected_end=expected_end,
                expected_end_epoch=expected_epoch,
                start_results=results,
                **metadata,
            )
            write_state(self.root, document)
            self._update_registry(document)
            pending = read_pending(self.root)
            if pending and pending.get("run_id") == token.run_id:
                write_pending(
                    self.root,
                    {**pending, "state": "STARTED", "started_at": now_iso()},
                )
        self._log_transition(current, document)
        return document

    def finish_recipe(self, token: RunToken) -> dict[str, Any]:
        with self.transition_lock("finish_recipe", token.run_id):
            current = self._require_token(token, {"RECIPE_RUNNING"})
            document = transition_document(
                current,
                new_state="COMPLETED_ESTIMATED",
                completion_basis="recipe blocks completed; no hardware readback",
                completed_at=now_iso(),
                active_targets=[],
            )
            write_state(self.root, document)
            self._update_registry(document)
        self._log_transition(current, document)
        return document

    def mark_fault(
        self,
        token: RunToken | None,
        *,
        operation: str,
        error: str,
        stop_results: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        run_id = token.run_id if token else ""
        with self.transition_lock("fault", run_id):
            current = read_state(self.root) or {}
            if token and current.get("run_id") not in {"", token.run_id}:
                return current
            document = transition_document(
                current,
                new_state="FAULT",
                fault={"operation": operation, "error": error, "at": now_iso()},
                stop_results=stop_results if stop_results is not None else current.get("stop_results", []),
                stop_requested=True,
                active_targets=[],
            )
            write_state(self.root, document)
            self._update_registry(document)
        self._log_transition(current, document)
        return document

    def rollback_pending(self, token: RunToken, error: str) -> dict[str, Any]:
        with self.transition_lock("rollback_pending", token.run_id):
            current = read_state(self.root) or {}
            if current.get("run_id") != token.run_id or current.get("state") != "PENDING":
                return current
            document = transition_document(
                current,
                new_state="FAULT",
                fault={"operation": "schedule_spawn", "error": error, "at": now_iso()},
                stop_requested=True,
                pending_targets=[],
            )
            write_pending(
                self.root,
                {
                    "run_id": token.run_id,
                    "operation_id": token.operation_id,
                    "state": "FAULT",
                    "error": error,
                },
            )
            write_state(self.root, document)
        self._log_transition(current, document)
        return document

    def emergency_stop(
        self,
        *,
        dry_run: bool = False,
        metadata: dict[str, Any] | None = None,
        fallback_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        stop_id = str(uuid.uuid4())
        with command_emission_lock(
            self.root,
            owner=f"stop:{os.getpid()}",
            run_id=stop_id,
        ):
            with self.transition_lock("accept_stop", stop_id):
                current = read_state(self.root) or {}
                targets = self.stop_targets(current, fallback_data=fallback_data)
                generation = cancellation_generation(current) + 1
                document = transition_document(
                    current,
                    new_state="STOPPING",
                    operation_type="stop_all",
                    stop_operation_id=stop_id,
                    cancellation_generation=generation,
                    stop_requested=True,
                    stop_requested_at=now_iso(),
                    owner=owner_metadata("stop_all", str(current.get("run_id", ""))),
                )
                write_state(self.root, document)
                pending = read_pending(self.root)
                if pending and pending.get("state") == "PENDING":
                    write_pending(
                        self.root,
                        {
                            **pending,
                            "state": "CANCELLED",
                            "cancelled_at": now_iso(),
                            "reason": "STOP ALL",
                        },
                    )
        append_protocol_log(
            self.root,
            {"event": "stop_accepted", "stop_operation_id": stop_id, "targets": targets},
        )
        results = self._stop_targets(targets, dry_run=dry_run)
        failures = [item for item in results if not item.get("ok")]
        with self.transition_lock("finish_stop", stop_id):
            latest = read_state(self.root) or document
            final = transition_document(
                latest,
                new_state="STOP_FAILED" if failures else "STOPPED",
                stopped_at=now_iso(),
                stop_results=results,
                active_targets=[],
                pending_targets=[],
                fault=(
                    {
                        "operation": "stop_all",
                        "error": "one or more STOP commands failed",
                        "at": now_iso(),
                    }
                    if failures
                    else latest.get("fault")
                ),
                **(metadata or {}),
            )
            write_state(self.root, final)
            self._update_registry(final)
        append_protocol_log(
            self.root,
            {"event": "stop_all", "state": final["state"], "results": results},
        )
        return final

    def stop_targets(
        self,
        state: dict[str, Any],
        *,
        fallback_data: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        for key in ("active_targets", "pending_targets", "armed_targets", "last_known_targets"):
            values = state.get(key)
            if isinstance(values, list) and values:
                primary = deduplicate_targets([dict(item) for item in values if isinstance(item, dict)])
                if primary:
                    return primary
        plan = state.get("plan")
        if isinstance(plan, dict):
            planned = targets_from_plan(plan, run_id=str(state.get("run_id", "")))
            if planned:
                return planned
        data = fallback_data
        if data is None:
            try:
                data = load_config(self.resolution)
            except Exception:
                data = None
        return targets_from_config(data or {}, include_disabled=True)

    def _stop_targets(self, targets: list[dict[str, Any]], *, dry_run: bool) -> list[dict[str, Any]]:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def stop_one(target: dict[str, Any]) -> dict[str, Any]:
            role = str(target.get("role", "UNKNOWN"))
            try:
                pump = (
                    pump_from_config(role, target, dry_run=True)
                    if dry_run
                    else self.pump_factory(role, target)
                )
                result = pump.stop()
                return {
                    "pump": role,
                    "port": target.get("port", ""),
                    "ok": True,
                    "result": result,
                }
            except Exception as exc:
                return {
                    "pump": role,
                    "port": target.get("port", ""),
                    "ok": False,
                    "error": str(exc),
                }

        if not targets:
            return []
        results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(
            max_workers=len(targets), thread_name_prefix="a4-emergency-stop"
        ) as executor:
            futures = [executor.submit(stop_one, target) for target in targets]
            for future in as_completed(futures):
                results.append(future.result())
        return sorted(results, key=lambda item: (str(item["pump"]), str(item["port"])))

    def reconcile_completion(
        self,
        *,
        now_epoch: float | None = None,
    ) -> dict[str, Any] | None:
        with self.transition_lock("reconcile_completion"):
            current = read_state(self.root)
            if not current or current.get("state") != "STARTED":
                return current
            expected = current.get("expected_end_epoch")
            if expected is None:
                try:
                    expected = datetime.fromisoformat(
                        str(current.get("expected_end"))
                    ).timestamp()
                except (TypeError, ValueError):
                    return current
            now_value = datetime.now(timezone.utc).timestamp() if now_epoch is None else now_epoch
            if now_value < float(expected):
                return current
            document = transition_document(
                current,
                new_state="COMPLETED_ESTIMATED",
                completed_at=now_iso(),
                completion_basis="programmed duration elapsed; no hardware readback",
                active_targets=[],
            )
            write_state(self.root, document)
            self._update_registry(document)
        self._log_transition(current, document)
        return document

    def _require_token(
        self,
        token: RunToken,
        allowed_states: set[str],
    ) -> dict[str, Any]:
        current = read_state(self.root)
        if not current:
            raise ValueError("runtime state is missing")
        if current.get("run_id") != token.run_id:
            raise ValueError("stale run ID")
        if current.get("operation_id") != token.operation_id:
            raise ValueError("stale operation ID")
        if cancellation_generation(current) != token.cancellation_generation:
            raise ValueError("operation was cancelled")
        if current.get("stop_requested"):
            raise ValueError("operation was stopped")
        if current.get("state") not in allowed_states:
            raise ValueError(f"operation state is not valid: {current.get('state')}")
        return current

    @staticmethod
    def _token(state: dict[str, Any]) -> RunToken:
        return RunToken(
            run_id=str(state.get("run_id", "")),
            operation_id=str(state.get("operation_id", "")),
            cancellation_generation=cancellation_generation(state),
            state_revision=state_revision(state),
            operation_type=str(state.get("operation_type", "")),
            plan_id=str(state.get("plan_id", "")),
        )

    def _log_transition(
        self,
        previous: dict[str, Any] | None,
        current: dict[str, Any],
    ) -> None:
        append_protocol_log(
            self.root,
            {
                "event": "state_transition",
                "from": (previous or {}).get("state", "MISSING"),
                "to": current.get("state"),
                "state_revision": current.get("state_revision"),
                "run_id": current.get("run_id", ""),
                "operation_id": current.get("operation_id", ""),
            },
        )

    def registered_active_root(self) -> Path | None:
        local_state = read_state(self.root)
        if local_state and local_state.get("state") in ACTIVE_STATES | {"ARMED"}:
            return None
        try:
            with self.registry_path.open("r", encoding="utf-8") as handle:
                registry = json.load(handle)
            root = Path(str(registry.get("active_config_dir", ""))).resolve()
            if not str(registry.get("active_config_dir", "")).strip() or root == self.root:
                return None
            state = read_state(root)
            if state and state.get("state") in ACTIVE_STATES | {"ARMED"}:
                return root
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            return None
        return None

    def _update_registry(self, state: dict[str, Any]) -> None:
        try:
            atomic_write_json(
                self.registry_path,
                {
                    "active_config_dir": str(self.root),
                    "state": state.get("state"),
                    "run_id": state.get("run_id", ""),
                    "operation_id": state.get("operation_id", ""),
                    "state_revision": state.get("state_revision", 0),
                    "updated_at": now_iso(),
                },
            )
        except Exception:
            # The per-config runtime state remains authoritative. Registry
            # failure must not bypass local safety transitions.
            pass


def token_from_state(state: dict[str, Any]) -> RunToken:
    return OperationCoordinator._token(state)

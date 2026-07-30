from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .app_info import get_build_info
from .config import load_config, resolve_config
from .coordinator import OperationCoordinator
from .diagnostics import diagnostics_summary, export_diagnostics, format_diagnostics_summary
from .operations import (
    call_action,
    cancel_pending,
    ensure_pump_enabled,
    get_arm_status,
    jog_pump,
    make_pump,
    profile_log_info,
    pushpull,
    run_profile,
    send_action,
    start_armed_pair,
    stop_all,
    stop_all_safe,
    write_profile,
    write_settings,
)
from .port_scan import scan_serial_ports
from .preflight import assess_preflight, format_preflight
from .profiles import calculate, result_to_dict, ul_per_mm_from_inner_diameter
from .protocol_runner import run_scheduled, schedule_armed
from .recipe_engine import RecipeEngine
from .recipe_model import validate_recipe
from .recipe_store import list_recipes, load_recipe
from .run_history import recent_runs
from .validation_store import ValidationStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="a4ctl", description="A4 syringe pump control CLI")
    parser.add_argument(
        "--version",
        action="version",
        version=_cli_version_text(),
    )
    parser.add_argument("--config-dir", default=None, help="Path to the shared Active Config directory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    config_path = subparsers.add_parser("config-path", help="Show the shared Active Config directory")
    config_path.add_argument("--json", action="store_true")

    arm_status = subparsers.add_parser("arm-status", help="Inspect the shared armed perfusion state")
    arm_status.add_argument("--json", action="store_true")

    preflight = subparsers.add_parser("preflight", help="Read-only production readiness assessment")
    preflight.add_argument("--json", action="store_true")
    preflight.add_argument("--require-commissioned", action="store_true")

    validation_status = subparsers.add_parser(
        "validation-status", help="Inspect commissioning status without moving pumps"
    )
    validation_status.add_argument("--json", action="store_true")

    export_validation = subparsers.add_parser(
        "export-validation", help="Export the current commissioning report"
    )
    export_validation.add_argument("--format", choices=["json", "csv", "markdown"], required=True)
    export_validation.add_argument("--output", required=True)

    history = subparsers.add_parser("recent-runs", help="Show normalized recent run history")
    history.add_argument("--limit", type=int, default=20)
    history.add_argument("--dish-id", default="")
    history.add_argument("--condition", default="")
    history.add_argument("--json", action="store_true")

    diagnostics = subparsers.add_parser(
        "diagnostics-summary",
        help="Read-only build, config, preflight, and runtime summary",
    )
    diagnostics.add_argument("--json", action="store_true")

    export_diagnostics_parser = subparsers.add_parser(
        "export-diagnostics",
        help="Export a sanitized read-only diagnostic ZIP",
    )
    export_diagnostics_parser.add_argument("--output", required=True)

    start_armed = subparsers.add_parser("start-armed", help="Start the persisted ARMED plan without reprogramming")
    add_run_metadata_args(start_armed)

    schedule = subparsers.add_parser("schedule-armed", help="Schedule a detached start of the persisted ARMED plan")
    schedule.add_argument("--delay-s", type=float, required=True)
    add_run_metadata_args(schedule)

    subparsers.add_parser("cancel-pending", help="Cancel a pending scheduled start")
    internal = subparsers.add_parser("run-scheduled", help=argparse.SUPPRESS)
    internal.add_argument("--run-id", required=True)

    subparsers.add_parser("list-ports", help="List available serial ports")
    recipes = subparsers.add_parser("list-recipes", help="List V2 JSON recipes")
    recipes.add_argument("--recipe-dir", default=None)

    send = subparsers.add_parser("send", help="Send a start/stop command to one pump")
    send.add_argument("--pump", required=True)
    send.add_argument(
        "--action",
        required=True,
        choices=["manual-forward", "manual-reverse", "save", "start-forward", "start-reverse", "stop"],
    )
    add_run_metadata_args(send)
    send.add_argument("--dry-run", action="store_true")

    jog = subparsers.add_parser("jog", help="Run a bounded manual jog")
    jog.add_argument("--pump", required=True, choices=["IN", "OUT"])
    jog.add_argument("--direction", required=True, choices=["forward", "reverse"])
    jog.add_argument("--duration-ms", type=int, default=1000)
    add_run_metadata_args(jog)
    jog.add_argument("--dry-run", action="store_true")

    write = subparsers.add_parser("write-settings", help="Write speed/time settings to one pump")
    write.add_argument("--pump", required=True, choices=["IN", "OUT"])
    write.add_argument("--speed-mm-min", type=float, required=True)
    write.add_argument("--duration-s", type=float, required=True)
    write.add_argument("--save", action=argparse.BooleanOptionalAction, default=True)
    add_run_metadata_args(write)
    write.add_argument("--dry-run", action="store_true")

    write_profile_parser = subparsers.add_parser("write-profile", help="Write a legacy saved profile")
    write_profile_parser.add_argument("--pump", required=True, choices=["IN", "OUT"])
    write_profile_parser.add_argument("--profile", required=True)
    write_profile_parser.add_argument("--save", action=argparse.BooleanOptionalAction, default=True)
    write_profile_parser.add_argument("--start-after-write", action="store_true")
    add_run_metadata_args(write_profile_parser)
    write_profile_parser.add_argument("--dry-run", action="store_true")

    run_profile_parser = subparsers.add_parser("run-profile", help="Start a legacy saved profile")
    run_profile_parser.add_argument("--pump", required=True)
    run_profile_parser.add_argument("--profile", required=True)
    add_run_metadata_args(run_profile_parser)
    run_profile_parser.add_argument("--dry-run", action="store_true")

    pair = subparsers.add_parser("pushpull", help="Run legacy profile-based push-pull")
    pair.add_argument("--in-pump", default="IN")
    pair.add_argument("--out-pump", default="OUT")
    pair.add_argument("--profile-in", required=True)
    pair.add_argument("--profile-out", required=True)
    pair.add_argument("--out-delay", type=float, default=0.5)
    pair.add_argument("--safety-stop-after", type=float, default=None)
    add_run_metadata_args(pair)
    pair.add_argument("--dry-run", action="store_true")

    stop = subparsers.add_parser("stop-all", help="Cancel pending starts and stop all enabled pumps")
    add_run_metadata_args(stop)
    stop.add_argument("--dry-run", action="store_true")

    calc = subparsers.add_parser("calc", help="Calculate pump speed/time/volume")
    calc.add_argument("--syringe", required=True)
    calc.add_argument("--mode", choices=["volume_duration", "volume_flow", "speed_duration"], default="volume_duration")
    calc.add_argument("--volume-ul", type=float)
    calc.add_argument("--duration-s", type=float)
    calc.add_argument("--flow-ml-min", type=float)
    calc.add_argument("--speed-mm-min", type=float)

    validate = subparsers.add_parser("validate-recipe", help="Validate a V2 recipe JSON file")
    validate.add_argument("--recipe", required=True)
    run_recipe = subparsers.add_parser("run-recipe", help="Execute a V2 recipe JSON file")
    run_recipe.add_argument("--recipe", required=True)
    add_run_metadata_args(run_recipe)
    run_recipe.add_argument("--dry-run", action="store_true")
    run_recipe.add_argument("--assume-yes", action="store_true")
    return parser


def add_run_metadata_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dish-id", default="")
    parser.add_argument("--condition", default="")
    parser.add_argument("--trigger-source", default="CLI")


def _cli_version_text() -> str:
    info = get_build_info()
    return (
        f"{info.get('application_name', 'A4PumpControl')} "
        f"{info.get('human_version', '')}; "
        f"package {info.get('package_version', '')}; "
        f"commit {info.get('git_commit_short') or 'unknown'}; "
        f"{'dirty' if info.get('git_dirty') is True else 'clean' if info.get('git_dirty') is False else 'cleanliness unknown'}; "
        f"build type {info.get('build_type', '')}; "
        f"control compatibility {info.get('control_compatibility_version', '')}; "
        f"Python {info.get('python_version', '')}; "
        f"build fingerprint {info.get('build_identity_fingerprint', '')}"
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return dispatch(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def dispatch(args: argparse.Namespace) -> int:
    resolution = resolve_config(args.config_dir)
    if args.command == "config-path":
        if args.json:
            print(json.dumps(resolution.to_dict(), ensure_ascii=True, indent=2))
        else:
            print(f"Active config directory: {resolution.active_config_dir}")
            print(f"pumps.json: {resolution.active_pumps_json}")
            print(f"source: {resolution.source}")
            print(f"writable: {str(resolution.writable).lower()}")
            print(f"required files present: {str(resolution.required_files_present).lower()}")
            if resolution.missing_files:
                print(f"missing files: {', '.join(resolution.missing_files)}")
        return 0

    if args.command == "arm-status":
        status = get_arm_status(resolution)
        if args.json:
            print(json.dumps(status, ensure_ascii=True, indent=2))
        else:
            print(_format_arm_status(status))
        return 0

    if args.command == "preflight":
        try:
            detected_ports = scan_serial_ports()
        except Exception:
            detected_ports = []
        result = assess_preflight(
            resolution,
            require_commissioned=args.require_commissioned,
            detected_ports=detected_ports,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=True, indent=2))
        else:
            _print_console_safe(format_preflight(result))
        return 0 if result["ready"] else 2

    if args.command == "validation-status":
        status = ValidationStore(resolution).status()
        public = {key: value for key, value in status.items() if key != "record"}
        if args.json:
            print(json.dumps(public, ensure_ascii=True, indent=2))
        else:
            _print_console_safe(f"status: {public['status']}")
            print(f"validation ID: {public['validation_id']}")
            print(f"last completed: {public['last_completed_at']}")
            print(f"current: {str(public['current']).lower()}")
            print(f"commissioned: {str(public['commissioned']).lower()}")
            for reason in public["stale_reasons"]:
                print(f"STALE: {reason}")
        return 0

    if args.command == "export-validation":
        path = ValidationStore(resolution).export(args.format, args.output)
        print(path)
        return 0

    if args.command == "recent-runs":
        runs = recent_runs(
            resolution,
            limit=args.limit,
            dish_id=args.dish_id,
            condition=args.condition,
        )
        if args.json:
            print(json.dumps(runs, ensure_ascii=True, indent=2))
        else:
            for item in runs:
                print(
                    "\t".join(
                        str(item[key])
                        for key in (
                            "timestamp",
                            "dish_id",
                            "condition",
                            "plan_id",
                            "run_id",
                            "terminal_state",
                            "stop_or_fault",
                        )
                    )
                )
        return 0

    if args.command == "diagnostics-summary":
        summary = diagnostics_summary(resolution)
        if args.json:
            print(json.dumps(summary, ensure_ascii=True, indent=2))
        else:
            _print_console_safe(format_diagnostics_summary(summary))
        return 0

    if args.command == "export-diagnostics":
        print(export_diagnostics(resolution, args.output))
        return 0

    if args.command == "start-armed":
        result = start_armed_pair(
            resolution,
            dish_id=args.dish_id,
            condition=args.condition,
            trigger_source=args.trigger_source,
        )
        print(json.dumps(result, ensure_ascii=True))
        return 0

    if args.command == "schedule-armed":
        result = schedule_armed(
            resolution,
            delay_s=args.delay_s,
            dish_id=args.dish_id,
            condition=args.condition,
            trigger_source=args.trigger_source,
            scanner=scan_serial_ports,
        )
        print(result["run_id"])
        return 0

    if args.command == "cancel-pending":
        print(json.dumps(cancel_pending(resolution), ensure_ascii=True))
        return 0

    if args.command == "run-scheduled":
        result = run_scheduled(resolution, args.run_id, scanner=scan_serial_ports)
        print(json.dumps(result, ensure_ascii=True))
        return 0

    if args.command == "list-ports":
        for port in scan_serial_ports():
            print(f"{port['device']}\t{port['description']}\t{port['hwid']}")
        return 0
    if args.command == "list-recipes":
        for path in list_recipes(args.recipe_dir):
            try:
                recipe = load_recipe(path)
                print(f"{path}\t{recipe.recipe_id}\t{recipe.display_name}")
            except Exception as exc:
                print(f"{path}\tINVALID\t{exc}")
        return 0

    data = load_config(resolution)
    metadata = {
        "dish_id": getattr(args, "dish_id", ""),
        "condition": getattr(args, "condition", ""),
        "trigger_source": getattr(args, "trigger_source", "CLI"),
    }
    if args.command == "send":
        if not args.dry_run and args.action in {
            "start-forward",
            "start-reverse",
            "manual-forward",
            "manual-reverse",
        }:
            coordinator = OperationCoordinator(resolution)
            token = coordinator.begin_recipe(data, operation_type="cli_manual")
            pump = coordinator.pump_factory(args.pump, data["pumps"][args.pump])
            if args.action.startswith("manual-"):
                result = coordinator.emit_manual(
                    token,
                    args.pump,
                    pump,
                    "reverse" if args.action.endswith("reverse") else "forward",
                )
            else:
                result = coordinator.emit_start(
                    token,
                    args.pump,
                    pump,
                    "reverse" if args.action.endswith("reverse") else "forward",
                )
        else:
            result = send_action(
                data, args.pump, args.action, dry_run=args.dry_run, **metadata
            )
        print(json.dumps(result, ensure_ascii=True))
    elif args.command == "jog":
        if args.dry_run:
            jog_results = jog_pump(
                data,
                args.pump,
                args.direction,
                args.duration_ms,
                dry_run=True,
                **metadata,
            )
        else:
            coordinator = OperationCoordinator(resolution)
            token = coordinator.begin_recipe(data, operation_type="cli_jog")
            pump = coordinator.pump_factory(args.pump, data["pumps"][args.pump])
            start_result = coordinator.emit_manual(
                token, args.pump, pump, args.direction
            )
            coordinator.wait(
                token,
                args.duration_ms / 1000.0,
                allowed_states={"RECIPE_RUNNING"},
            )
            stopped = coordinator.emergency_stop(
                metadata={**metadata, "reason": "jog complete"},
                fallback_data=data,
            )
            jog_results = [start_result, *list(stopped.get("stop_results") or [])]
        print(json.dumps(jog_results, ensure_ascii=True))
    elif args.command == "write-settings":
        print(json.dumps(write_settings(data, args.pump, args.speed_mm_min, args.duration_s, save=args.save, dry_run=args.dry_run, **metadata), ensure_ascii=True))
    elif args.command == "write-profile":
        print(json.dumps(write_profile(data, args.pump, args.profile, save=args.save, start_after_write=args.start_after_write, dry_run=args.dry_run, **metadata), ensure_ascii=True))
    elif args.command == "run-profile":
        print(json.dumps(run_profile(
            data,
            args.pump,
            args.profile,
            dry_run=args.dry_run,
            coordinator=None if args.dry_run else OperationCoordinator(resolution),
            **metadata,
        ), ensure_ascii=True))
    elif args.command == "pushpull":
        print(json.dumps(pushpull(
            data, in_pump=args.in_pump, out_pump=args.out_pump, profile_in=args.profile_in,
            profile_out=args.profile_out, out_delay=args.out_delay, safety_stop_after=args.safety_stop_after,
            dry_run=args.dry_run, **metadata,
        ), ensure_ascii=True))
    elif args.command == "stop-all":
        print(json.dumps(stop_all_safe(resolution, dry_run=args.dry_run, **metadata), ensure_ascii=True))
    elif args.command == "calc":
        syringe = data["syringes"][args.syringe]
        ul_per_mm = syringe.get("calibrated_ul_per_mm")
        if ul_per_mm is None:
            ul_per_mm = ul_per_mm_from_inner_diameter(syringe["nominal_inner_diameter_mm"])
        result = calculate(
            args.mode, float(ul_per_mm), volume_ul=args.volume_ul, duration_s=args.duration_s,
            flow_ml_min=args.flow_ml_min, speed_mm_min=args.speed_mm_min, syringe_key=args.syringe,
        )
        print(json.dumps(result_to_dict(result), indent=2, ensure_ascii=True))
    elif args.command == "validate-recipe":
        recipe = load_recipe(args.recipe)
        validate_recipe(recipe, data)
        print(f"OK: {recipe.recipe_id} ({len(recipe.blocks)} blocks)")
    elif args.command == "run-recipe":
        recipe = load_recipe(args.recipe)
        validate_recipe(recipe, data)
        events = RecipeEngine(data, resolution).execute(
            recipe,
            dry_run=args.dry_run,
            context={**metadata, "assume_yes": args.assume_yes},
        )
        print(json.dumps(events, ensure_ascii=True))
    else:
        raise ValueError(f"unsupported command: {args.command}")
    return 0


def _format_arm_status(status: dict[str, Any]) -> str:
    plan = status.get("plan") if isinstance(status.get("plan"), dict) else {}
    pumps = plan.get("pumps") if isinstance(plan.get("pumps"), dict) else {}
    lines = [
        f"state: {status.get('state', 'MISSING')}",
        f"plan ID: {status.get('plan_id', '')}",
        f"armed at: {status.get('armed_at', '')}",
        f"IN port: {pumps.get('IN', {}).get('port', '')}",
        f"OUT port: {pumps.get('OUT', {}).get('port', '')}",
        f"IN requested flow: {pumps.get('IN', {}).get('requested_flow_ml_min', '')}",
        f"OUT requested flow: {pumps.get('OUT', {}).get('requested_flow_ml_min', '')}",
        f"IN programmed speed: {pumps.get('IN', {}).get('programmed_speed_mm_min', '')}",
        f"OUT programmed speed: {pumps.get('OUT', {}).get('programmed_speed_mm_min', '')}",
        f"programmed duration: {plan.get('programmed_duration_s', '')}",
        f"expected end: {status.get('expected_end', '')}",
        f"pending run ID: {(status.get('pending') or {}).get('run_id', '')}",
    ]
    if status.get("fault"):
        lines.append(f"fault: {status['fault']}")
    return "\n".join(lines)


def _print_console_safe(value: str) -> None:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(value.encode(encoding, errors="replace").decode(encoding, errors="replace"))


if __name__ == "__main__":
    raise SystemExit(main())

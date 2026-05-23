from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

from .a4 import A4Pump, list_serial_ports, pump_from_config
from .config import load_config
from .logger import log_command
from .profiles import calculate, calculate_profile, result_to_dict, ul_per_mm_from_inner_diameter


ACTION_METHODS = {
    "start-forward": "start_forward",
    "start-reverse": "start_reverse",
    "stop": "stop",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="a4ctl", description="A4 syringe pump control CLI")
    parser.add_argument("--config-dir", default=None, help="Path to config directory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-ports", help="List available serial ports")

    send = subparsers.add_parser("send", help="Send a start/stop command to one pump")
    send.add_argument("--pump", required=True, help="Pump key, e.g. IN or OUT")
    send.add_argument("--action", required=True, choices=sorted(ACTION_METHODS))
    add_run_metadata_args(send)
    send.add_argument("--dry-run", action="store_true")

    run_profile = subparsers.add_parser("run-profile", help="Start a saved A4 condition and log profile metadata")
    run_profile.add_argument("--pump", required=True)
    run_profile.add_argument("--profile", required=True)
    add_run_metadata_args(run_profile)
    run_profile.add_argument("--dry-run", action="store_true")

    pushpull = subparsers.add_parser("pushpull", help="Run IN forward and OUT reverse with an optional delay")
    pushpull.add_argument("--in-pump", default="IN")
    pushpull.add_argument("--out-pump", default="OUT")
    pushpull.add_argument("--profile-in", required=True)
    pushpull.add_argument("--profile-out", required=True)
    pushpull.add_argument("--out-delay", type=float, default=0.5)
    pushpull.add_argument("--safety-stop-after", type=float, default=None)
    add_run_metadata_args(pushpull)
    pushpull.add_argument("--dry-run", action="store_true")

    stop_all_parser = subparsers.add_parser("stop-all", help="Immediately stop all configured pumps")
    add_run_metadata_args(stop_all_parser)
    stop_all_parser.add_argument("--dry-run", action="store_true")

    calc = subparsers.add_parser("calc", help="Calculate pump speed/time/volume")
    calc.add_argument("--syringe", required=True)
    calc.add_argument("--mode", choices=["volume_duration", "volume_flow", "speed_duration"], default="volume_duration")
    calc.add_argument("--volume-ul", type=float, default=None)
    calc.add_argument("--duration-s", type=float, default=None)
    calc.add_argument("--flow-ml-min", type=float, default=None)
    calc.add_argument("--speed-mm-min", type=float, default=None)

    return parser


def add_run_metadata_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dish-id", default="")
    parser.add_argument("--condition", default="")
    parser.add_argument("--trigger-source", default="CLI")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return dispatch(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "list-ports":
        for port in list_serial_ports():
            print(f"{port['device']}\t{port['description']}\t{port['hwid']}")
        return 0

    data = load_config(args.config_dir)

    if args.command == "send":
        result = send_action(
            data,
            args.pump,
            args.action,
            dry_run=args.dry_run,
            dish_id=args.dish_id,
            condition=args.condition,
            trigger_source=args.trigger_source,
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0

    if args.command == "run-profile":
        result = run_profile(
            data,
            args.pump,
            args.profile,
            dry_run=args.dry_run,
            dish_id=args.dish_id,
            condition=args.condition,
            trigger_source=args.trigger_source,
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0

    if args.command == "pushpull":
        results = pushpull(
            data,
            in_pump=args.in_pump,
            out_pump=args.out_pump,
            profile_in=args.profile_in,
            profile_out=args.profile_out,
            out_delay=args.out_delay,
            safety_stop_after=args.safety_stop_after,
            dry_run=args.dry_run,
            dish_id=args.dish_id,
            condition=args.condition,
            trigger_source=args.trigger_source,
        )
        print(json.dumps(results, ensure_ascii=False))
        return 0

    if args.command == "stop-all":
        results = stop_all(
            data,
            dry_run=args.dry_run,
            dish_id=args.dish_id,
            condition=args.condition,
            trigger_source=args.trigger_source,
        )
        print(json.dumps(results, ensure_ascii=False))
        return 0

    if args.command == "calc":
        syringe = data["syringes"][args.syringe]
        ul_per_mm = syringe.get("calibrated_ul_per_mm")
        if ul_per_mm is None:
            ul_per_mm = ul_per_mm_from_inner_diameter(syringe["nominal_inner_diameter_mm"])
        result = calculate(
            args.mode,
            float(ul_per_mm),
            volume_ul=args.volume_ul,
            duration_s=args.duration_s,
            flow_ml_min=args.flow_ml_min,
            speed_mm_min=args.speed_mm_min,
            syringe_key=args.syringe,
        )
        print(json.dumps(result_to_dict(result), indent=2, ensure_ascii=False))
        return 0

    raise ValueError(f"unsupported command: {args.command}")


def send_action(
    data: dict[str, Any],
    pump_key: str,
    action: str,
    *,
    dry_run: bool = False,
    dish_id: str = "",
    condition: str = "",
    trigger_source: str = "CLI",
    profile_key: str = "",
    profile_calc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pump = make_pump(data, pump_key, dry_run=dry_run)
    result = call_action(pump, action)
    calc = profile_calc or {}
    log_command(
        result=result,
        action=action,
        dish_id=dish_id,
        condition=condition,
        trigger_source=trigger_source,
        profile=profile_key,
        syringe=calc.get("syringe", ""),
        speed_mm_min=calc.get("speed_mm_min"),
        duration_s=calc.get("duration_s"),
        target_volume_ul=calc.get("target_volume_ul"),
        estimated_volume_ul=calc.get("estimated_volume_ul"),
        note=calc.get("note", ""),
    )
    return result


def run_profile(
    data: dict[str, Any],
    pump_key: str,
    profile_key: str,
    *,
    dry_run: bool = False,
    dish_id: str = "",
    condition: str = "",
    trigger_source: str = "CLI",
) -> dict[str, Any]:
    profile_info = profile_log_info(data, profile_key)
    direction = data["profiles"][profile_key].get("direction", "forward")
    action = "start-reverse" if direction == "reverse" else "start-forward"
    # Future extension: write speed/time to A4 only after Q1H..Q6H1D command details
    # are verified on the actual hardware. Initial implementation starts saved A4 settings.
    return send_action(
        data,
        pump_key,
        action,
        dry_run=dry_run,
        dish_id=dish_id,
        condition=condition,
        trigger_source=trigger_source,
        profile_key=profile_key,
        profile_calc=profile_info,
    )


def pushpull(
    data: dict[str, Any],
    *,
    in_pump: str,
    out_pump: str,
    profile_in: str,
    profile_out: str,
    out_delay: float,
    safety_stop_after: float | None = None,
    dry_run: bool = False,
    dish_id: str = "",
    condition: str = "",
    trigger_source: str = "CLI",
) -> list[dict[str, Any]]:
    if out_delay < 0:
        raise ValueError("out_delay must be zero or positive")
    results = [
        run_profile(
            data,
            in_pump,
            profile_in,
            dry_run=dry_run,
            dish_id=dish_id,
            condition=condition,
            trigger_source=trigger_source,
        )
    ]
    if out_delay:
        time.sleep(out_delay)
    results.append(
        run_profile(
            data,
            out_pump,
            profile_out,
            dry_run=dry_run,
            dish_id=dish_id,
            condition=condition,
            trigger_source=trigger_source,
        )
    )
    if safety_stop_after is not None:
        if safety_stop_after <= 0:
            raise ValueError("safety_stop_after must be positive")
        time.sleep(safety_stop_after)
        results.extend(
            stop_all(
                data,
                dry_run=dry_run,
                dish_id=dish_id,
                condition=condition,
                trigger_source=trigger_source,
                note="safety-stop-after",
            )
        )
    return results


def stop_all(
    data: dict[str, Any],
    *,
    dry_run: bool = False,
    dish_id: str = "",
    condition: str = "",
    trigger_source: str = "CLI",
    note: str = "",
) -> list[dict[str, Any]]:
    results = []
    for pump_key in data["pumps"]:
        result = send_action(
            data,
            pump_key,
            "stop",
            dry_run=dry_run,
            dish_id=dish_id,
            condition=condition,
            trigger_source=trigger_source,
            profile_calc={"note": note},
        )
        results.append(result)
    return results


def profile_log_info(data: dict[str, Any], profile_key: str) -> dict[str, Any]:
    profile = data["profiles"][profile_key]
    syringe_key = profile["syringe"]
    calc = calculate_profile(profile, data["syringes"][syringe_key], syringe_key)
    return {
        "syringe": syringe_key,
        "speed_mm_min": calc.speed_mm_min,
        "duration_s": calc.duration_s,
        "target_volume_ul": calc.target_volume_ul,
        "estimated_volume_ul": calc.estimated_volume_ul,
        "note": profile.get("note", ""),
    }


def make_pump(data: dict[str, Any], pump_key: str, *, dry_run: bool = False) -> A4Pump:
    try:
        pump_config = data["pumps"][pump_key]
    except KeyError as exc:
        raise KeyError(f"Unknown pump: {pump_key}") from exc
    return pump_from_config(pump_key, pump_config, dry_run=dry_run)


def call_action(pump: A4Pump, action: str) -> dict[str, Any]:
    try:
        method_name = ACTION_METHODS[action]
    except KeyError as exc:
        raise ValueError(f"Unknown action: {action}") from exc
    return getattr(pump, method_name)()


if __name__ == "__main__":
    raise SystemExit(main())

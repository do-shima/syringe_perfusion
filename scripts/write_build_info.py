from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syringe_perfusion.app_info import write_build_info


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--build-type", required=True)
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args()
    print(
        write_build_info(
            args.output,
            build_type=args.build_type,
            require_clean=args.require_clean,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

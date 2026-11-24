"""Command line for the Hydra pipeline.

    python -m launcher run-hello [--source-root DIR]

`run-hello` runs `hydraos.hello.main` on Hydra's Python host. Standard output carries only the
program's own output; errors go to standard error as `error: <message>` with exit status 1.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydra.core.overlay.python.dsl.python import Left

from launcher.pipeline import SOURCE_ROOT, HydraError, load_project

HELLO = "hydraos.hello"


def _run_hello(args: argparse.Namespace) -> None:
    project = load_project([args.source_root])
    if HELLO not in project.modules:
        raise HydraError(f"no module {HELLO} under {args.source_root}")
    result = project.module(HELLO).main()
    if isinstance(result, Left):
        raise HydraError(f"{HELLO}.main failed: {result.value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m launcher", description="Run Hydra's pipeline over this repo.")
    commands = parser.add_subparsers(dest="command", required=True)
    run_hello = commands.add_parser("run-hello", help=f"run {HELLO}.main on Hydra's Python host")
    run_hello.add_argument(
        "--source-root", type=Path, default=SOURCE_ROOT, help="directory of .hydra sources (default: src/main/hydra)"
    )
    run_hello.set_defaults(handler=_run_hello)
    args = parser.parse_args(argv)
    args.source_root = args.source_root.resolve()
    try:
        args.handler(args)
    except (HydraError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

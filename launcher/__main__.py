"""Command line for the Hydra pipeline.

    python -m launcher run-hello [--source-root DIR]
    python -m launcher build [--out PATH] [--source-root DIR]

`run-hello` runs `hydraos.hello.main` on Hydra's Python host; standard output carries only the
program's own output. `build` asks the Hydra-written coder `hydraos.riscv.coder` for the boot image
of `hydraos.hello` and writes it to PATH (default: out/hello.bin in this repo). Errors go to
standard error as `error: <message>` with exit status 1.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydra.core.overlay.python.dsl.python import Left

from launcher.pipeline import REPO_ROOT, SOURCE_ROOT, HydraError, Project, load_project

HELLO = "hydraos.hello"
CODER = "hydraos.riscv.coder"


def _load(source_root: Path, *required: str) -> Project:
    project = load_project([source_root])
    for name in required:
        if name not in project.modules:
            raise HydraError(f"no module {name} under {source_root}")
    return project


def _run_hello(args: argparse.Namespace) -> None:
    project = _load(args.source_root, HELLO)
    result = project.module(HELLO).main()
    if isinstance(result, Left):
        raise HydraError(f"{HELLO}.main failed: {result.value}")


def _build(args: argparse.Namespace) -> None:
    project = _load(args.source_root, HELLO, CODER)
    result = project.module(CODER).build_image(project.graph, project.modules[HELLO])
    if isinstance(result, Left):
        raise HydraError(result.value)
    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(result.value)
    print(f"wrote {out} ({len(result.value)} bytes)", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m launcher", description="Run Hydra's pipeline over this repo.")
    commands = parser.add_subparsers(dest="command", required=True)
    source_root = argparse.ArgumentParser(add_help=False)
    source_root.add_argument(
        "--source-root", type=Path, default=SOURCE_ROOT, help="directory of .hydra sources (default: src/main/hydra)"
    )
    run_hello = commands.add_parser("run-hello", parents=[source_root], help=f"run {HELLO}.main on Hydra's Python host")
    run_hello.set_defaults(handler=_run_hello)
    build = commands.add_parser("build", parents=[source_root], help=f"write the RISC-V boot image of {HELLO}")
    build.add_argument("--out", type=Path, default=REPO_ROOT / "out" / "hello.bin", help="image path (default: out/hello.bin)")
    build.set_defaults(handler=_build)
    args = parser.parse_args(argv)
    args.source_root = args.source_root.resolve()
    try:
        args.handler(args)
    except (HydraError, OSError) as e:  # OSError: unreadable sources, unwritable --out
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

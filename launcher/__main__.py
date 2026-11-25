"""Command line for the Hydra pipeline.

    python -m launcher run-hello [--source-root DIR]
    python -m launcher build [--out PATH] [--source-root DIR] [--generated-dir DIR]

`run-hello` runs `hydraos.hello.main` on Hydra's Python host; standard output carries only the
program's own output. `build` asks the Hydra-written coder `hydraos.riscv.coder` for the boot image
of `hydraos.hello` and its derivation record, writes the image to PATH (default: out/hello.bin in this
repo) and the record beside it (out/hello.derivation.json), and reports how many of the image's bits
the record explains. The Python generated from the sources goes to DIR (default: build/python). Errors
go to standard error as `error: <message>` with exit status 1.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydra.core.overlay.python.dsl.python import Left

from launcher.pipeline import GENERATED_DIR, REPO_ROOT, SOURCE_ROOT, HydraError, Project, load_project
from launcher.record import dumps, record_json

HELLO = "hydraos.hello"
CODER = "hydraos.riscv.coder"


def _load(source_root: Path, *required: str, generated_dir: Path = GENERATED_DIR) -> Project:
    project = load_project([source_root], generated_dir=generated_dir)
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
    project = _load(args.source_root, HELLO, CODER, generated_dir=args.generated_dir)
    result = project.module(CODER).build_traced(project.graph, project.modules[HELLO], project.sources())
    if isinstance(result, Left):
        raise HydraError(result.value)
    traced = result.value
    record = record_json(traced, project.texts)
    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(traced.image)
    print(f"wrote {out} ({len(traced.image)} bytes)", file=sys.stderr)
    record_path = out.with_name(f"{out.stem}.derivation.json")
    record_path.write_text(dumps(record), encoding="utf-8")
    print(f"wrote {record_path}", file=sys.stderr)
    coverage = record["coverage"]
    print(
        f"derivation: {coverage['bits']} of {8 * len(traced.image)} bits explained, "
        f"{coverage['sourceBits']} traced to source, {coverage['atoms']} atoms",
        file=sys.stderr,
    )


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
    build.add_argument(
        "--generated-dir", type=Path, default=GENERATED_DIR, help="where the Python generated from the sources goes (default: build/python)"
    )
    build.set_defaults(handler=_build)
    args = parser.parse_args(argv)
    args.source_root = args.source_root.resolve()
    if hasattr(args, "generated_dir"):
        args.generated_dir = args.generated_dir.resolve()
    try:
        args.handler(args)
    except (HydraError, OSError) as e:  # OSError: unreadable sources, unwritable --out
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

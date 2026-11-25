"""Command line for the Hydra pipeline.

    python -m launcher run-hello [--source-root DIR]
    python -m launcher build [--out PATH] [--source-root DIR] [--generated-dir DIR]
    python -m launcher check-derivation [--jobs N] [--report PATH]

`run-hello` runs `hydraos.hello.main` on Hydra's Python host; standard output carries only the
program's own output. `build` asks the Hydra-written coder `hydraos.riscv.coder` for the boot image
of `hydraos.hello` and its derivation record, writes the image to PATH (default: out/hello.bin in this
repo) and the record beside it (out/hello.derivation.json), and reports how many of the image's bits
the record explains. The Python generated from the sources goes to DIR (default: build/python).
`check-derivation` changes each source atom of the record in turn, rebuilds each change in a fresh
process, N at a time (default 8), and compares every image with the one the record predicts
(launcher/check.py); it writes its report to PATH, or to standard output, and exits with status 1 if
any rebuild differs from its prediction. Errors go to standard error as `error: <message>` with exit
status 1.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from hydra.core.overlay.python.dsl.python import Left, Right

from launcher import check
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


def _traced(project: Project):
    result = project.module(CODER).build_traced(project.graph, project.modules[HELLO], project.sources())
    if isinstance(result, Left):
        raise HydraError(result.value)
    return result.value


def _build(args: argparse.Namespace) -> None:
    project = _load(args.source_root, HELLO, CODER, generated_dir=args.generated_dir)
    traced = _traced(project)
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


def _check_derivation(args: argparse.Namespace) -> int:
    project = _load(args.source_root, HELLO, CODER)
    traced = _traced(project)
    record = record_json(traced, project.texts)
    mutations = check.plan(record, lambda file: (REPO_ROOT / file).read_text(encoding="utf-8"))
    derive, d = project.module("hydraos.riscv.derive"), project.module("hydraos.riscv.derivation")

    def predict(m: check.Mutation) -> tuple[bytes | None, str]:
        value = d.ValueNumber(m.value["number"]) if "number" in m.value else d.ValueName(m.value["name"])
        r = derive.predict(traced.derivation, d.AtomId(m.atom), value)
        return (bytes(r.value), "") if isinstance(r, Right) else (None, r.value)

    def progress(done: int, r: check.Result) -> None:
        print(f"[{done}/{len(mutations)}] {r.outcome} {r.mutation}", file=sys.stderr, flush=True)

    started = time.monotonic()
    results = check.run(mutations, predict, args.jobs, progress)
    minutes = (time.monotonic() - started) / 60
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip() or "unknown"
    changed = subprocess.run(["git", "status", "--porcelain", "--", str(args.source_root)], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()
    coverage = record["coverage"]
    text = check.report(results, [
        f"Derivation check of {HELLO}'s boot image",
        f"  image: {record['image']['bytes']} bytes, sha256 {record['image']['sha256']}",
        f"  record: {coverage['atoms']} atoms; {coverage['bits']} of {8 * record['image']['bytes']} bits explained, {coverage['sourceBits']} traced to source",
        f"  sources: {args.source_root.relative_to(REPO_ROOT) if args.source_root.is_relative_to(REPO_ROOT) else args.source_root}"
        f" at commit {commit}{' with uncommitted changes' if changed else ''}",
        f"  {len(mutations)} mutations, each rebuilt with `python -m launcher build` in a fresh process, {args.jobs} at a time, in {minutes:.0f} minutes",
    ])
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
        print(f"wrote {args.report}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    counts = {o: sum(r.outcome == o for r in results) for o in ("matched", "rejected", "mismatched")}
    print(f"check: {len(results)} mutations, {counts['matched']} matched, {counts['rejected']} rejected by the build, "
          f"{counts['mismatched']} mismatched", file=sys.stderr)
    return 1 if counts["mismatched"] else 0


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
    checking = commands.add_parser(
        "check-derivation", parents=[source_root], help=f"check that {HELLO}'s derivation record predicts real rebuilds"
    )
    checking.add_argument("--jobs", type=int, default=8, help="rebuilds run at a time (default: 8)")
    checking.add_argument("--report", type=Path, help="where to write the report (default: standard output)")
    checking.set_defaults(handler=_check_derivation)
    args = parser.parse_args(argv)
    args.source_root = args.source_root.resolve()
    if hasattr(args, "generated_dir"):
        args.generated_dir = args.generated_dir.resolve()
    try:
        return args.handler(args) or 0
    except (HydraError, OSError) as e:  # OSError: unreadable sources, unwritable --out
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

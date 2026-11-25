"""The derivation check: does the record predict real rebuilds?

Each mutation changes one source atom of the record (hydraos.riscv.derivation) in a copy of the sources:

- a character of the message: each of bits 0 to 6, written back with Hydra's own string escaping;
- a number: each bit below the width of the image field it feeds (through copies), or below one more than
  its bit length where it feeds arithmetic; a negative number is flipped in two's complement at that width;
- a register operand: each bit of its number, written as the register with that number, which the copied
  dsl.hydra defines when no register has it;
- a label operand: every other label of the program.

Derived atoms, the names labels define, and the program's structure are not mutated (see the spec).
Every mutated copy is built with `python -m launcher build` in a fresh process, and the image is compared
with what the record predicts: hydraos.riscv.derive.predict, the derivation evaluated again with that one
atom's value changed. Each mutation ends in one of four outcomes:

- matched: the build succeeded and its image is the predicted one, bit for bit;
- rejected: one of the encoder's own checks refused the program (a value out of range, a misaligned
  instruction or target, an undefined or duplicate label, a size that disagrees with the encoding, a
  division by zero), which the prediction does not model;
- failed: the build failed for any other reason (a source that does not parse, a trace that disagrees
  with what Hydra evaluated, a crash or a timeout), which is a fault of the check or of the build;
- mismatched: the build succeeded with another image than the predicted one.

The check passes when nothing failed or mismatched.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from hydra.core.print.model import escape_string_char

from launcher.pipeline import REPO_ROOT, SOURCE_ROOT

KINDS = ("character", "number", "register", "label")
OUTCOMES = ("matched", "rejected", "failed", "mismatched")

# The errors of the encoder's own checks (hydraos.riscv.encode: inRange, checkedRegister, recordEncoding,
# layoutItem, recordOffset, encodeItem) and of the evaluator's division (hydraos.riscv.derive.evaluate).
REJECTIONS = [re.compile(p) for p in (
    r"[\w.]+: .+ -?\d+ out of range \[-?\d+, -?\d+\]",
    r"register -?\d+ out of range \[0, 31\]",
    r"[\w.]+: no fixed field is called .+",
    r"duplicate label .+",
    r"instruction at offset -?\d+ is not 4-byte aligned",
    r"[\w.]+: undefined label .+",
    r"[\w.]+: target .+ at offset -?\d+ is not 4-byte aligned",
    r"item \d+: encoded \d+ bytes, recorded size -?\d+",
    r"derivation: division by zero in .+",
)]


@dataclass(frozen=True)
class Edit:
    """Replace text[start:end] of a source file, which must read old, with new."""

    file: str  # as the record names it: relative to the repository
    start: int  # code point offsets
    end: int
    old: str
    new: str


@dataclass(frozen=True)
class Mutation:
    """One source atom given a new value, and the edits that write that value into the sources."""

    kind: str
    atom: str
    value: dict  # as the record writes values: {"number": n} or {"name": s}
    edits: tuple[Edit, ...]
    where: str  # file:line:column of the atom

    def __str__(self) -> str:
        e = self.edits[0]
        return f"{self.kind} {self.atom} := {_value_text(self.value)} ({self.where}: {e.old} -> {e.new})"


@dataclass(frozen=True)
class Result:
    mutation: Mutation
    outcome: str  # one of OUTCOMES
    detail: str  # the build's error, or how the image differs from the prediction


def plan(record: dict, read: Callable[[str], str]) -> list[Mutation]:
    """Every mutation of the record's source atoms. read gives the text of a file the record names."""
    atoms = record["atoms"]
    by_id = {a["id"]: a for a in atoms}
    users: dict[str, list[dict]] = defaultdict(list)
    for a in atoms:
        for r in _references(a["formula"]):
            users[r].append(a)
    labels = sorted(a["id"].removeprefix("label/") for a in atoms if a["id"].startswith("label/"))
    registers = {}  # number -> (name, dsl file), from the registers that call sites copy
    for a in atoms:
        if "source" in a["place"] and "copy" in a["formula"]:
            register = by_id[a["formula"]["copy"]]
            name = register["place"]["source"]["definition"].rpartition(".")[2]
            registers[register["value"]["number"]] = (name, register["place"]["source"]["span"]["file"])
    texts: dict[str, str] = {}

    def text_of(file: str) -> str:
        if file not in texts:
            texts[file] = read(file)
        return texts[file]

    out = []
    for a in atoms:
        source = a["place"].get("source")
        if source is None:
            continue
        span, formula, value = source["span"], a["formula"], a["value"]
        text = text_of(span["file"])
        start, end = _offsets(text, span)
        where = f"{span['file']}:{span['line']}:{span['column']}"

        def mutation(kind: str, new_value: dict, new_text: str, *more: Edit) -> Mutation:
            return Mutation(kind, a["id"], new_value, (Edit(span["file"], start, end, span["text"], new_text), *more), where)

        if source["character"] is not None:
            c = value["number"]
            for k in range(7):
                out.append(mutation("character", {"number": c ^ (1 << k)}, escape_string_char(c ^ (1 << k))))
        elif "stated" in formula and "number" in value:
            n, suffix = value["number"], span["text"].partition(":")[1:]
            width = _width(a["id"], n, users)
            for k in range(width):
                m = _flipped(n, k, width)
                out.append(mutation("number", {"number": m}, f"{m}{''.join(suffix)}"))
        elif "stated" in formula:
            for other in labels:
                if other != value["name"]:
                    out.append(mutation("label", {"name": other}, '"' + "".join(escape_string_char(ord(ch)) for ch in other) + '"'))
        elif "copy" in formula:  # a call site copies the number of the register it names
            n = value["number"]
            for k in range(5):
                m = n ^ (1 << k)
                if m in registers:
                    out.append(mutation("register", {"number": m}, registers[m][0]))
                else:
                    dsl_file = next(iter(registers.values()))[1]
                    dsl = text_of(dsl_file)
                    define = Edit(dsl_file, len(dsl), len(dsl), "", f"\nterm x{m} = Register{{{m}:int32}}\n")
                    out.append(mutation("register", {"number": m}, f"x{m}", define))
        # Any other source atom (the message's length) is derived from atoms that are mutated themselves.
    return out


def apply(mutation: Mutation, root: Path) -> None:
    """Write a mutation into a copy of the source root."""
    by_file: dict[str, list[Edit]] = defaultdict(list)
    for e in mutation.edits:
        by_file[e.file].append(e)
    for file, edits in by_file.items():
        path = root / (REPO_ROOT / file).relative_to(SOURCE_ROOT)
        text = path.read_text(encoding="utf-8")
        for e in sorted(edits, key=lambda e: e.start, reverse=True):
            if text[e.start:e.end] != e.old:
                raise ValueError(f"{file}: expected {e.old!r} at {e.start}, found {text[e.start:e.end]!r}")
            text = text[:e.start] + e.new + text[e.end:]
        path.write_text(text, encoding="utf-8")


def run(
    mutations: Sequence[Mutation],
    predict: Callable[[Mutation], tuple[bytes | None, str]],
    jobs: int,
    progress: Callable[[int, Result], None] = lambda done, result: None,
) -> list[Result]:
    """Rebuild every mutation, jobs at a time, and compare each image with its prediction. predict gives
    the predicted image, or None and the reason the record cannot predict one."""
    predictions = [predict(m) for m in mutations]
    results: list[Result | None] = [None] * len(mutations)
    with tempfile.TemporaryDirectory(prefix="hydra-os-check-") as work, ThreadPoolExecutor(jobs) as pool:
        futures = {pool.submit(rebuild, m, Path(work) / f"m{i:04}"): i for i, m in enumerate(mutations)}
        for done, future in enumerate(as_completed(futures), 1):
            i = futures[future]
            image, error = future.result()
            results[i] = compare(mutations[i], predictions[i], image, error)
            progress(done, results[i])
    return results


def report(results: Sequence[Result], header: Sequence[str]) -> str:
    """The check's report: a summary per kind, the rejected builds, the failures, the mismatches, then every
    mutation."""
    lines = list(header) + ["", f"{'kind':<10} {'mutations':>9} {'matched':>8} {'rejected':>9} {'failed':>7} {'mismatched':>11}"]
    for kind in (*KINDS, "total"):
        of = [r for r in results if kind in (r.mutation.kind, "total")]
        n = Counter(r.outcome for r in of)
        lines.append(f"{kind:<10} {len(of):>9} {n['matched']:>8} {n['rejected']:>9} {n['failed']:>7} {n['mismatched']:>11}")
    for title, outcome in (("Rejected by the encoder", "rejected"), ("Failed", "failed"), ("Mismatched", "mismatched")):
        found = [r for r in results if r.outcome == outcome]
        lines += ["", f"{title}: {len(found)}"] + [f"  {r.mutation}\n    {r.detail}" for r in found]
    lines += ["", "Every mutation:"] + [f"  {r.outcome:<10} {r.mutation}" for r in results]
    return "\n".join(lines) + "\n"


def rebuild(mutation: Mutation, work: Path) -> tuple[bytes | None, str]:
    """Build a copy of the sources with the mutation applied, in a fresh process: the image, or None and the
    build's error. Whatever goes wrong is reported, never raised, so one mutation cannot end the run."""
    root = work / "src"
    try:
        shutil.copytree(SOURCE_ROOT, root)
        apply(mutation, root)
        out = work / "hello.bin"
        build = [sys.executable, "-m", "launcher", "build", "--source-root", str(root), "--out", str(out), "--generated-dir", str(work / "generated")]
        r = subprocess.run(build, cwd=REPO_ROOT, capture_output=True, text=True, timeout=1800)
        if r.returncode == 0:
            return out.read_bytes(), ""
        errors = [line.removeprefix("error: ") for line in r.stderr.splitlines() if line.startswith("error: ")]
        return None, errors[-1] if errors else f"exit status {r.returncode}: {r.stderr.strip().splitlines()[-1:]}"
    except Exception as e:  # noqa: BLE001 - reported as the mutation's outcome
        return None, f"the rebuild did not finish: {type(e).__name__}: {e}"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def is_rejection(error: str) -> bool:
    """Whether a build's error is one of the encoder's own checks refusing the program."""
    return any(p.fullmatch(error) for p in REJECTIONS)


def compare(mutation: Mutation, predicted: tuple[bytes | None, str], image: bytes | None, error: str) -> Result:
    if image is None:
        return Result(mutation, "rejected" if is_rejection(error) else "failed", error)
    expected, why = predicted
    if expected is None:
        return Result(mutation, "mismatched", f"the build succeeded, but the record predicts no image: {why}")
    if expected == image:
        return Result(mutation, "matched", "")
    if len(expected) != len(image):
        return Result(mutation, "mismatched", f"predicted {len(expected)} bytes, built {len(image)}")
    bits = [f"{i}.{b}" for i in range(len(image)) for b in range(8) if (expected[i] ^ image[i]) >> b & 1]
    return Result(mutation, "mismatched", f"bits (byte.bit) that differ from the prediction: {' '.join(bits)}")


def _references(formula: dict) -> list[str]:
    """The atoms a formula, as the record writes it, refers to."""
    ((kind, arg),) = formula.items()
    if kind in ("copy", "labelOffset"):
        return [arg]
    if kind in ("sum", "count"):
        return list(arg)
    if kind in ("difference", "product", "quotient"):
        return [arg["x"], arg["y"]]
    if kind in ("bits", "utf8"):
        return [arg["atom"]]
    return []


def _width(atom: str, value: int, users: dict[str, list[dict]]) -> int:
    """How many low bits of a number matter: the width of the image field it fills (through copies), the
    highest bit a bits formula takes from it, or one more than its bit length where it feeds arithmetic."""
    widths = []
    for u in users.get(atom, []):
        f = u["formula"]
        if "copy" in f:
            widths.append(u["place"]["image"]["width"] if "image" in u["place"] else _width(u["id"], value, users))
        elif "bits" in f:
            widths.append(f["bits"]["lo"] + f["bits"]["width"])
        else:
            widths.append(abs(value).bit_length() + 1)
    return max(widths, default=abs(value).bit_length() + 1)


def _flipped(n: int, k: int, width: int) -> int:
    """n with bit k flipped, in two's complement at width bits when n is negative."""
    f = (n % (1 << width)) ^ (1 << k)
    return f - (1 << width) if n < 0 and f >= 1 << (width - 1) else f


def _offsets(text: str, span: dict) -> tuple[int, int]:
    """The code point offsets of a span, from its lines and columns, checked against its text."""
    start, end = _offset(text, span["line"], span["column"]), _offset(text, span["endLine"], span["endColumn"])
    if text[start:end] != span["text"]:
        raise ValueError(f"{span['file']}:{span['line']}:{span['column']}: expected {span['text']!r}, found {text[start:end]!r}")
    return start, end


def _offset(text: str, line: int, column: int) -> int:
    """The code point offset of a 1-based line and 1-based column counted in UTF-16 code units."""
    if "\r" in text:
        raise ValueError("a source with CR line ends; the check expects LF")
    lines = text.split("\n")
    at = sum(len(s) + 1 for s in lines[: line - 1])
    units, i = 0, 0
    while units < column - 1:
        units += 2 if ord(lines[line - 1][i]) >= 0x10000 else 1
        i += 1
    return at + i


def _value_text(value: dict) -> str:
    return str(value["number"]) if "number" in value else f'"{value["name"]}"'

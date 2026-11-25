"""The derivation check's plan: which source atoms it changes, to what, and how each change is written
back into a copy of the sources. (The full check, which rebuilds every mutation, runs from the command
line; its report is committed under docs/evidence/.)"""

from collections import Counter

import pytest
from hydra.core.overlay.python.dsl.python import Right

from helpers import run_launcher
from launcher.check import Result, apply, compare, plan, report
from launcher.pipeline import REPO_ROOT, SOURCE_ROOT
from launcher.record import record_json

RUNTIME = "src/main/hydra/hydraos/riscv/runtime.hydra"
DSL = "src/main/hydra/hydraos/riscv/dsl.hydra"
LUI_T0 = "source/hydraos.riscv.runtime.startup#listElement:1"  # lui t0 256:int32


@pytest.fixture(scope="module")
def mutations(project):
    coder = project.module("hydraos.riscv.coder")
    r = coder.build_traced(project.graph, project.modules["hydraos.hello"], project.sources())
    assert isinstance(r, Right), r
    return plan(record_json(r.value, project.texts), lambda file: (REPO_ROOT / file).read_text(encoding="utf-8"))


def one(mutations, atom, value):
    found = [m for m in mutations if m.atom == atom and m.value == value]
    assert len(found) == 1, found
    return found[0]


def edits(m):
    return [(e.file, e.old, e.new) for e in m.edits]


def test_the_plan_has_every_kind_of_source_atom(mutations):
    assert Counter(m.kind for m in mutations) == {"character": 119, "number": 373, "register": 160, "label": 42}


def test_every_character_of_the_message_is_flipped_in_bits_0_to_6(mutations):
    chars = [m for m in mutations if m.kind == "character"]
    assert Counter(m.atom for m in chars) == {f"hydraos.hello.main/char/{i}": 7 for i in range(17)}
    assert sorted(m.value["number"] for m in chars if m.atom == "hydraos.hello.main/char/0") == sorted(72 ^ (1 << k) for k in range(7))


def test_a_character_flipped_to_a_quote_is_written_escaped(mutations):
    m = one(mutations, "hydraos.hello.main/char/5", {"number": 34})  # the space, bit 1
    assert edits(m) == [("src/main/hydra/hydraos/hello.hydra", " ", '\\"')]


def test_a_character_flipped_to_a_control_character_is_written_as_a_unicode_escape(mutations):
    m = one(mutations, "hydraos.hello.main/char/16", {"number": 11})  # \n, bit 0
    assert edits(m) == [("src/main/hydra/hydraos/hello.hydra", "\\n", "\\u000b")]


def test_a_number_is_flipped_below_the_width_of_the_field_it_feeds(mutations):
    count = Counter(m.atom for m in mutations if m.kind == "number")
    assert count["encode/lui/opcode"] == 7
    assert count["encode/beq/funct3"] == 3
    assert count["encode/wfi/funct12"] == 12
    assert count["source/hydraos.riscv.dsl.t0#wrapBody"] == 5
    assert count[f"{LUI_T0}/applicationArgument"] == 20
    assert count["source/hydraos.riscv.runtime.startup#listElement:4/applicationArgument"] == 12  # sw's split immediate


def test_a_number_that_feeds_arithmetic_is_flipped_below_one_more_than_its_bit_length(mutations):
    count = Counter(m.atom for m in mutations if m.kind == "number")
    assert (count["encode/pageSize"], count["encode/pageHalf"], count["encode/instructionSize"]) == (14, 13, 4)
    assert (count["encode/loadAddressSize"], count["encode/labelSize"]) == (5, 1)


def test_a_negative_immediate_is_flipped_in_twos_complement(mutations):
    atom = "source/hydraos.riscv.runtime.writeStdoutRoutine#listElement:11/applicationArgument"  # addi a1 a1 -1
    values = [m.value["number"] for m in mutations if m.atom == atom]
    assert values == [-2, -3, -5, -9, -17, -33, -65, -129, -257, -513, -1025, 2047]
    assert edits(one(mutations, atom, {"number": 2047})) == [(RUNTIME, "-1:int32", "2047:int32")]


def test_a_register_flipped_to_a_named_number_uses_that_name(mutations):
    m = one(mutations, f"{LUI_T0}/applicationFunction/applicationArgument", {"number": 7})  # t0 is x5; x7 is t2
    assert edits(m) == [(RUNTIME, "t0", "t2")]


def test_a_register_flipped_to_an_unnamed_number_is_defined_in_the_copied_dsl(mutations):
    m = one(mutations, f"{LUI_T0}/applicationFunction/applicationArgument", {"number": 4})
    assert edits(m) == [(RUNTIME, "t0", "x4"), (DSL, "", "\nterm x4 = Register{4:int32}\n")]


def test_a_label_operand_becomes_every_other_label(mutations):
    atom = "source/hydraos.riscv.runtime.startup#listElement:0/applicationArgument"  # jal ra "main"
    assert sorted(m.value["name"] for m in mutations if m.atom == atom) == [
        "halt", "main.message", "writeStdout", "writeStdout.done", "writeStdout.loop", "writeStdout.wait"]
    assert edits(one(mutations, atom, {"name": "halt"})) == [(RUNTIME, '"main"', '"halt"')]


def test_derived_atoms_are_not_mutated(mutations):
    atoms = {m.atom for m in mutations}
    assert not [a for a in atoms if not (a.startswith("source/") or a.startswith("encode/") or "/char/" in a)]
    assert "source/hydraos.riscv.coder.mainProgram#lambdaBody/wrapBody/applicationArgument/listElement:1/listElement:2/applicationArgument" not in atoms


def test_a_mutation_is_written_into_a_copy_of_the_sources(mutations, tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    for p in SOURCE_ROOT.rglob("*.hydra"):
        (root / p.relative_to(SOURCE_ROOT)).parent.mkdir(parents=True, exist_ok=True)
        (root / p.relative_to(SOURCE_ROOT)).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    apply(one(mutations, f"{LUI_T0}/applicationFunction/applicationArgument", {"number": 4}), root)
    runtime = (root / "hydraos/riscv/runtime.hydra").read_text(encoding="utf-8")
    dsl = (root / "hydraos/riscv/dsl.hydra").read_text(encoding="utf-8")
    assert "  lui x4 256:int32,\n  lui t1 5:int32," in runtime
    assert dsl.endswith("\nterm x4 = Register{4:int32}\n")
    assert (SOURCE_ROOT / "hydraos/riscv/runtime.hydra").read_text(encoding="utf-8").count("lui t0 256:int32") == 1


def test_a_rebuild_is_matched_rejected_or_mismatched_against_its_prediction(mutations):
    m = mutations[0]
    assert compare(m, (b"\x00\x01", ""), b"\x00\x01", "") == Result(m, "matched", "")
    assert compare(m, (b"\x00\x01", ""), None, "addi: immediate 3413 out of range [-2048, 2047]") == Result(
        m, "rejected", "addi: immediate 3413 out of range [-2048, 2047]")
    assert compare(m, (b"\x00\x01", ""), b"\x00\x03", "") == Result(m, "mismatched", "bits (byte.bit) that differ from the prediction: 1.1")
    assert compare(m, (None, "derivation: division by zero in encode/pageSize"), b"\x00", "") == Result(
        m, "mismatched", "the build succeeded, but the record predicts no image: derivation: division by zero in encode/pageSize")


def test_the_report_counts_each_kind_and_lists_what_did_not_match(mutations):
    chars = [m for m in mutations if m.kind == "character"]
    text = report([Result(chars[0], "matched", ""), Result(chars[1], "mismatched", "bits (byte.bit) that differ from the prediction: 88.0")], ["header"])
    assert text.startswith("header\n")
    assert "character          2        1         0           1" in text
    assert "total              2        1         0           1" in text
    assert f"Mismatched: 1\n  {chars[1]}\n    bits (byte.bit) that differ from the prediction: 88.0" in text


def test_the_command_is_available():
    r = run_launcher("check-derivation", "--help")
    assert r.returncode == 0, r.stderr.decode()
    assert "--jobs" in r.stdout.decode() and "--report" in r.stdout.decode()

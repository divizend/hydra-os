"""The derivation record: the JSON the build writes beside the image, with every source place resolved to
the text it names."""

import json
import subprocess

import pytest
from hydra.core.overlay.python.dsl.python import None_, Right
from hydra.core.overlay.python.util.cons_list import ConsList
from hydra.core.paths import SubtermPath

from helpers import GOLDEN_IMAGE, run_launcher
from launcher.pipeline import REPO_ROOT
from launcher.record import Resolver, record_json

HELLO_SOURCE = "src/main/hydra/hydraos/hello.hydra"


@pytest.fixture(scope="module")
def record(project):
    coder = project.module("hydraos.riscv.coder")
    r = coder.build_traced(project.graph, project.modules["hydraos.hello"], project.sources())
    assert isinstance(r, Right), r
    return record_json(r.value, project.texts)


@pytest.fixture(scope="module")
def by_id(record):
    return {a["id"]: a for a in record["atoms"]}


def last_commit(path):
    return subprocess.run(["git", "log", "-1", "--format=%H", "--", path], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.strip()


def test_the_record_carries_the_image_and_its_coverage(record):
    assert record["image"] == {"bytes": 105, "sha256": "b6b66453b6357317825b8db6b818dcb1298253ae780c53413ef87e530eeff59f"}
    assert record["coverage"] == {"bits": 840, "sourceBits": 840, "atoms": len(record["atoms"])}


def test_every_source_place_resolves_to_text_that_denotes_its_value(record, by_id):
    kinds = set()
    for a in record["atoms"]:
        if "source" not in a["place"]:
            continue
        source, value, formula = a["place"]["source"], a["value"], a["formula"]
        text = source["span"]["text"]
        if source["character"] is not None:
            kind = "character"
            assert json.loads(f'"{text}"') == chr(value["number"]), a
        elif "stated" in formula and "number" in value:
            kind = "number"
            assert int(text.split(":")[0]) == value["number"], a
        elif "stated" in formula:
            kind = "name"
            assert text == json.dumps(value["name"]), a
        elif "copy" in formula:
            kind = "register"
            register = by_id[formula["copy"]]
            assert register["id"] == f"source/hydraos.riscv.dsl.{text}#wrapBody", a
            assert register["value"] == value, a
        elif "count" in formula:
            kind = "length"
            assert text == "(lists.length (literals.binaryToBytes bytes))", a  # Hydra's span includes the grouping parentheses
            assert value["number"] == len(formula["count"]), a
        else:
            pytest.fail(f"a source atom of an unexpected kind: {a}")
        kinds.add(kind)
    assert kinds == {"character", "number", "name", "register", "length"}


def test_a_negative_immediate_resolves_to_its_literal(by_id):
    span = by_id["source/hydraos.riscv.runtime.writeStdoutRoutine#listElement:11/applicationArgument"]["place"]["source"]["span"]
    assert span["text"] == "-1:int32"


def test_the_last_character_of_the_message_is_the_escape_backslash_n(by_id):
    span = by_id["hydraos.hello.main/char/16"]["place"]["source"]["span"]
    assert span["text"] == "\\n"
    assert (span["file"], span["line"], span["column"], span["endLine"], span["endColumn"]) == (HELLO_SOURCE, 8, 54, 8, 56)


def test_a_span_links_to_its_line_at_the_commit_that_last_changed_the_file(by_id):
    span = by_id["hydraos.hello.main/char/0"]["place"]["source"]["span"]
    assert span["url"] == f"https://github.com/divizend/hydra-os/blob/{last_commit(HELLO_SOURCE)}/{HELLO_SOURCE}#L8"


def test_build_writes_the_committed_record_beside_the_image(tmp_path):
    out, generated = tmp_path / "hello.bin", tmp_path / "generated"
    r = run_launcher("build", "--out", str(out), "--generated-dir", str(generated))
    err = r.stderr.decode()
    assert r.returncode == 0, err
    assert out.read_bytes() == GOLDEN_IMAGE
    assert (generated / "hydraos" / "riscv" / "coder.py").is_file()
    fresh = (tmp_path / "hello.derivation.json").read_text(encoding="utf-8")
    assert fresh == (REPO_ROOT / "out" / "hello.derivation.json").read_text(encoding="utf-8")
    atoms = len(json.loads(fresh)["atoms"])
    assert f"derivation: 840 of 840 bits explained, 840 traced to source, {atoms} atoms" in err


def test_every_item_resolves_to_the_call_that_wrote_it(record):
    items = record["items"]
    assert len(items) == 29
    assert [i["place"]["span"]["text"] for i in items[5:8]] == ['label "halt"', "wfi", 'jal zero "halt"']
    assert items[6]["operands"] == []
    assert items[28]["place"]["span"]["text"] == "data bytes"
    assert items[28]["operands"][0] == {"role": "byte", "atom": "message/0"}


def test_a_definition_with_a_type_signature_resolves(project):
    d = project.module("hydraos.riscv.derivation")
    text = "## A module.\nmodule m\n\n## The answer.\nterm answer : int32 = 42:int32\n"
    resolve = Resolver({"m": ("m.hydra", text)}, lambda file: None)
    span = resolve(d.SourcePlace("m.answer", SubtermPath(ConsList.of()), None_()))
    assert (span["text"], span["line"], span["column"]) == ("42:int32", 5, 23)

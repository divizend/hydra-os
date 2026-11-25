"""Tracing: the encoder records every constant, offset and field as an atom and assembles the image
from them; the coder traces the message and every operand back to source text."""

import pytest
import hydra.core.model as M
import hydra.core.packaging as P
from hydra.core.overlay.python.dsl.python import Given, Left, None_, Right
from hydra.core.overlay.python.util.cons_list import ConsList
from hydra.core.print.paths import subterm_path

from helpers import GOLDEN_IMAGE, program


@pytest.fixture(scope="module")
def enc(project):
    return project.module("hydraos.riscv.encode")


@pytest.fixture(scope="module")
def coder(project):
    return project.module("hydraos.riscv.coder")


@pytest.fixture(scope="module")
def d(project):
    return project.module("hydraos.riscv.derivation")


@pytest.fixture(scope="module")
def derive(project):
    return project.module("hydraos.riscv.derive")


@pytest.fixture(scope="module")
def hello_program(project):
    r = project.module("hydraos.riscv.coder").compile_module(project.graph, project.modules["hydraos.hello"])
    assert isinstance(r, Right), r
    return r.value


def traced(project, coder, name, sources=None):
    """build_traced for a module, with every module of the project as sources unless others are given."""
    if sources is None:
        sources = ConsList.of(*project.modules.values())
    return coder.build_traced(project.graph, project.modules[name], sources)


@pytest.fixture(scope="module")
def hello(project, coder):
    r = traced(project, coder, "hydraos.hello")
    assert isinstance(r, Right), r
    return r.value


def atoms_by_id(t):
    return {a.id.value: a for a in t.derivation.value}


def ancestors(derive, t, key):
    """The atom and every atom its value follows from."""
    by_id, values = atoms_by_id(t), derive.atom_values(t.derivation.value)
    seen, todo = set(), [key]
    while todo:
        k = todo.pop()
        if k not in seen:
            seen.add(k)
            todo.extend(r.value for r in derive.references(values, by_id[k].formula))
    return seen


def atoms_of_byte(d, t, b):
    """The image atoms holding bits of byte b of the image."""
    found = []
    for a in t.derivation.value:
        if isinstance(a.place, d.PlaceImage):
            p = a.place.value
            lo = (b - p.offset) * 8
            if 0 <= lo < 32 and p.lo < lo + 8 and lo < p.lo + p.width:
                found.append(a.id.value)
    return sorted(found)


def source_place(atom):
    p = atom.place.value
    return p.definition, subterm_path(p.path), p.character


def test_the_image_assembled_from_the_encoders_atoms_is_the_golden_image(enc, hello_program):
    r = enc.encode_traced(enc.untraced(hello_program))
    assert isinstance(r, Right), r
    assert r.value.image == GOLDEN_IMAGE
    assert r.value.coverage.bits == 840


def test_an_out_of_range_constant_is_rejected(project, enc):
    dsl, model = project.module("hydraos.riscv.dsl"), project.module("hydraos.riscv.model")
    c = enc.constants()
    bad = c.with_encodings(ConsList.of(*[e.with_opcode(147) if e.mnemonic == "addi" else e for e in c.encodings]))
    r = enc.encode_with(bad, enc.untraced(program(model, [dsl.addi(dsl.t1, dsl.t1, 1)])))
    assert r == Left("addi: opcode 147 out of range [0, 127]")


def test_a_size_that_disagrees_with_the_encoding_is_rejected(project, enc):
    dsl, model = project.module("hydraos.riscv.dsl"), project.module("hydraos.riscv.model")
    bad = enc.constants().with_instruction_size(5)
    r = enc.encode_with(bad, enc.untraced(program(model, [dsl.wfi])))
    assert r == Left("item 0: encoded 4 bytes, recorded size 5")


def test_every_bit_of_hello_traces_back_to_source(hello):
    assert hello.image == GOLDEN_IMAGE
    assert (hello.coverage.bits, hello.coverage.source_bits) == (840, 840)


def test_byte_0x31_reaches_its_register_its_encoding_and_its_branch_target(d, derive, hello):
    by_id = atoms_by_id(hello)
    assert atoms_of_byte(d, hello, 0x31) == ["image/48/funct3", "image/48/imm[4:1]", "image/48/rs1"]

    register = "source/hydraos.riscv.dsl.a1#wrapBody"
    assert register in ancestors(derive, hello, "image/48/rs1")
    assert by_id[register].value == d.ValueNumber(11)
    assert source_place(by_id[register]) == ("hydraos.riscv.dsl.a1", "wrapBody", None_())

    assert "encode/beq/funct3" in ancestors(derive, hello, "image/48/funct3")
    assert source_place(by_id["encode/beq/funct3"]) == (
        "hydraos.riscv.encode.encodings", "listElement:2/recordField:fixed/listElement:0/recordField:value", None_())

    target = "source/hydraos.riscv.runtime.writeStdoutRoutine#listElement:3/applicationArgument"
    assert by_id["word/48/offset"].formula == d.FormulaDifference(d.Operands(d.AtomId("word/48/target"), d.AtomId("pc/15")))
    assert {target, "label/writeStdout.done", "pc/15"} <= ancestors(derive, hello, "image/48/imm[4:1]")
    assert by_id[target].value == d.ValueName("writeStdout.done")


def test_byte_0x58_is_the_utf8_of_the_first_character_of_the_message(d, hello):
    by_id = atoms_by_id(hello)
    assert atoms_of_byte(d, hello, 0x58) == ["image/88/byte"]
    assert by_id["image/88/byte"].formula == d.FormulaCopy(d.AtomId("message/0"))
    assert by_id["message/0"].formula == d.FormulaUtf8(d.Utf8Byte(d.AtomId("hydraos.hello.main/char/0"), 0))
    char = by_id["hydraos.hello.main/char/0"]
    assert char.value == d.ValueNumber(ord("H"))
    assert source_place(char) == ("hydraos.hello.main", "applicationArgument/applicationArgument", Given(0))


def test_the_length_operand_is_the_count_of_the_message_bytes(d, hello):
    by_id = atoms_by_id(hello)
    length = "source/hydraos.riscv.coder.mainProgram#lambdaBody/wrapBody/applicationArgument/listElement:1/listElement:2/applicationArgument"
    assert by_id[length].formula == d.FormulaCount(ConsList.of(*[d.AtomId(f"message/{k}") for k in range(17)]))
    assert by_id[length].value == d.ValueNumber(17)


@pytest.mark.parametrize("name", ["hydraos.indirect", "hydraos.computed"])
def test_without_sources_a_module_still_builds_the_golden_image(project, coder, name):
    r = traced(project, coder, name, ConsList.of())
    assert isinstance(r, Right), r
    assert r.value.image == GOLDEN_IMAGE


def test_a_message_written_in_another_definition_is_traced_per_character(project, coder, d):
    r = traced(project, coder, "hydraos.indirect")
    assert isinstance(r, Right), r
    assert (r.value.image, r.value.coverage.source_bits) == (GOLDEN_IMAGE, 840)
    char = atoms_by_id(r.value)["hydraos.indirect.greeting/char/16"]
    assert char.value == d.ValueNumber(10)
    assert source_place(char) == ("hydraos.indirect.greeting", "applicationArgument", Given(16))


def test_a_computed_message_is_traced_as_a_whole_on_the_argument_of_writeStdout(project, coder, d):
    r = traced(project, coder, "hydraos.computed")
    assert isinstance(r, Right), r
    assert (r.value.image, r.value.coverage.source_bits) == (GOLDEN_IMAGE, 840)
    by_id = atoms_by_id(r.value)
    assert not [k for k in by_id if "/char/" in k]
    first = by_id["message/0"]
    assert (first.value, first.formula) == (d.ValueNumber(ord("H")), d.FormulaStated())
    assert source_place(first) == ("hydraos.computed.main", "applicationArgument", None_())


def int32(n):
    return M.TermLiteral(M.LiteralInteger(M.IntegerValueInt32(n)))


def edited(project, name, edit):
    """Every module of the project, with the body of the definition called name replaced by edit(body)."""
    def definition(x):
        if isinstance(x, P.DefinitionTerm) and x.value.name.value == name:
            return P.DefinitionTerm(x.value.with_body(edit(x.value.body)))
        return x
    return ConsList.of(*[m.with_definitions(ConsList.of(*[definition(x) for x in m.definitions])) for m in project.modules.values()])


def in_list(f):
    """An edit of an annotated list literal: f gets and returns the elements."""
    def edit(t):
        if isinstance(t, M.TermAnnotated):
            return M.TermAnnotated(t.value.with_body(edit(t.value.body)))
        return M.TermList(ConsList.of(*f(list(t.value))))
    return edit


def replaced(i, g):
    return in_list(lambda xs: [g(x) if j == i else x for j, x in enumerate(xs)])


def test_a_source_that_disagrees_with_the_program_is_rejected(project, coder):
    register = M.TermWrap(M.WrappedTerm(M.Name("hydraos.riscv.model.Register"), int32(6)))
    r = traced(project, coder, "hydraos.hello", edited(project, "hydraos.riscv.dsl.t0", lambda body: register))
    assert r == Left("hydraos.riscv.coder: item 1 (lui at hydraos.riscv.runtime.startup#listElement:1) traces to rd 6, imm 256, "
                     "but Hydra evaluated rd 5, imm 256")


def test_a_source_with_another_constructor_is_rejected(project, coder):
    def la(call):  # jal ra "main" -> la ra "main"
        f = call.value.function.value
        return M.TermApplication(call.value.with_function(M.TermApplication(f.with_function(M.TermVariable(M.Name("hydraos.riscv.dsl.la"))))))
    r = traced(project, coder, "hydraos.hello", edited(project, "hydraos.riscv.runtime.startup", replaced(0, la)))
    assert r == Left("hydraos.riscv.coder: item 0 (la at hydraos.riscv.runtime.startup#listElement:0) is a jal in the program Hydra evaluated")


def test_a_source_with_another_label_is_rejected(project, coder):
    def stop(call):
        return M.TermApplication(call.value.with_argument(M.TermLiteral(M.LiteralString("stop"))))
    r = traced(project, coder, "hydraos.hello", edited(project, "hydraos.riscv.runtime.startup", replaced(5, stop)))
    assert r == Left('hydraos.riscv.coder: item 5 (label at hydraos.riscv.runtime.startup#listElement:5) traces to label "stop", '
                     'but Hydra evaluated label "halt"')


def test_a_source_with_another_number_of_items_is_rejected(project, coder):
    r = traced(project, coder, "hydraos.hello", edited(project, "hydraos.riscv.runtime.startup", in_list(lambda xs: xs[:6] + xs[7:])))
    assert r == Left("hydraos.riscv.coder: the sources give 28 items, but Hydra evaluated 29")


def test_an_operand_that_is_not_a_literal_a_register_or_the_message_is_named(project, coder):
    def computed(call):  # lui t0 256 -> lui t0 (math.add 255 1)
        add = M.TermApplication(M.Application(M.TermApplication(M.Application(M.TermVariable(M.Name("hydra.core.lib.math.add")), int32(255))), int32(1)))
        return M.TermApplication(call.value.with_argument(add))
    r = traced(project, coder, "hydraos.hello", edited(project, "hydraos.riscv.runtime.startup", replaced(1, computed)))
    assert r == Left("hydraos.riscv.coder: cannot trace the imm of lui at hydraos.riscv.runtime.startup#listElement:1/applicationArgument: "
                     "application of hydra.core.lib.math.add")


def test_sources_without_the_coder_are_named(project, coder):
    r = traced(project, coder, "hydraos.hello", ConsList.of(project.modules["hydraos.hello"]))
    assert r == Left("hydraos.riscv.coder: no definition hydraos.riscv.coder.mainProgram among the sources")


def test_a_traced_message_that_disagrees_with_the_evaluated_bytes_is_rejected(project, coder, derive):
    r = coder.trace_message(project.modules["hydraos.hello"], b"Hello from Hydra!", derive.recording_of(ConsList.of()))
    assert r == Left("hydraos.riscv.coder: byte 16 of the message traced to hydraos.hello.main is 10, but Hydra evaluated 33")

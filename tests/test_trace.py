"""Tracing: the encoder records every constant, offset and field as an atom and assembles the image
from them; the coder traces the message and every operand back to source text."""

import pytest
from hydra.core.overlay.python.dsl.python import Left, Right
from hydra.core.overlay.python.util.cons_list import ConsList

from helpers import GOLDEN_IMAGE, program


@pytest.fixture(scope="module")
def enc(project):
    return project.module("hydraos.riscv.encode")


@pytest.fixture(scope="module")
def hello_program(project):
    r = project.module("hydraos.riscv.coder").compile_module(project.graph, project.modules["hydraos.hello"])
    assert isinstance(r, Right), r
    return r.value


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

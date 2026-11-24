"""RISC-V encoding: every supported instruction, label-relative offsets, and every error.

Expected bytes were produced by GNU as 2.40 (-march=rv64i -mno-relax) and are cross-checked here by
decoding our own output with GNU objdump. Neither tool takes part in building the image.
"""

import pytest
from hydra.core.overlay.python.dsl.python import Left, Right

from helpers import encode, objdump

W = "73005010"  # wfi
CASES = [  # (name, items, expected hex, objdump prefix)
    ("addi_positive", lambda d: [d.addi(d.t1, d.t1, 1365)], "13035355", ["addi x6,x6,1365"]),
    ("addi_negative", lambda d: [d.addi(d.a1, d.a1, -1)], "9385f5ff", ["addi x11,x11,-1"]),
    ("addi_zero_rs1", lambda d: [d.addi(d.a1, d.zero, 17)], "93051001", ["addi x11,x0,17"]),
    ("andi", lambda d: [d.andi(d.t1, d.t1, 32)], "13730302", ["andi x6,x6,32"]),
    ("lbu_offset", lambda d: [d.lbu(d.t1, d.t0, 5)], "03c35200", ["lbu x6,5(x5)"]),
    ("lbu_zero", lambda d: [d.lbu(d.t2, d.a0, 0)], "83430500", ["lbu x7,0(x10)"]),
    ("lui_small", lambda d: [d.lui(d.t1, 5)], "37530000", ["lui x6,0x5"]),
    ("lui_large", lambda d: [d.lui(d.t0, 65536)], "b7020010", ["lui x5,0x10000"]),
    ("sb", lambda d: [d.sb(d.t2, d.t0, 0)], "23807200", ["sb x7,0(x5)"]),
    ("sw", lambda d: [d.sw(d.t1, d.t0, 0)], "23a06200", ["sw x6,0(x5)"]),
    ("jalr", lambda d: [d.jalr(d.zero, d.ra, 0)], "67800000", ["jalr x0,0(x1)"]),
    ("wfi", lambda d: [d.wfi], W, ["wfi"]),
    ("jal_forward", lambda d: [d.jal(d.ra, "main"), *[d.wfi] * 6, d.label("main")],
     "ef00c001" + W * 6, ["jal x1,0x1c"] + ["wfi"] * 6),
    ("jal_backward", lambda d: [d.label("halt"), d.wfi, d.jal(d.zero, "halt")],
     W + "6ff0dfff", ["wfi", "jal x0,0x0"]),
    ("beq_forward", lambda d: [d.beq(d.a1, d.zero, "done"), *[d.wfi] * 8, d.label("done")],
     "63820502" + W * 8, ["beq x11,x0,0x24"] + ["wfi"] * 8),
    ("beq_backward", lambda d: [d.label("wait"), d.wfi, d.wfi, d.beq(d.t1, d.zero, "wait")],
     W * 2 + "e30c03fe", ["wfi", "wfi", "beq x6,x0,0x0"]),
    ("la_near", lambda d: [d.la(d.a0, "msg"), *[d.wfi] * 13, d.label("msg")],
     "17050000" "1305c503" + W * 13, ["auipc x10,0x0", "addi x10,x10,60"] + ["wfi"] * 13),
    ("la_far", lambda d: [d.la(d.a0, "far"), d.data(bytes(2040)), d.label("far")],
     "17150000" "13050580" + "00" * 2040, ["auipc x10,0x1", "addi x10,x10,-2048"]),
    ("data_verbatim", lambda d: [d.data(b"Hi")], "4869", []),
    ("empty_program", lambda d: [], "", []),
]
ERRORS = [  # (name, items, exact Left message)
    ("addi_imm_too_big", lambda d, m: [d.addi(d.a0, d.a0, 2048)], "addi: immediate 2048 out of range [-2048, 2047]"),
    ("lui_imm_too_big", lambda d, m: [d.lui(d.t0, 1048576)], "lui: immediate 1048576 out of range [0, 1048575]"),
    ("register_out_of_range", lambda d, m: [d.addi(m.Register(32), d.zero, 0)], "register 32 out of range [0, 31]"),
    ("undefined_label", lambda d, m: [d.jal(d.zero, "nowhere")], "jal: undefined label nowhere"),
    ("duplicate_label", lambda d, m: [d.label("main"), d.label("main")], "duplicate label main"),
    ("beq_out_of_range", lambda d, m: [d.beq(d.a1, d.zero, "far"), d.data(bytes(4092)), d.label("far")],
     "beq: offset 4096 out of range [-4096, 4094]"),
    ("misaligned_instruction", lambda d, m: [d.data(b"x"), d.wfi], "instruction at offset 1 is not 4-byte aligned"),
    ("misaligned_target", lambda d, m: [d.jal(d.zero, "odd"), d.data(b"x"), d.label("odd")],
     "jal: target odd at offset 5 is not 4-byte aligned"),
]


@pytest.fixture(scope="module")
def dsl(project):
    return project.module("hydraos.riscv.dsl")


@pytest.fixture(scope="module")
def model(project):
    return project.module("hydraos.riscv.model")


@pytest.mark.parametrize("name,build,hexbytes,prefix", CASES, ids=[c[0] for c in CASES])
def test_encoding(project, dsl, name, build, hexbytes, prefix):
    result = encode(project, build(dsl))
    assert isinstance(result, Right), result
    assert result.value == bytes.fromhex(hexbytes)


DISASSEMBLED = [c for c in CASES if c[3]]


@pytest.mark.parametrize("name,build,hexbytes,prefix", DISASSEMBLED, ids=[c[0] for c in DISASSEMBLED])
def test_encoding_matches_gnu_objdump(project, dsl, name, build, hexbytes, prefix):
    result = encode(project, build(dsl))
    assert isinstance(result, Right), result
    assert objdump(result.value)[: len(prefix)] == prefix


@pytest.mark.parametrize("name,build,message", ERRORS, ids=[e[0] for e in ERRORS])
def test_encoding_error(project, dsl, model, name, build, message):
    result = encode(project, build(dsl, model))
    assert isinstance(result, Left), result
    assert result.value == message

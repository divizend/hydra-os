"""The bare-metal runtime: start-up/power-off and the writeStdout routine, as Hydra data."""

from helpers import GOLDEN_IMAGE, encode


def test_startup_encodes_to_golden_prefix(project):
    d, rt = project.module("hydraos.riscv.dsl"), project.module("hydraos.riscv.runtime")
    assert encode(project, [*rt.startup(), d.label("main")]).value == GOLDEN_IMAGE[:28]


def test_write_stdout_routine_encodes_to_golden_slice(project):
    rt = project.module("hydraos.riscv.runtime")
    assert encode(project, list(rt.write_stdout_routine())).value == GOLDEN_IMAGE[44:88]

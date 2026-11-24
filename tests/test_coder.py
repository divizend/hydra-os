"""The RISC-V coder: hello compiles to the golden image; anything else is rejected by name."""

import hashlib

import pytest
from hydra.core.overlay.python.dsl.python import Left, Right

from helpers import GOLDEN_IMAGE, GOLDEN_SHA256


def test_hello_builds_the_golden_image(project):
    r = project.module("hydraos.riscv.coder").build_image(project.graph, project.modules["hydraos.hello"])
    assert isinstance(r, Right), r
    assert r.value == GOLDEN_IMAGE
    assert hashlib.sha256(r.value).hexdigest() == GOLDEN_SHA256


@pytest.mark.parametrize("namespace,message", [
    ("hydraos.unsupported.nomain", "hydraos.riscv.coder: module hydraos.unsupported.nomain has no term definition named main"),
    ("hydraos.unsupported.stderr", "hydraos.riscv.coder: unsupported in main: application of hydra.core.lib.system.writeStderr"),
    ("hydraos.unsupported.sequence", "hydraos.riscv.coder: unsupported in main: application of hydra.core.lib.effects.bind"),
    ("hydraos.unsupported.function", "hydraos.riscv.coder: unsupported in main: lambda"),
])
def test_unsupported_programs_are_rejected(project, namespace, message):
    r = project.module("hydraos.riscv.coder").compile_module(project.graph, project.modules[namespace])
    assert isinstance(r, Left) and r.value == message

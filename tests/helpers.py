"""Shared test helpers and constants (imported as `from helpers import ...`)."""

import subprocess
import sys

from launcher.pipeline import REPO_ROOT


def run_launcher(*args, cwd=REPO_ROOT, env=None):
    """Run `python -m launcher <args>` in a fresh process, capturing stdout and stderr as bytes."""
    return subprocess.run(
        [sys.executable, "-m", "launcher", *args], cwd=cwd, env=env, capture_output=True, timeout=600
    )


def program(model, items):
    """A `hydraos.riscv.model.Program` holding `items` in order."""
    from hydra.core.overlay.python.util.cons_list import ConsList

    return model.Program(ConsList.of(*items))


def encode(project, items):
    """Run the generated `hydraos.riscv.encode.encodeProgram` on `items`; returns its Left or Right."""
    model = project.module("hydraos.riscv.model")
    return project.module("hydraos.riscv.encode").encode_program(program(model, items))


OBJDUMP = "riscv64-linux-gnu-objdump"


def objdump(image: bytes) -> list[str]:
    """GNU objdump's reading of a raw RV64 image: one instruction text per line, comments stripped."""
    import re
    import shutil
    import tempfile

    import pytest

    tool = shutil.which(OBJDUMP)
    if tool is None:
        pytest.fail(f"{OBJDUMP} not found: apt-get install -y binutils-riscv64-linux-gnu")
    with tempfile.NamedTemporaryFile(suffix=".bin") as f:
        f.write(image)
        f.flush()
        out = subprocess.run(
            [tool, "-D", "-b", "binary", "-m", "riscv:rv64", "-M", "no-aliases,numeric", f.name],
            capture_output=True, text=True, check=True,
        ).stdout
    lines = []
    for line in out.splitlines():
        m = re.match(r"^\s*[0-9a-f]+:\s+[0-9a-f]+\s+(.*?)\s*(#.*)?$", line)
        if m:
            lines.append(m.group(1).replace("\t", " ").strip())
    return lines

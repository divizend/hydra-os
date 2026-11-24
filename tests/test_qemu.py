"""End to end: QEMU boots the image the launcher builds and prints the line."""

import shutil
import subprocess

import pytest

from helpers import run_launcher


def test_qemu_boots_the_image_and_prints_the_line(tmp_path):
    out = tmp_path / "hello.bin"
    assert run_launcher("build", "--out", str(out)).returncode == 0
    qemu = shutil.which("qemu-system-riscv64") or pytest.fail("qemu-system-riscv64 not found: apt-get install -y qemu-system-misc")
    r = subprocess.run([qemu, "-machine", "virt", "-bios", "none", "-nographic", "-kernel", str(out)],
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr.decode()
    assert r.stdout == b"Hello from Hydra\n"

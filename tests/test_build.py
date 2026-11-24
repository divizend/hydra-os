"""The build command: the committed image, determinism, and independence from the working directory."""

import os
import subprocess

from helpers import GOLDEN_IMAGE, run_launcher
from launcher.pipeline import REPO_ROOT


def test_build_writes_the_golden_image_every_time(tmp_path):
    for name in ("first.bin", "second.bin"):
        out = tmp_path / name
        r = run_launcher("build", "--out", str(out))
        assert r.returncode == 0, r.stderr.decode()
        assert out.read_bytes() == GOLDEN_IMAGE
        assert f"wrote {out} (105 bytes)" in r.stderr.decode()


def test_build_from_another_working_directory(tmp_path):
    out = tmp_path / "hello.bin"
    r = run_launcher("build", "--out", str(out), cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(REPO_ROOT)})
    assert r.returncode == 0, r.stderr.decode()
    assert out.read_bytes() == GOLDEN_IMAGE


def test_committed_image_is_the_golden_image():
    assert (REPO_ROOT / "out/hello.bin").read_bytes() == GOLDEN_IMAGE


def test_hello_bin_is_marked_binary_for_git():
    r = subprocess.run(["git", "check-attr", "binary", "--", "out/hello.bin"], cwd=REPO_ROOT, capture_output=True, text=True)
    assert r.stdout == "out/hello.bin: binary: set\n"


def test_build_reports_an_unwritable_out_path(tmp_path):
    r = run_launcher("build", "--out", str(tmp_path))  # an existing directory, not a file
    err = r.stderr.decode()
    assert r.returncode == 1
    assert "error: " in err
    assert "Traceback" not in err

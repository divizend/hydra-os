"""Shared test helpers and constants (imported as `from helpers import ...`)."""

import subprocess
import sys

from launcher.pipeline import REPO_ROOT


def run_launcher(*args, cwd=REPO_ROOT, env=None):
    """Run `python -m launcher <args>` in a fresh process, capturing stdout and stderr as bytes."""
    return subprocess.run(
        [sys.executable, "-m", "launcher", *args], cwd=cwd, env=env, capture_output=True, timeout=600
    )

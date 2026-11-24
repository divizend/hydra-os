"""The kernel program on Hydra's Python host, through the launcher CLI."""

from helpers import run_launcher


def test_hello_runs_on_the_python_host():
    r = run_launcher("run-hello")
    assert r.returncode == 0, r.stderr.decode()
    assert r.stdout == b"Hello from Hydra\n"


def test_cli_reports_hydra_error_without_traceback():
    r = run_launcher("run-hello", "--source-root", "tests/fixtures/broken")
    err = r.stderr.decode()
    assert r.returncode == 1
    assert "error: tests/fixtures/broken/broken.hydra: " in err
    assert "Traceback" not in err

"""The Hydra 0.18.1 pipeline: kernel loading, parsing, inference and Python generation."""

import importlib.metadata

import pytest

from launcher.pipeline import CACHE_DIR, HydraError, generate_python, load_kernel_modules, parse_sources


def test_probe_module_runs_on_python_host(project):
    assert project.module("hydraos.probe").double(21) == 42


def test_parse_error_names_file_and_position():
    kernel = load_kernel_modules()
    with pytest.raises(HydraError, match=r"^broken\.hydra: \d+:\d+: "):
        parse_sources(kernel, [("broken.hydra", "module hydraos.broken\n\nterm x =\n")])


def test_kernel_cache_file_is_named_after_installed_version(project):
    version = importlib.metadata.version("hydra-kernel")
    assert version == "0.18.1"
    assert (CACHE_DIR / f"hydra-kernel-{version}.pickle").is_file()


def test_generate_python_starts_from_clean_dir(project, tmp_path):
    stale = tmp_path / "hydraos" / "stale.py"
    stale.parent.mkdir(parents=True)
    stale.write_text("x = 1\n")
    written = generate_python(project.graph, project.kernel, [project.modules["hydraos.probe"]], tmp_path)
    assert not stale.exists()
    assert tmp_path / "hydraos" / "probe.py" in written

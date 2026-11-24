"""Shared fixtures: one Hydra pipeline run per test session."""

import pytest

from launcher.pipeline import REPO_ROOT, SOURCE_ROOT, load_project

FIXTURES = REPO_ROOT / "tests" / "fixtures"


@pytest.fixture(scope="session")
def project(tmp_path_factory):
    """Every module in src/main/hydra and tests/fixtures/hydra, parsed, inferred and generated to Python."""
    return load_project(
        source_roots=(SOURCE_ROOT, FIXTURES / "hydra"),
        generated_dir=tmp_path_factory.mktemp("generated"),
    )

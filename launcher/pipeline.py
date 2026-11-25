"""Run Hydra 0.18.1's published pipeline over this repo's `.hydra` sources.

This is host glue, the role a Hydra `heads/` driver plays: it calls Hydra's own published functions
in order (load the kernel, parse, infer, generate Python) and holds no project logic.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.resources
import json
import os
import pickle
import shutil
import sys
import tempfile
import types
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Sequence

# Decoding the kernel's JSON recurses deeply; Hydra's own Python head sets the same limit.
sys.setrecursionlimit(10000)

import hydra.core.decode.packaging as decode_packaging  # noqa: E402
import hydra.core.json.decode as json_decode  # noqa: E402
from hydra.core.bootstrap import types_by_name  # noqa: E402
from hydra.core.codegen import generate_source_files, infer_modules_given, modules_to_graph  # noqa: E402
from hydra.core.graph import Graph  # noqa: E402
from hydra.core.json import model as json_model  # noqa: E402
from hydra.core.lexical import empty_inference_context  # noqa: E402
from hydra.core.model import Name, TypeVariable  # noqa: E402
from hydra.core.overlay.python.dsl.python import FrozenDict, Left  # noqa: E402
from hydra.core.overlay.python.util.cons_list import ConsList  # noqa: E402
from hydra.core.overlay.python.sources.libraries import standard_library  # noqa: E402
from hydra.core.packaging import Module  # noqa: E402
from hydra.core.parse.packaging import parse_modules  # noqa: E402
from hydra.core.print.errors import error as print_error  # noqa: E402
from hydra.core.scoping import f_type_to_type_scheme  # noqa: E402
from hydra.core.strip import deannotate_type_recursive  # noqa: E402
from hydra.python.coder import module_to_python  # noqa: E402
from hydra.python.language import python_language  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "src" / "main" / "hydra"
GENERATED_DIR = REPO_ROOT / "build" / "python"
CACHE_DIR = REPO_ROOT / "build" / "cache"

_MODULE_TYPE = Name("hydra.core.packaging.Module")


class HydraError(Exception):
    """A Hydra step returned `left`; the message is Hydra's own text."""


def bootstrap_graph() -> Graph:
    """An empty graph holding only the Python host's primitives."""
    return Graph(
        bound_terms=FrozenDict({}),
        bound_types=FrozenDict({}),
        class_constraints=FrozenDict({}),
        lambda_variables=frozenset(),
        metadata=FrozenDict({}),
        primitives=FrozenDict(standard_library()),
        schema_types=FrozenDict({}),
        type_variables=frozenset(),
    )


def load_kernel_modules(cache_dir: Path = CACHE_DIR) -> list[Module]:
    """Hydra's kernel modules, decoded from the JSON bundled with hydra-kernel.

    Decoding takes about a minute, so the result is cached in a pickle named after the installed
    hydra-kernel version. A cache file that fails to load is rebuilt: the rebuild yields the same
    modules, so nothing is hidden by it.
    """
    version = importlib.metadata.version("hydra-kernel")
    cache = Path(cache_dir) / f"hydra-kernel-{version}.pickle"
    if cache.is_file():
        try:
            with cache.open("rb") as f:
                return pickle.load(f)
        except Exception:  # truncated or unreadable cache: rebuild below
            pass
    modules = _decode_bundled_kernel()
    cache.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=cache.parent, prefix=cache.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            pickle.dump(modules, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(temp, cache)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
    return modules


def _decode_bundled_kernel() -> list[Module]:
    root = Path(str(importlib.resources.files("hydra") / "hydra_kernel_json"))
    schema_map = FrozenDict(
        {name: deannotate_type_recursive(f_type_to_type_scheme(t).body) for name, t in types_by_name.items()}
    )
    graph = bootstrap_graph()
    modules = []
    for path in sorted(root.glob("hydra/**/*.json")):
        with path.open(encoding="utf-8") as f:
            value = _to_hydra_json(json.load(f, parse_float=Decimal))
        term = json_decode.from_json(schema_map, False, _MODULE_TYPE, TypeVariable(_MODULE_TYPE), value)
        if isinstance(term, Left):
            raise HydraError(f"{path}: {term.value}")
        module = decode_packaging.module(graph, term.value)
        if isinstance(module, Left):
            raise HydraError(f"{path}: {module.value}")
        modules.append(module.value)
    return modules


def _to_hydra_json(value) -> json_model.Value:
    if value is None:
        return json_model.ValueNull()
    if isinstance(value, bool):
        return json_model.ValueBoolean(value)
    if isinstance(value, Decimal):
        return json_model.ValueNumber(value)
    if isinstance(value, int):
        return json_model.ValueNumber(Decimal(value))
    if isinstance(value, str):
        return json_model.ValueString(value)
    if isinstance(value, list):
        return json_model.ValueArray(tuple(_to_hydra_json(v) for v in value))
    if isinstance(value, dict):
        return json_model.ValueObject(tuple((k, _to_hydra_json(v)) for k, v in value.items()))
    raise TypeError(f"unexpected JSON value of type {type(value).__name__}")


def find_sources(root: Path) -> list[tuple[str, str]]:
    """Every `.hydra` file under `root`, sorted, as (display path, text)."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"source root not found: {root}")
    return [(_display_path(p), p.read_text(encoding="utf-8")) for p in sorted(root.rglob("*.hydra"))]


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def parse_sources(kernel: Sequence[Module], sources: Sequence[tuple[str, str]]) -> list[Module]:
    """Parse `.hydra` texts into modules, resolving names against the kernel."""
    result = parse_modules(list(kernel), list(sources))
    if isinstance(result, Left):
        raise HydraError(result.value)
    return list(result.value)


def kernel_graph(kernel: Sequence[Module]) -> Graph:
    """The bootstrap graph with the given kernel modules folded in."""
    return modules_to_graph(bootstrap_graph(), list(kernel), list(kernel))


def infer(graph: Graph, kernel: Sequence[Module], modules: Sequence[Module]) -> list[Module]:
    """Type-check our modules together, with the kernel in scope."""
    result = infer_modules_given(empty_inference_context(), graph, list(kernel) + list(modules), list(modules))
    if isinstance(result, Left):
        raise HydraError(print_error(result.value))
    return list(result.value)


def dependency_closure(modules: Sequence[Module], kernel: Sequence[Module]) -> list[Module]:
    """The kernel modules our modules depend on, directly or transitively."""
    by_name = {m.name: m for m in kernel}
    closure: dict = {}
    pending = list(modules)
    while pending:
        for dependency in pending.pop().dependencies:
            target = by_name.get(dependency.module)
            if target is not None and target.name not in closure:
                closure[target.name] = target
                pending.append(target)
    return list(closure.values())


def generate_python(
    graph: Graph, kernel: Sequence[Module], inferred: Sequence[Module], out_dir: Path = GENERATED_DIR
) -> list[Path]:
    """Generate Python for `inferred` into a freshly emptied `out_dir`; return the written files.

    The universe is only the kernel modules ours depend on: with the whole kernel it is the same
    output, but generation takes minutes instead of a fraction of a second.
    """
    out_dir = Path(out_dir)
    subs = _overlay_lib_subs()
    universe = dependency_closure(inferred, kernel) + list(inferred)
    result = generate_source_files(
        lambda mod, defs, cx, g: module_to_python(subs, mod, defs, cx, g),
        python_language(),
        False,
        graph,
        universe,
        list(inferred),
        empty_inference_context(),
    )
    if isinstance(result, Left):
        raise HydraError(print_error(result.value))
    if out_dir.exists():
        shutil.rmtree(out_dir)
    written = []
    for relative, content in result.value:
        target = out_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(target)
    return written


def _overlay_lib_subs() -> frozenset[str]:
    """The `hydra.core.lib.<sub>` namespaces with a native Python implementation installed."""
    lib = Path(str(importlib.resources.files("hydra") / "core" / "overlay" / "python" / "lib"))
    return frozenset(p.stem for p in lib.glob("*.py") if p.stem not in ("__init__", "libraries"))


@dataclass
class Project:
    """Our modules, inferred, with the Python generated from them and the text each was parsed from."""

    graph: Graph
    kernel: list[Module]
    modules: dict[str, Module]
    generated_dir: Path
    texts: dict[str, tuple[str, str]]  # module name -> (display path, text)

    def sources(self) -> ConsList:
        """Our modules as the list of sources the coder reads its program from."""
        return ConsList.of(*self.modules.values())

    def module(self, namespace: str) -> types.ModuleType:
        """Import the Python generated for a Hydra module, e.g. `hydraos.hello`."""
        path = str(self.generated_dir)
        if path not in sys.path:
            sys.path.insert(0, path)
            importlib.invalidate_caches()
        return importlib.import_module(namespace)


def load_project(
    source_roots: Sequence[Path] = (SOURCE_ROOT,),
    generated_dir: Path = GENERATED_DIR,
    cache_dir: Path = CACHE_DIR,
) -> Project:
    """Load the kernel, then parse, infer and generate Python for every module under `source_roots`.

    Inference and generation see only the kernel modules ours depend on. With the whole kernel in
    scope, Hydra's Python-host inference takes about 14 s for twenty one-line definitions; with the
    dependency closure it is near-instant, and the result is the same.
    """
    kernel = load_kernel_modules(cache_dir)
    sources = [source for root in source_roots for source in find_sources(root)]
    parsed = parse_sources(kernel, sources)
    in_scope = dependency_closure(parsed, kernel)
    graph = kernel_graph(in_scope)
    inferred = infer(graph, in_scope, parsed)
    generate_python(graph, in_scope, inferred, generated_dir)
    texts = {m.name.value: source for source, m in zip(sources, parsed, strict=True)}  # parse_modules keeps the order
    return Project(graph, kernel, {m.name.value: m for m in inferred}, Path(generated_dir), texts)

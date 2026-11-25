"""The derivation record as JSON: a plain rendering of the Hydra values the coder and the encoder produce
(hydraos.riscv.derivation): the image's digest, its coverage, where each item of the program was written,
and every atom, with every source place resolved to the text it names.

A source place is a definition, a hydra.core.paths.SubtermPath inside its body and, inside a string
literal, a character. It is resolved with Hydra's own parser: the definition is found by its header
(`term <name>` at the start of a line), its optional signature, `=` and body are read with Hydra's parsers,
the body with spans (hydra.core.parse.core.term), the path is followed step by step
(hydra.core.positions.subtermAtStep), and a character is found by Hydra's string escape grammar
(hydra.core.parse.core.escapedChar). Lines and columns count from 1, columns in UTF-16 code units
(hydra.core.positions.offsetToPosition); an end is exclusive. A span links to its lines on GitHub at the
commit that last changed its file, when the file is committed as it is.

This module computes no provenance: it only renders what the Hydra code recorded.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from functools import cache
from pathlib import Path

from hydra.core import parsers
from hydra.core.overlay.python.dsl.python import Given, Node, None_
from hydra.core.parse.core import escaped_char, term, term_signature, whitespace
from hydra.core.parse.packaging import keyword
from hydra.core.parsing import ParseResultSuccess
from hydra.core.paths import SubtermPath
from hydra.core.positions import offset_to_position, peel_spans, subterm_at_step, term_span
from hydra.core.print.paths import subterm_path

from launcher.pipeline import REPO_ROOT, HydraError

Texts = Mapping[str, tuple[str, str]]  # module name -> (file, text)

# One character of a string literal's content, read as Hydra's stringLit reads it: an escape sequence, or
# any character but a quote or a backslash.
STRING_CHARACTER = parsers.alt(parsers.try_(escaped_char()), parsers.satisfy(lambda c: c != 34 and c != 92))

# What follows a term definition's name, read as Hydra's termDefinitionParser reads it: an optional
# signature, `=`, then the body, here with its spans.
DEFINITION_BODY = parsers.bind(
    whitespace(),
    lambda _: parsers.bind(
        parsers.optional(parsers.bind(keyword(":"), lambda _: term_signature())),
        lambda _: parsers.bind(keyword("="), lambda _: term()),
    ),
)


def record_json(traced, texts: Texts, link: Callable[[str], str | None] | None = None) -> dict:
    """The record of a traced build (a hydraos.riscv.derivation.Traced): the image's size and digest, its
    coverage, where each item of the program was written, and every atom, each source place with the span
    of text it names."""
    derivation = sys.modules[type(traced).__module__]
    resolve = Resolver(texts, link or github_link(REPO_ROOT))
    image = bytes(traced.image)

    def item(i) -> dict:
        out = plain(derivation, i)
        if isinstance(i.place, Given):
            out["place"]["span"] = resolve(i.place.value)
        return out

    def atom(a) -> dict:
        out = plain(derivation, a)
        if isinstance(a.place, derivation.PlaceSource):
            out["place"]["source"]["span"] = resolve(a.place.value)
        return out

    return {
        "image": {"bytes": len(image), "sha256": hashlib.sha256(image).hexdigest()},
        "coverage": plain(derivation, traced.coverage),
        "items": [item(i) for i in traced.items],
        "atoms": [atom(a) for a in traced.derivation.value],
    }


def dumps(record: dict) -> str:
    """The record as JSON text, one item or atom per line."""
    lines = []
    for k, v in record.items():
        if isinstance(v, list):
            entries = ",\n".join(f"    {json.dumps(e, ensure_ascii=False)}" for e in v)
            lines.append(f"  {json.dumps(k)}: [\n{entries}\n  ]")
        else:
            lines.append(f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}")
    return "{\n" + ",\n".join(lines) + "\n}\n"


def plain(derivation, x):
    """A value of hydraos.riscv.derivation's types as JSON, under Hydra's own names: a record as an
    object, a wrapper as its content, a union value as {variant: content}, an optional as its value or
    null, a list as an array, and a SubtermPath as Hydra prints it."""
    if x is None or isinstance(x, (bool, int, str)):
        return x
    if isinstance(x, Given):
        return plain(derivation, x.value)
    if isinstance(x, None_):
        return None
    if isinstance(x, SubtermPath):
        return subterm_path(x)
    name = type(x).__name__
    for union in (derivation.Place, derivation.Formula, derivation.Value):
        if name.startswith(union.__name__) and name != union.__name__:  # a variant class, such as FormulaCopy
            variant = getattr(union, re.sub(r"(?<!^)(?=[A-Z])", "_", name[len(union.__name__):]).upper()).value
            return {variant: plain(derivation, getattr(x, "value", None))}
    if isinstance(x, Node):  # a wrapper, such as AtomId
        return plain(derivation, x.value)
    if dataclasses.is_dataclass(x):
        return {getattr(type(x), f.name.upper()).value: plain(derivation, getattr(x, f.name)) for f in dataclasses.fields(x)}
    if isinstance(x, Sequence):
        return [plain(derivation, e) for e in x]
    raise TypeError(f"no JSON rendering for {type(x).__name__}")


class Resolver:
    """Resolves source places to spans, parsing each definition's body once."""

    def __init__(self, texts: Texts, link: Callable[[str], str | None]):
        self.texts, self.link = texts, link
        self.bodies: dict[str, tuple[str, str, int, object]] = {}
        self.literals: dict[tuple[str, int, int], list[tuple[int, int]]] = {}

    def __call__(self, place) -> dict:
        file, text, offset, node = self.body(place.definition)
        where = f"{place.definition}#{subterm_path(place.path)}"
        for step in place.path.value:
            child = subterm_at_step(step, peel_spans(node))
            if not isinstance(child, Given):
                raise HydraError(f"record: no subterm at {where}")
            node = child.value
        span = term_span(node)
        if not isinstance(span, Given):
            raise HydraError(f"record: the subterm at {where} has no source span")
        start, end = offset + span.value.start, offset + span.value.end
        if isinstance(place.character, Given):
            characters = self.characters(text, start, end, where)
            if not 0 <= place.character.value < len(characters):
                raise HydraError(f"record: the string literal at {where} has no character {place.character.value}")
            start, end = characters[place.character.value]
        return _span(file, text, start, end, self.link(file))

    def body(self, definition: str) -> tuple[str, str, int, object]:
        """The file and text holding a definition, where its body starts, and the body parsed with spans."""
        if definition not in self.bodies:
            module, _, local = definition.rpartition(".")
            if module not in self.texts:
                raise HydraError(f"record: no source text for module {module}")
            file, text = self.texts[module]
            found = re.search(rf"^term\s+{re.escape(local)}(?![\w'])", text, re.MULTILINE)
            if found is None:
                raise HydraError(f"record: {file} has no term definition {local}")
            parsed = parsers.run_parser(DEFINITION_BODY, text[found.end():])
            if not isinstance(parsed, ParseResultSuccess):
                raise HydraError(f"record: the definition of {definition} does not parse: {parsed.value.message}")
            self.bodies[definition] = (file, text, found.end(), parsed.value.value)
        return self.bodies[definition]

    def characters(self, text: str, start: int, end: int, where: str) -> list[tuple[int, int]]:
        """Where each character of the string literal text[start:end] is written, by Hydra's escape grammar."""
        key = (where, start, end)
        if key not in self.literals:
            if text[start] != '"' or text[end - 1] != '"':
                raise HydraError(f"record: the subterm at {where} is not a string literal")
            found, at = [], start + 1
            while at < end - 1:
                r = parsers.run_parser(STRING_CHARACTER, text[at:end - 1])
                if not isinstance(r, ParseResultSuccess):
                    raise HydraError(f"record: the string literal at {where} does not parse at offset {at}")
                found.append((at, at + r.value.remainder.offset))
                at += r.value.remainder.offset
            self.literals[key] = found
        return self.literals[key]


def _span(file: str, text: str, start: int, end: int, url: str | None) -> dict:
    s, e = offset_to_position(text, start), offset_to_position(text, end)
    line, end_line = s.line + 1, e.line + 1
    anchor = f"#L{line}" if line == end_line else f"#L{line}-L{end_line}"
    return {
        "file": file,
        "line": line,
        "column": s.column + 1,
        "endLine": end_line,
        "endColumn": e.column + 1,
        "text": text[start:end],
        "url": url + anchor if url else None,
    }


def github_link(repo_root: Path) -> Callable[[str], str | None]:
    """The GitHub URL of a repository file at the commit that last changed it, or None when the file is not
    committed as it is, lies outside the repository, or the repository has no GitHub remote."""

    def git(*args: str) -> str | None:
        r = subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None

    remote = git("remote", "get-url", "origin") or ""
    found = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([^/]+)/(.+?)(?:\.git)?", remote)
    base = f"https://github.com/{found[1]}/{found[2]}" if found else None

    @cache
    def link(file: str) -> str | None:
        if base is None or Path(file).is_absolute():
            return None
        if git("status", "--porcelain", "--", file) != "":
            return None  # changed since its last commit, or not committed at all
        commit = git("log", "-1", "--format=%H", "--", file)
        return f"{base}/blob/{commit}/{file}" if commit else None

    return link

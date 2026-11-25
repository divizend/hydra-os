# Derivation Record Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The build writes `out/hello.derivation.json`, a record that explains every bit of `out/hello.bin`, and a check proves the record predicts real rebuilds.

**Architecture:** New Hydra types (`hydraos.riscv.derivation`) and an evaluator (`hydraos.riscv.derive`). The encoder derives every field as an atom and assembles the image from atoms. The coder traces the message and each item's operands by reading source terms, cross-checked against the evaluated program. The Python launcher only serializes, resolves places to spans with Hydra's span parser, and runs the mutation check.

**Tech Stack:** Hydra 0.18.1 (`.hydra`, Python host), Python 3.13, pytest.

**Spec:** `docs/superpowers/specs/2026-11-25-derivation-record-design.md`

## Global Constraints

- The image stays byte-identical to `GOLDEN_IMAGE` (sha256 `b6b66453…f59f`); every existing test keeps passing unchanged.
- Error messages of the encoder and coder stay exactly as the existing tests assert.
- Hydra 0.18.1 rules: no module mixes type and term definitions; unions take a plain `#` comment, never `##`; write `λx:T. body` with a space after the dot; a wrapper around a variable is `wrap(T){x}`.
- The launcher knows nothing about RISC-V and never computes provenance itself.
- Every memory-uncertain run goes through `/work/bin/run-capped.sh`.

## Review Focus

- A source place that resolves to the wrong text (a path built on the inferred term that differs from the parsed one) → Task 4 test: every source atom's span denotes its value.
- The `\n` escape at the end of the message → Task 4 test: character 16 resolves to the two characters `\n`.
- Negative immediates (`addi a1 a1 -1`) through `bits` → Task 1 test: `bits` of −1 gives all ones; Task 5's run flips its bits.
- Modules built without sources (`indirect`, `computed` fixtures) → existing `test_coder.py` tests stay green on the traced path.
- A mutated character that must be escaped (`"`, `\`, a control character) → Task 5 test: rendering uses Hydra's `escape_string_char`.

---

### Task 1: Derivation types and evaluator

**Files:**
- Create: `src/main/hydra/hydraos/riscv/derivation.hydra` (types only)
- Create: `src/main/hydra/hydraos/riscv/derive.hydra` (terms)
- Test: `tests/test_derive.py`

**Interfaces:**
- Produces (types): `AtomId = wrap(string)`; `Value = union{number: bigint, name: string}`; `SourcePlace{definition: string, path: hydra.core.paths.SubtermPath, character: optional<int32>}`; `ImagePlace{offset, lo, width: int32}`; `Place = union{source, intermediate: string, image}`; `Operands{left, right: AtomId}`; `BitsOf{atom: AtomId, lo, width: int32}`; `Utf8Byte{atom: AtomId, index: int32}`; `Formula = union{given: unit, copy: AtomId, sum: list<AtomId>, difference, product, quotient: Operands, bits: BitsOf, count: list<AtomId>, utf8: Utf8Byte, labelOffset: AtomId}`; `Rule{definition, detail: string}`; `Atom{id, place, value, formula, rule}`; `Derivation = wrap(list<Atom>)`; `OperandAtom{role: string, atom: AtomId}`; `ItemTrace{place: optional<SourcePlace>, operands: list<OperandAtom>}`; `TracedProgram{program: Program, items: list<ItemTrace>, atoms: list<Atom>}`; `Coverage{bits, sourceBits, atoms: int32}`; `Traced{image: binary, derivation: Derivation, coverage: Coverage}`.
- Produces (terms, generated Python in snake_case): `evaluate(values: map<string, Value>, f: Formula) -> either<string, Value>`; `derived(values, id: string, place, formula, rule) -> either<string, Atom>` (value computed by `evaluate`); `assemble(atoms: list<Atom>) -> either<string, binary>`; `predict(d: Derivation, id: AtomId, v: Value) -> either<string, binary>`; `coverage(d: Derivation) -> Coverage`. `labelOffset a` reads the atom `"label/" ++ name(a)`.

- [ ] **Step 1: Write failing tests** in `tests/test_derive.py`, building atoms with the generated dataclasses:
  - `evaluate` of `bits(−1, 0, 12)` is 4095; of `bits(36, 1, 4)` is 2; `quotient(−1, 4096)` is −1 (floor); `utf8(0xFC, 1)` is 0xBC; `count` of 17 atoms is 17; `labelOffset` of a name atom `"main"` reads `label/main`.
  - `assemble` of the four field atoms of `beq a1, zero, +36` at offset 0 gives `63 82 05 02`; one byte atom at offset 4 appends one byte; a gap (fields covering 31 bits) is a Left naming the offset; an overlap is a Left.
  - `predict` with one data-byte source atom changed from `0x48` to `0x49` changes exactly that byte.
  - `coverage` counts bits and the bits whose given ancestors all have source places.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_derive.py` fails (modules missing).
- [ ] **Step 3:** Write both modules. `assemble` groups image atoms by offset, requires the fields of each unit to tile 0..32 or 0..8 bits, the units to tile 0..size, and packs words little-endian; bytes go to `binary` through the existing base64 path (move `base64` and `wordBytes` here from `encode.hydra` and import them there).
- [ ] **Step 4:** The tests pass; `tests/test_encode.py` still passes.
- [ ] **Step 5:** Commit "Add the derivation record's types and its evaluator".

### Task 2: The encoder derives every field

**Files:**
- Modify: `src/main/hydra/hydraos/riscv/model.hydra` (types `Encoding{mnemonic: string, opcode: int32, fixed: list<FixedField>}`, `FixedField{field: string, value: int32}`)
- Modify: `src/main/hydra/hydraos/riscv/encode.hydra`
- Test: `tests/test_encode.py`, `tests/test_trace.py` (new)

**Interfaces:**
- Consumes: Task 1.
- Produces: `encodings: list<Encoding>` (one entry per emitted mnemonic, `la.auipc` and `la.addi` for `la`; `wfi` as I-type SYSTEM: opcode 115, funct12 261, rs1 0, funct3 0, rd 0); `instructionSize = 4`, `loadAddressSize = 8`, `labelSize = 0` (int32); `pageSize = 4096`, `pageHalf = 2048` (bigint); `encodeTraced(tp: TracedProgram) -> either<string, Traced>`; `untraced(p: Program) -> TracedProgram` (operand atoms given, placed `intermediate "item k role"`); `encodeProgram(p) = map image (encodeTraced (untraced p))`.
- Atom ids: `item/<k>/<role>`, `size/<k>`, `pc/<k>`, `label/<name>`, `word/<offset>/<part>` for offsets and `la` halves, `image/<offset>/<field>`, constants `encode/<definition-local-name>/...`.

- [ ] **Step 1: Failing tests** in `tests/test_trace.py`: `encode_traced(untraced(golden program))` gives `GOLDEN_IMAGE` and coverage `bits == 840`; an `Encoding` with opcode 147 is rejected with `"addi: opcode 147 out of range [0, 127]"`; an encoding whose length disagrees with `itemSize` is rejected with `"item 3: encoded 4 bytes, recorded size 5"`.
- [ ] **Step 2:** They fail.
- [ ] **Step 3:** Rewrite field construction per format as lists of image atoms whose formulas are `copy` (registers, table constants) or `bits` (immediates and offsets), with the existing range and alignment checks applied to evaluated values, in the existing order. Layout atoms use `sum` over sizes. Every constant atom is placed at its `SubtermPath` inside its definition (`listElement`, `recordField`).
- [ ] **Step 4:** `tests/test_encode.py`, `tests/test_runtime.py`, `tests/test_coder.py` and the new tests pass.
- [ ] **Step 5:** Commit "Derive every field of the image as an atom".

### Task 3: The coder traces where everything came from

**Files:**
- Create: `src/main/hydra/hydraos/riscv/sources.hydra` (terms: find a definition among modules; walk an item list's terms with `SubtermPath`s; read a DSL call's arguments and the parameter each one fills)
- Modify: `src/main/hydra/hydraos/riscv/coder.hydra`
- Test: `tests/test_trace.py`

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: `traceProgram(g, m, sources: list<Module>) -> either<string, TracedProgram>`; `buildTraced(g, m, sources) -> either<string, Traced>`; `buildImage(g, m) = map image (buildTraced g m [])`.
- Atom ids: `<module>.<def>/char/<i>` (source characters), `message/<k>`, `message/length`, `source/<definition>#<path>` (call-site and dsl atoms).

- [ ] **Step 1: Failing tests:** `build_traced(graph, hello, all modules)` gives `GOLDEN_IMAGE`, coverage `bits == 840 == sourceBits`; byte 0x31's three image atoms reach `source/hydraos.riscv.dsl.a1#wrapBody`, the BEQ funct3 entry of `encodings`, and `label/writeStdout.done` minus `pc/<k>`; byte 0x58 reaches `hydraos.hello.main/char/0` through `utf8`; without sources `indirect` and `computed` still give `GOLDEN_IMAGE`.
- [ ] **Step 2:** They fail.
- [ ] **Step 3:** Implement. Message: `encodeUtf8` of a string literal, through same-module definitions, is traced per character; anything else gives one given atom per byte, placed on the argument term. Items: walk `mainProgram`'s concatenated lists, expanding `startup` and `writeStdoutRoutine` from their definitions; registers copy the literal in their dsl definition; `lists.length (literals.binaryToBytes bytes)` is `count` of the message bytes; any other argument form is a Left naming it. Compare every traced value with `compileModule`'s program; a difference is a Left naming the item.
- [ ] **Step 4:** All tests pass.
- [ ] **Step 5:** Commit "Trace the message and every operand to its source".

### Task 4: The launcher writes the record

**Files:**
- Modify: `launcher/__main__.py`, `launcher/pipeline.py` (graph and modules handed to the coder)
- Create: `launcher/record.py` (`record_json(traced, sources) -> dict`, `resolve_place(place, texts) -> dict` using `parse_term_with_spans` and `span_at_path`, character spans by Hydra's escape grammar)
- Test: `tests/test_record.py`; `out/hello.derivation.json` committed

**Interfaces:**
- Consumes: Task 3's `build_traced`.
- Produces: `build` writes the image and `<out stem>.derivation.json`, prints `derivation: 840 of 840 bits explained, 840 traced to source, <n> atoms`; new option `--generated-dir`.

- [ ] **Step 1: Failing tests:** every source atom's resolved text denotes its value (an int32 literal parses to it, a string literal is the name, a register variable names a dsl definition whose literal is the value, character 16 is `\n`); a fresh build's JSON equals the committed file; the printed line is as above.
- [ ] **Step 2:** They fail.
- [ ] **Step 3:** Implement; the JSON is a plain rendering of the Hydra values plus a `span` (file, line, column, text, GitHub URL at the commit) on every source place.
- [ ] **Step 4:** Tests pass; `python -m launcher build` regenerates both outputs; `git diff out/hello.bin` is empty.
- [ ] **Step 5:** Commit "Write the derivation record beside the image".

### Task 5: The mutation check

**Files:**
- Create: `launcher/check.py`; command `check-derivation [--jobs N] [--report PATH]` in `launcher/__main__.py`
- Test: `tests/test_check.py` (mutation planning and rendering only, no rebuilds)
- Create: `docs/evidence/2026-11-25-derivation-check.txt` (the full run's report)

**Interfaces:**
- Consumes: Task 4's record and spans; Task 1's `predict`.
- Produces: per-mutation result `matched | rejected(error) | mismatched(bits)`; exit status 1 on any mismatch.

- [ ] **Step 1: Failing tests:** the plan for the hello record lists 119 character flips (17 × 7); a flip of `"` renders as `\"` and of a control character as `\u00XX`; a register flip to an undefined number adds `term x4 = Register{4:int32}` to the copied dsl.hydra; a label mutation lists the six other labels.
- [ ] **Step 2:** They fail.
- [ ] **Step 3:** Implement; each mutation copies the sources, builds with `python -m launcher build --source-root … --out … --generated-dir …` in a fresh process, and compares with `predict`. Run with 8 workers under `run-capped.sh`.
- [ ] **Step 4:** Unit tests pass; the full run reports 0 mismatched; commit the report.
- [ ] **Step 5:** Commit "Check that the record predicts every rebuild".

### Task 6: Document, clean up, ship

- [ ] README: a section on the record, the coverage line and the check, with links to the committed JSON and report.
- [ ] Delete `/work/hydra-os-viz/gen/`.
- [ ] Full test suite once (the change is cross-cutting); merge to `main`; push; confirm the files on GitHub.

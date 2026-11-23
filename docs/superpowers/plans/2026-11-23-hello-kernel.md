# Hello Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Hydra program, `hydraos.hello`, that prints `Hello from Hydra` both on Hydra's Python host and as a 105-byte bare-metal RISC-V image that QEMU boots. Every byte of the image is computed by Hydra code.

**Architecture:** Five `.hydra` modules form a minimal RISC-V host:
- `model`: the syntax model;
- `dsl`: registers and item constructors;
- `encode`: the serializer;
- `runtime`: start-up and `writeStdout` as data;
- `coder`.

A thin Python launcher runs Hydra 0.18.1's published pipeline (parse → infer → generate Python), imports the generated coder, and calls it on the inferred `hydraos.hello` module.

**Tech Stack:** Hydra 0.18.1 (`hydra-kernel`, `hydra-python` from PyPI), Python 3.13, pytest, QEMU 7.2 (`qemu-system-riscv64`), GNU binutils (test oracle only).

**Spec:** `docs/superpowers/specs/2026-11-23-hello-kernel-design.md`

## Global Constraints

- Pin `hydra-kernel==0.18.1`, `hydra-python==0.18.1`, `pytest==9.2.0` in `requirements.txt`.
  Python ≥ 3.12; on the box: `/work/toolchain/uv-python/cpython-3.13.18-linux-x86_64-gnu/bin/python3`.
- Don't build Hydra from source, track its `main`, file upstream issues, or change `CategoricalData/hydra`.
- Every byte of `out/hello.bin` comes from Hydra code.
  No assembler, linker or C compiler in the build, and no hand-written assembly files in the repo.
- The launcher (`launcher/`) only orchestrates Hydra calls: no RISC-V knowledge, no project logic.
- `hydraos.hello` contains nothing RISC-V-specific.
- An unsupported construct is an error naming the construct; never emit an image or a warning instead.
- If Hydra's Python coder fails on one of our constructs, restructure our `.hydra` source.
  If that isn't possible, stop and report it with evidence.
  Never patch generated code or work around it in the launcher.
- Machine: RV64I on QEMU `virt` with `-bios none`; the raw image loads at `0x8000_0000`.
  UART0 is an NS16550A at `0x1000_0000` (THR at offset 0; LSR at offset 5; THRE = bit 5 = `0x20`).
  The test device is at `0x0010_0000`; storing `0x5555` exits QEMU with status 0.
- Message: `Hello from Hydra\n` (17 bytes), sent unchanged, with no newline translation.
- Run command: `qemu-system-riscv64 -machine virt -bios none -nographic -kernel out/hello.bin`.
- Work on branch `increment-1-hello-kernel` in `/work/hydra-os`. This box forbids git worktrees.
- Box rules:
  - Install the box packages with `apt-get install -y qemu-system-misc binutils-riscv64-linux-gnu`.
    They live on the ephemeral overlay, so re-run that after a pod restart.
  - Run the first cold kernel load under `/work/bin/run-capped.sh 8192 900 …`.
  - Quote pytest's own summary line (`N passed`) as evidence, never an exit code through a filter.
- Every commit message ends with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Stale generated code.**
   A module deleted or renamed in `src/` must not stay importable from an earlier build.
   `generate_python` starts from an empty directory (test in Task 1).
2. **Readable Hydra errors.**
   A `.hydra` syntax error surfaces as `path: line:col: message`.
   The CLI prints it as `error: …` with exit status 1 and no Python traceback (tests in Tasks 1 and 2).
3. **Kernel cache tied to the installed Hydra.**
   The cache file is named after the installed `hydra-kernel` version, so an upgrade can't load stale modules (test in Task 1).
4. **Working directory.**
   `python -m launcher build` from any working directory still reads the repo's `src/main/hydra` (test in Task 6).
5. **Windows git.**
   `out/hello.bin` is marked `binary` in `.gitattributes`, so `core.autocrlf` on Windows can't rewrite its `0x0a` byte (test in Task 6).

## Verified while planning

These were checked on the box on 2026-11-23 with throwaway probes; nothing from them is committed.

- **The pipeline works on published 0.18.1:** parse → infer → generate Python → import → run.
  The generated `hydraos.hello` is `@lru_cache(1) def main() -> Either[SystemError, None]`, calling `write_stdout(encode_utf8("Hello from Hydra\n"))`.
- **Cost:**
  - Decoding the bundled kernel JSON (272 modules) takes about 66 s, with a peak RSS around 600 MiB.
  - A pickle of the decoded modules is 22 MB and loads in about 4 s.
  - Inference takes under 1 s.
  - Generation takes about 0.2 s if its universe is only our modules' kernel dependency closure, and 2 min if it is the whole kernel.
- **Call shapes:**
  - `json_decode.from_json(schema_map, False, Name("hydra.core.packaging.Module"), TypeVariable(Name("hydra.core.packaging.Module")), value)`
  - `hydra.core.decode.packaging.module(bootstrap_graph, term)`
  - `parse_modules(kernel, [(path, text)])` returns `Either[str, …]`.
  - `infer_modules_given(empty_inference_context(), graph, kernel + mine, mine)`
  - `generate_source_files(lambda m, d, cx, g: module_to_python(subs, m, d, cx, g), python_language(), False, graph, closure + inferred, inferred, cx)`
  - Errors print with `hydra.core.print.errors.error(err)`.
  - `subs` is the set of `.py` file stems in the installed `hydra/core/overlay/python/lib/`, minus `__init__` and `libraries`.
  - Decoding needs `sys.setrecursionlimit(10000)`, as Hydra's own Python head sets.
- **`.hydra` pitfalls found on 0.18.1:**
  1. Don't mix `type` and `term` definitions in one module.
     The Python coder emits two file headers into one file, giving `SyntaxError: from __future__ imports must occur at the beginning of the file`.
     Hydra's own kernel keeps them apart too.
  2. Write `λp:Program. length …` with a space after the dot.
     Otherwise the dotted name is read greedily as a qualified name.
  3. A qualified reference such as `lists.head` needs `import hydra.core.lib.lists as lists`.
     Without an alias, use the bare name (only when unambiguous).
  4. A wrapper around a *variable* needs the keyword form: `wrap(hydraos.riscv.model.Label){name}`, because `Label{name}` reads as a record.
  5. Integer literals need width suffixes (`17:int32`, `4096:bigint`).
  6. Don't rely on operator sugar (`+`, `|>`) or destructuring; use prefix application.
- **Generated-Python shapes:**
  - records are frozen dataclasses with snake_case keyword fields;
  - union variants are `<Union><Variant>` classes, with the payload as the single argument and in `.value`; unit variants take no argument (`InstructionWfi()`);
  - wrappers are one-argument classes (`Register(10)`);
  - `list<…>` is `ConsList` (`hydra.core.overlay.python.util.cons_list.ConsList.of(*items)`);
  - `binary` is `bytes`; `optional` is `Given`/`None_`; `either` is `Left`/`Right` (`hydra.core.overlay.python.dsl.python`);
  - camelCase names become snake_case;
  - a nullary *value* term (a literal, an injection, a list) is a module-level value, and a nullary *application* is an `@lru_cache(1)` zero-argument function.
- **Arithmetic:** `math.div` and `math.mod` are floor-based and return `optional`.
- **The golden image boots:** QEMU 7.2 booted `GOLDEN_IMAGE` (below), printing exactly `Hello from Hydra\n` with exit status 0.
  Every expected word in this plan was produced by GNU as 2.40 (`-march=rv64i -mno-relax`) and decoded with `objdump -M no-aliases,numeric`.

---

### Task 1: Project skeleton and the Hydra pipeline

**Files:**
- Create:
  - `.gitignore` (`.venv/`, `build/`, `__pycache__/`, `.pytest_cache/`);
  - `requirements.txt`;
  - `pytest.ini` (`[pytest]`, `testpaths = tests`, `pythonpath = .`);
  - `launcher/__init__.py` (a docstring only);
  - `launcher/pipeline.py`;
  - `tests/conftest.py`;
  - `tests/fixtures/hydra/hydraos/probe.hydra`.
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Produces, in `launcher/pipeline.py`:
  - `REPO_ROOT: Path` (the repo directory, from `__file__`);
  - `SOURCE_ROOT = REPO_ROOT / "src/main/hydra"`;
  - `GENERATED_DIR = REPO_ROOT / "build/python"`;
  - `CACHE_DIR = REPO_ROOT / "build/cache"`;
  - `class HydraError(Exception)`, whose message is Hydra's own text;
  - `bootstrap_graph() -> Graph`: an empty graph whose `primitives` is `standard_library()`;
  - `load_kernel_modules(cache_dir: Path = CACHE_DIR) -> list[Module]`;
  - `find_sources(root: Path) -> list[tuple[str, str]]`: (display path, text) for `root/**/*.hydra`, sorted;
  - `parse_sources(kernel, sources) -> list[Module]`;
  - `kernel_graph(kernel) -> Graph`;
  - `infer(graph, kernel, modules) -> list[Module]`;
  - `dependency_closure(modules, kernel) -> list[Module]`;
  - `generate_python(graph, kernel, inferred, out_dir: Path = GENERATED_DIR) -> list[Path]`;
  - `@dataclass class Project: graph: Graph; kernel: list[Module]; modules: dict[str, Module]; generated_dir: Path`, with a method `module(namespace: str) -> types.ModuleType`;
  - `load_project(source_roots=(SOURCE_ROOT,), generated_dir=GENERATED_DIR, cache_dir=CACHE_DIR) -> Project`.
- Produces, in `tests/conftest.py`: a session fixture `project` that loads `SOURCE_ROOT` and `tests/fixtures/hydra` into a `tmp_path_factory` directory, plus `FIXTURES = REPO_ROOT / "tests/fixtures"`.

- [ ] **Step 1: Branch, environment, box packages**

```bash
cd /work/hydra-os && git checkout -b increment-1-hello-kernel
apt-get install -y qemu-system-misc binutils-riscv64-linux-gnu
/work/toolchain/uv-python/cpython-3.13.18-linux-x86_64-gnu/bin/python3 -m venv .venv
printf 'hydra-kernel==0.18.1\nhydra-python==0.18.1\npytest==9.2.0\n' > requirements.txt
.venv/bin/pip install -r requirements.txt
```

Expected: `pip` finishes, and `qemu-system-riscv64 --version` prints `QEMU emulator version 7.2…`.

- [ ] **Step 2: Write the probe fixture and the failing tests**

`tests/fixtures/hydra/hydraos/probe.hydra`:

```
## Pipeline probe: proves parse, infer, generate and import on the Python host.
module hydraos.probe

import hydra.core.lib.math

## Double an integer.
term double = λx:int32. add x x
```

`tests/test_pipeline.py`:

```python
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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest -q tests/test_pipeline.py`
Expected: errors with `ModuleNotFoundError: No module named 'launcher.pipeline'`.

- [ ] **Step 4: Implement `launcher/pipeline.py`**

- **Recursion limit.** Call `sys.setrecursionlimit(10000)` at import time.
- **Kernel loading.** `load_kernel_modules` decodes every `hydra/hydra_kernel_json/hydra/**/*.json` (skipping `manifest.json`).
  - Find the directory with `importlib.resources.files("hydra")`.
  - Convert Python JSON values to `hydra.core.json.model` values; numbers become `Decimal` (`json.load(f, parse_float=Decimal)`).
  - Decode with the call shapes listed above. The schema map is `{name: deannotate_type_recursive(f_type_to_type_scheme(t).body)}` over `hydra.core.bootstrap.types_by_name`.
  - Cache the decoded list with pickle at `cache_dir / f"hydra-kernel-{importlib.metadata.version('hydra-kernel')}.pickle"`.
  - Write the cache atomically: write a temp file, then `os.replace`.
  - If the cache file fails to unpickle, rebuild it.
- **`find_sources`.** Display paths are repo-relative POSIX paths when inside `REPO_ROOT`, otherwise absolute.
- **Errors.** `parse_sources` raises `HydraError(left_value)`. `infer` and `generate_python` raise `HydraError(hydra.core.print.errors.error(err))`.
- **`kernel_graph`.** Returns `modules_to_graph(bootstrap_graph(), kernel, kernel)`.
- **`dependency_closure`.** The transitive closure, within `kernel`, of `module.dependencies[*].module`, matched by `Module.name`.
- **`generate_python`.**
  - Delete `out_dir` first.
  - Use the closure-plus-inferred universe.
  - Write every `(path, content)` pair under `out_dir`.
  - Return the written paths.
- **`Project.module`.** Inserts `generated_dir` at the front of `sys.path` (once), then calls `importlib.import_module`.
- **`load_project`.** Chains the above and keys `modules` by `m.name.value`.

- [ ] **Step 5: Run the tests to verify they pass, capped for the cold kernel decode**

Run: `/work/bin/run-capped.sh 8192 900 .venv/bin/pytest -q tests/test_pipeline.py`
Expected: `4 passed`. The first run takes about 70 s; later runs take a few seconds.

- [ ] **Step 6: Commit**

```bash
git add .gitignore requirements.txt pytest.ini launcher tests
git commit -m "Add the Hydra 0.18.1 pipeline: kernel loading, parse, infer, generate Python" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: The kernel program, run on the Python host

**Files:**
- Create:
  - `src/main/hydra/hydraos/hello.hydra`;
  - `launcher/__main__.py`;
  - `tests/fixtures/broken/broken.hydra` (contents: `module hydraos.broken\n\nterm x =\n`).
- Test: `tests/test_hello_python.py`

**Interfaces:**
- Consumes: `load_project`, `HydraError`, `SOURCE_ROOT`, `REPO_ROOT` (Task 1).
- Produces:
  - The CLI `python -m launcher run-hello [--source-root DIR]`.
    `DIR` is resolved against the current directory and defaults to `SOURCE_ROOT`.
    Its stdout is only the program's output.
    On a `HydraError`, or a `Left` result from `main()`, it prints `error: <message>` on stderr and exits 1.
    argparse usage errors exit 2.
  - `hydraos.hello.main`, whose type is `effect<either<SystemError, unit>>`.

- [ ] **Step 1: Write `src/main/hydra/hydraos/hello.hydra`** (verified to parse and infer on 0.18.1)

```
## The kernel: print one line, on any Hydra host.
module hydraos.hello

import hydra.core.lib.system
import hydra.core.lib.text

## Print a greeting.
term main = writeStdout (encodeUtf8 "Hello from Hydra\n")
```

- [ ] **Step 2: Write the failing tests**

```python
def run_launcher(*args, cwd=REPO_ROOT, env=None):
    return subprocess.run([sys.executable, "-m", "launcher", *args],
                          cwd=cwd, env=env, capture_output=True, timeout=600)

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
```

Put `run_launcher` in `tests/helpers.py`, which also holds every other shared test helper and constant.
Tests import it with `from helpers import …`; pytest's default import mode puts `tests/` on `sys.path`.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest -q tests/test_hello_python.py`
Expected: 2 failed (`No module named launcher.__main__`).

- [ ] **Step 4: Implement `launcher/__main__.py`**

Use argparse with subcommand `run-hello`.
It calls `load_project([source_root])`, then `project.module("hydraos.hello").main()`.
It prints nothing else to stdout.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest -q tests/test_hello_python.py`
Expected: `2 passed`.

- [ ] **Step 6: Commit**: `git add src launcher tests`, then `git commit -m "Run the hello kernel on Hydra's Python host"` with the Co-Authored-By line.

### Task 3: The RISC-V model, its DSL, and the encoder

**Files:**
- Create:
  - `src/main/hydra/hydraos/riscv/model.hydra` (types only);
  - `src/main/hydra/hydraos/riscv/dsl.hydra` (terms only);
  - `src/main/hydra/hydraos/riscv/encode.hydra`;
  - additions to `tests/helpers.py`.
- Test: `tests/test_encode.py`

**Interfaces:**
- Produces:
  - **`hydraos.riscv.model`**, whose exact text is below.
  - **`hydraos.riscv.dsl`**:
    - registers `zero, ra, t0, t1, t2, a0, a1 : Register` (x0, x1, x5, x6, x7, x10, x11);
    - `label : string → Item` and `data : binary → Item`;
    - `addi, andi, jalr, lbu : Register → Register → int32 → Item`, with arguments (rd, rs1, imm);
    - `sb, sw : Register → Register → int32 → Item`, with arguments (src, base, imm), giving `SType{rs1 = base, rs2 = src, imm}`;
    - `lui : Register → int32 → Item`;
    - `beq : Register → Register → string → Item`;
    - `jal, la : Register → string → Item`;
    - `wfi : Item`.
  - **`hydraos.riscv.encode.encodeProgram : Program → either<string, binary>`**, which is `encode_program` in Python.
  - **`tests/helpers.py`** additions:
    - `program(model, items) -> model.Program`, which wraps `ConsList.of(*items)`;
    - `encode(project, items) -> Left | Right`;
    - `objdump(image: bytes) -> list[str]`: the instruction text of each line, address, hex and `# …` comment stripped.
      It calls `riscv64-linux-gnu-objdump -D -b binary -m riscv:rv64 -M no-aliases,numeric`.
      If the tool is missing, it calls `pytest.fail("… apt-get install -y binutils-riscv64-linux-gnu")`.

`src/main/hydra/hydraos/riscv/model.hydra`:

```
## The RISC-V instructions this project emits (RV64I), as Hydra types.
##
## Source of truth: The RISC-V Instruction Set Manual, Volume I: Unprivileged ISA, and Volume II:
## Privileged Architecture (wfi). Record the edition and URL used here when implementing.
module hydraos.riscv.model

## An integer register x0..x31, by number.
type Register = wrap(int32)

## A symbolic address of an instruction or data byte in the image.
type Label = wrap(string)

## rd ← f(rs1, imm); imm in [-2048, 2047]. Used by addi, andi, jalr, lbu.
type IType = record{rd: Register, rs1: Register, imm: int32}

## memory[rs1 + imm] ← rs2; imm in [-2048, 2047]. Used by sb, sw.
type SType = record{rs1: Register, rs2: Register, imm: int32}

## rd ← imm << 12; imm in [0, 1048575]. Used by lui.
type UType = record{rd: Register, imm: int32}

## If rs1 = rs2, continue at target.
type Branch = record{rs1: Register, rs2: Register, target: Label}

## rd ← address of the next instruction; continue at target.
type Jump = record{rd: Register, target: Label}

## The la pseudo-instruction: rd ← address of target, always auipc + addi (8 bytes).
type LoadAddress = record{rd: Register, target: Label}

type Instruction = union{
  addi: IType,
  andi: IType,
  beq: Branch,
  jal: Jump,
  jalr: IType,
  la: LoadAddress,
  lbu: IType,
  lui: UType,
  sb: SType,
  sw: SType,
  wfi: unit}

## A label definition (0 bytes), an instruction (4 bytes; la is 8), or raw data bytes.
type Item = union{
  label: Label,
  instruction: Instruction,
  data: binary}

## A flat image: the items in order, starting at offset 0.
type Program = wrap(list<Item>)
```

- [ ] **Step 1: Write the helpers and the failing tests**

```python
W = "73005010"  # wfi
CASES = [  # (name, items, expected hex, objdump prefix)
    ("addi_positive", lambda d: [d.addi(d.t1, d.t1, 1365)], "13035355", ["addi x6,x6,1365"]),
    ("addi_negative", lambda d: [d.addi(d.a1, d.a1, -1)], "9385f5ff", ["addi x11,x11,-1"]),
    ("addi_zero_rs1", lambda d: [d.addi(d.a1, d.zero, 17)], "93051001", ["addi x11,x0,17"]),
    ("andi", lambda d: [d.andi(d.t1, d.t1, 32)], "13730302", ["andi x6,x6,32"]),
    ("lbu_offset", lambda d: [d.lbu(d.t1, d.t0, 5)], "03c35200", ["lbu x6,5(x5)"]),
    ("lbu_zero", lambda d: [d.lbu(d.t2, d.a0, 0)], "83430500", ["lbu x7,0(x10)"]),
    ("lui_small", lambda d: [d.lui(d.t1, 5)], "37530000", ["lui x6,0x5"]),
    ("lui_large", lambda d: [d.lui(d.t0, 65536)], "b7020010", ["lui x5,0x10000"]),
    ("sb", lambda d: [d.sb(d.t2, d.t0, 0)], "23807200", ["sb x7,0(x5)"]),
    ("sw", lambda d: [d.sw(d.t1, d.t0, 0)], "23a06200", ["sw x6,0(x5)"]),
    ("jalr", lambda d: [d.jalr(d.zero, d.ra, 0)], "67800000", ["jalr x0,0(x1)"]),
    ("wfi", lambda d: [d.wfi], W, ["wfi"]),
    ("jal_forward", lambda d: [d.jal(d.ra, "main"), *[d.wfi] * 6, d.label("main")],
     "ef00c001" + W * 6, ["jal x1,0x1c"] + ["wfi"] * 6),
    ("jal_backward", lambda d: [d.label("halt"), d.wfi, d.jal(d.zero, "halt")],
     W + "6ff0dfff", ["wfi", "jal x0,0x0"]),
    ("beq_forward", lambda d: [d.beq(d.a1, d.zero, "done"), *[d.wfi] * 8, d.label("done")],
     "63820502" + W * 8, ["beq x11,x0,0x24"] + ["wfi"] * 8),
    ("beq_backward", lambda d: [d.label("wait"), d.wfi, d.wfi, d.beq(d.t1, d.zero, "wait")],
     W * 2 + "e30c03fe", ["wfi", "wfi", "beq x6,x0,0x0"]),
    ("la_near", lambda d: [d.la(d.a0, "msg"), *[d.wfi] * 13, d.label("msg")],
     "17050000" "1305c503" + W * 13, ["auipc x10,0x0", "addi x10,x10,60"] + ["wfi"] * 13),
    ("la_far", lambda d: [d.la(d.a0, "far"), d.data(bytes(2040)), d.label("far")],
     "17150000" "13050580" + "00" * 2040, ["auipc x10,0x1", "addi x10,x10,-2048"]),
    ("data_verbatim", lambda d: [d.data(b"Hi")], "4869", []),
    ("empty_program", lambda d: [], "", []),
]
ERRORS = [  # (name, items, exact Left message)
    ("addi_imm_too_big", lambda d, m: [d.addi(d.a0, d.a0, 2048)], "addi: immediate 2048 out of range [-2048, 2047]"),
    ("lui_imm_too_big", lambda d, m: [d.lui(d.t0, 1048576)], "lui: immediate 1048576 out of range [0, 1048575]"),
    ("register_out_of_range", lambda d, m: [d.addi(m.Register(32), d.zero, 0)], "register 32 out of range [0, 31]"),
    ("undefined_label", lambda d, m: [d.jal(d.zero, "nowhere")], "jal: undefined label nowhere"),
    ("duplicate_label", lambda d, m: [d.label("main"), d.label("main")], "duplicate label main"),
    ("beq_out_of_range", lambda d, m: [d.beq(d.a1, d.zero, "far"), d.data(bytes(4092)), d.label("far")],
     "beq: offset 4096 out of range [-4096, 4094]"),
    ("misaligned_instruction", lambda d, m: [d.data(b"x"), d.wfi], "instruction at offset 1 is not 4-byte aligned"),
    ("misaligned_target", lambda d, m: [d.jal(d.zero, "odd"), d.data(b"x"), d.label("odd")],
     "jal: target odd at offset 5 is not 4-byte aligned"),
]
```

Write three tests:
- `test_encoding`, parametrized over `CASES`: the result is `Right`, and its value equals `bytes.fromhex(hex)`.
- `test_encoding_matches_gnu_objdump`, over the `CASES` with a non-empty prefix: `objdump(value)[:len(prefix)] == prefix`.
- `test_encoding_error`, over `ERRORS`: the result is `Left`, and its value equals the message.

`d` and `m` are `project.module("hydraos.riscv.dsl")` and `project.module("hydraos.riscv.model")`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest -q tests/test_encode.py`
Expected: errors (`No module named 'hydraos.riscv.dsl'`).

- [ ] **Step 3: Write `model.hydra` (above) and `dsl.hydra`**

`dsl.hydra` imports `hydraos.riscv.model` and contains only terms.
Each register is a constant such as `Register{10:int32}`.
Use `wrap(hydraos.riscv.model.Label){name}` for labels.

- [ ] **Step 4: Implement `encode.hydra`**

Only `encodeProgram` is public.

- **Pass 1, layout.**
  - Compute each item's offset: a label takes 0 bytes, an instruction 4, `la` 8, and data its length.
  - Build a label → offset map.
  - Report `duplicate label <name>` and `instruction at offset <n> is not 4-byte aligned`.
- **Pass 2, encoding.**
  - Encode in item order; the first error wins.
  - Do all bit arithmetic in `bigint`, using `literals.int32ToBigint` and `bigintToInt32`.
  - A negative field enters as `math.mod v (2^width)`.
  - Write each word as 4 little-endian bytes.

| Instruction | Format | Opcode | funct3 | Range checked (message `<m>: immediate|offset <v> out of range [lo, hi]`) |
|---|---|---|---|---|
| `addi` / `andi` / `lbu` / `jalr` | I | 0x13 / 0x13 / 0x03 / 0x67 | 0 / 7 / 4 / 0 | imm [-2048, 2047] |
| `sb` / `sw` | S | 0x23 | 0 / 2 | imm [-2048, 2047] |
| `beq` | B | 0x63 | 0 | offset = target − pc, in [-4096, 4094] |
| `lui` | U | 0x37 | – | imm [0, 1048575] |
| `jal` | J | 0x6F | – | offset in [-1048576, 1048574] |
| `la` | auipc (U, 0x17) + addi (I) | | | offset = target − pc; hi = (offset + 2048) div 4096; lo = offset − 4096·hi; offset in [-2147483648, 2147481599] |
| `wfi` | fixed word `0x10500073` | | | |

The field layouts follow the RISC-V manual:

- I: `imm[11:0]<<20 | rs1<<15 | f3<<12 | rd<<7 | op`
- S: `imm[11:5]<<25 | rs2<<20 | rs1<<15 | f3<<12 | imm[4:0]<<7 | op`
- B: `imm[12]<<31 | imm[10:5]<<25 | rs2<<20 | rs1<<15 | f3<<12 | imm[4:1]<<8 | imm[11]<<7 | op`
- U: `imm<<12 | rd<<7 | op`
- J: `imm[20]<<31 | imm[10:1]<<21 | imm[11]<<20 | imm[19:12]<<12 | rd<<7 | op`

Other errors:
- A register outside 0–31: `register <n> out of range [0, 31]`.
- A missing label: `<m>: undefined label <name>`.
- A branch, jump or `la` target that isn't 4-byte aligned: `<m>: target <name> at offset <n> is not 4-byte aligned`.

Turn the byte list into `binary` with a base64 encoder written in Hydra (standard alphabet, padded, mapped arithmetically) plus `literals.base64ToBinary`.

Import the colliding library names with aliases, for example `import hydra.core.lib.lists as lists`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest -q tests/test_encode.py`
Expected: `46 passed` (20 encodings, 18 objdump checks, 8 errors).

- [ ] **Step 6: Commit**: `git add src tests`, then `git commit -m "Add the RISC-V syntax model, its DSL and the encoder"` with the Co-Authored-By line.

### Task 4: The bare-metal runtime, as Hydra data

**Files:**
- Create: `src/main/hydra/hydraos/riscv/runtime.hydra`.
- Modify: `tests/helpers.py`, to add `GOLDEN_IMAGE` and `GOLDEN_SHA256` (below).
- Test: `tests/test_runtime.py`

**Interfaces:**
- Consumes: `hydraos.riscv.dsl` and `encodeProgram` (Task 3).
- Produces, as module-level `ConsList` values in Python:
  - `hydraos.riscv.runtime.startup : list<Item>`;
  - `hydraos.riscv.runtime.writeStdoutRoutine : list<Item>` (`write_stdout_routine`).
  Their labels are `main` (defined later by the coder), `halt`, `writeStdout`, `writeStdout.loop`, `writeStdout.wait` and `writeStdout.done`.

```python
GOLDEN_IMAGE = bytes.fromhex(
    "ef00c001 b7021000 37530000 13035355 23a06200 73005010 6ff0dfff"  # startup, 28 bytes
    "17050000 1305c503 93051001 6f004000"                             # main, 16 bytes
    "b7020010 63820502 03c35200 13730302 e30c03fe 83430500 23807200"  # writeStdout ...
    "13051500 9385f5ff 6ff01ffe 67800000"                             # ... 44 bytes
    "48656c6c6f2066726f6d2048796472610a")                             # "Hello from Hydra\n"
GOLDEN_SHA256 = "b6b66453b6357317825b8db6b818dcb1298253ae780c53413ef87e530eeff59f"
```

- [ ] **Step 1: Write the failing tests**

```python
def test_startup_encodes_to_golden_prefix(project):
    d, rt = project.module("hydraos.riscv.dsl"), project.module("hydraos.riscv.runtime")
    assert encode(project, [*rt.startup, d.label("main")]).value == GOLDEN_IMAGE[:28]

def test_write_stdout_routine_encodes_to_golden_slice(project):
    rt = project.module("hydraos.riscv.runtime")
    assert encode(project, list(rt.write_stdout_routine)).value == GOLDEN_IMAGE[44:88]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest -q tests/test_runtime.py`
Expected: errors (`No module named 'hydraos.riscv.runtime'`).

- [ ] **Step 3: Implement `runtime.hydra`** with exactly these sequences. The module's doc comment says the `either` result of `writeStdout` isn't materialized.

`startup`, starting at byte 0:
1. `jal ra "main"`
2. `lui t0 256`
3. `lui t1 5`
4. `addi t1 t1 1365`
5. `sw t1 t0 0` (stores 0x5555 at 0x0010_0000)
6. `label "halt"`
7. `wfi`
8. `jal zero "halt"`

`writeStdoutRoutine`, taking a0 = address and a1 = length:
1. `label "writeStdout"`
2. `lui t0 65536` (UART0)
3. `label "writeStdout.loop"`
4. `beq a1 zero "writeStdout.done"`
5. `label "writeStdout.wait"`
6. `lbu t1 t0 5` (LSR)
7. `andi t1 t1 32` (THRE)
8. `beq t1 zero "writeStdout.wait"`
9. `lbu t2 a0 0`
10. `sb t2 t0 0`
11. `addi a0 a0 1`
12. `addi a1 a1 -1`
13. `jal zero "writeStdout.loop"`
14. `label "writeStdout.done"`
15. `jalr zero ra 0`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest -q tests/test_runtime.py`
Expected: `2 passed`.

- [ ] **Step 5: Commit**: `git add src tests`, then `git commit -m "Add the bare-metal runtime: start-up, power-off, writeStdout"` with the Co-Authored-By line.

### Task 5: The coder

**Files:**
- Create:
  - `src/main/hydra/hydraos/riscv/coder.hydra`;
  - the fixtures `tests/fixtures/hydra/hydraos/unsupported/{nomain,stderr,sequence,function}.hydra`.
- Test: `tests/test_coder.py`

**Interfaces:**
- Consumes: `dsl`, `runtime.startup`, `runtime.writeStdoutRoutine`, `encode.encodeProgram`, `GOLDEN_IMAGE`.
- Produces:
  - `hydraos.riscv.coder.compileModule : hydra.core.graph.Graph → hydra.core.packaging.Module → either<string, Program>` (`compile_module`);
  - `hydraos.riscv.coder.buildImage : Graph → Module → either<string, binary>` (`build_image`), which is `compileModule` followed by `encodeProgram`, with encoder messages passed through unchanged.

Fixtures. Each one has a `module hydraos.unsupported.<name>` header and imports exactly the library modules it uses.
- `nomain`: `term greeting = writeStdout (encodeUtf8 "x")`
- `stderr`: `term main = writeStderr (encodeUtf8 "x")`
- `sequence`: `term main = bind (writeStdout (encodeUtf8 "a")) (λr. writeStdout (encodeUtf8 "b"))`, importing `hydra.core.lib.effects`
- `function`: `term main = λx:int32. writeStdout (encodeUtf8 "x")`. Don't name a module `lambda`: it is a Python keyword.

- [ ] **Step 1: Write the fixtures and the failing tests**

```python
def test_hello_builds_the_golden_image(project):
    r = project.module("hydraos.riscv.coder").build_image(project.graph, project.modules["hydraos.hello"])
    assert isinstance(r, Right), r
    assert r.value == GOLDEN_IMAGE
    assert hashlib.sha256(r.value).hexdigest() == GOLDEN_SHA256

@pytest.mark.parametrize("namespace,message", [
    ("hydraos.unsupported.nomain", "hydraos.riscv.coder: module hydraos.unsupported.nomain has no term definition named main"),
    ("hydraos.unsupported.stderr", "hydraos.riscv.coder: unsupported in main: application of hydra.core.lib.system.writeStderr"),
    ("hydraos.unsupported.sequence", "hydraos.riscv.coder: unsupported in main: application of hydra.core.lib.effects.bind"),
    ("hydraos.unsupported.function", "hydraos.riscv.coder: unsupported in main: lambda"),
])
def test_unsupported_programs_are_rejected(project, namespace, message):
    r = project.module("hydraos.riscv.coder").compile_module(project.graph, project.modules[namespace])
    assert isinstance(r, Left) and r.value == message
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest -q tests/test_coder.py`
Expected: errors (`No module named 'hydraos.riscv.coder'`).

- [ ] **Step 3: Implement `coder.hydra`**

1. Find the `term` definition named `<module>.main`.
2. Strip its body with `hydra.core.strip.deannotateAndDetypeTerm`.
   The parsed body is wrapped in a description annotation.
3. Require `application(variable hydra.core.lib.system.writeStdout, x)`.
   Otherwise return `hydraos.riscv.coder: unsupported in main: <description>`, where the description is:
   - for an application, `application of ` plus the head of the application spine: its name if the head is a variable, otherwise the head's own description;
   - `lambda` for a lambda;
   - `variable <name>` for a variable;
   - the term's variant name for anything else.
4. Reduce `x` with `hydra.core.reduction.reduceTerm unit g true x`.
   - The result must strip to a `binary` literal; otherwise return `hydraos.riscv.coder: argument of writeStdout did not reduce to a binary literal`.
   - If reduction fails, return `hydraos.riscv.coder: reduction failed: ` followed by `hydra.core.print.errors.error e`.
5. Assemble the `Program` as `startup` ++ `[label "main", la a0 "main.message", addi a1 zero <byte count>, jal zero "writeStdout"]` ++ `writeStdoutRoutine` ++ `[label "main.message", data <bytes>]`.
   `main` tail-calls `writeStdout`, because its value is `writeStdout`'s value; the routine then returns straight to `startup`, so no stack is needed.

Import the kernel modules for the types you match: `hydra.core.model`, `hydra.core.packaging` and `hydra.core.graph`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest -q tests/test_coder.py`
Expected: `5 passed`.

- [ ] **Step 5: Commit**: `git add src tests`, then `git commit -m "Add the RISC-V coder: compile hello into a boot image"` with the Co-Authored-By line.

### Task 6: Build command, committed image, QEMU boot, README

**Files:**
- Modify: `launcher/__main__.py`, adding the `build` subcommand.
- Create: `.gitattributes` (`out/*.bin binary`), `README.md`, `out/hello.bin`.
- Test: `tests/test_build.py`, `tests/test_qemu.py`

**Interfaces:**
- Consumes: `run_launcher`, `GOLDEN_IMAGE`, `build_image`.
- Produces: `python -m launcher build [--out PATH] [--source-root DIR]`.
  - `PATH` defaults to `REPO_ROOT / "out/hello.bin"`; a relative `PATH` is resolved against the current directory.
  - It writes the image bytes, creating parent directories, and prints `wrote <PATH> (<n> bytes)` on stderr.
  - Errors are reported as in `run-hello`.

- [ ] **Step 1: Write the failing tests**

```python
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
```

`tests/test_qemu.py`:

```python
def test_qemu_boots_the_image_and_prints_the_line(tmp_path):
    out = tmp_path / "hello.bin"
    assert run_launcher("build", "--out", str(out)).returncode == 0
    qemu = shutil.which("qemu-system-riscv64") or pytest.fail("qemu-system-riscv64 not found: apt-get install -y qemu-system-misc")
    r = subprocess.run([qemu, "-machine", "virt", "-bios", "none", "-nographic", "-kernel", str(out)],
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr.decode()
    assert r.stdout == b"Hello from Hydra\n"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest -q tests/test_build.py tests/test_qemu.py`
Expected: 5 failed (`invalid choice: 'build'`, missing `out/hello.bin`, attribute `unspecified`).

- [ ] **Step 3: Implement `build`.**
It calls `project.module("hydraos.riscv.coder").build_image(project.graph, project.modules["hydraos.hello"])` and writes the `Right` value.
Then add `.gitattributes`, and run `.venv/bin/python -m launcher build` to create `out/hello.bin`.

- [ ] **Step 4: Write `README.md`.**
It covers:
- what this is (link to Hydra and to the spec);
- the data flow in five lines;
- **Run it on Windows:**
  1. `winget install SoftwareFreedomConservancy.QEMU`
  2. In PowerShell from the clone: `& "C:\Program Files\qemu\qemu-system-riscv64.exe" -machine virt -bios none -nographic -kernel out\hello.bin`
  3. The expected line, after which QEMU exits by itself.
  4. The fallback if the console misbehaves: drop `-nographic` and add `-no-shutdown`; the line then appears in the window's serial console.
- **Run it on Linux:** the same command.
- **Build it:** Python ≥ 3.12, `pip install -r requirements.txt`, `python -m launcher build`.
- **Run it on the Python host:** `python -m launcher run-hello`.
- **Tests:** `pytest`, which needs `qemu-system-riscv64` and `riscv64-linux-gnu-objdump`.
- **Layout.**

- [ ] **Step 5: Run the whole suite and verify it passes**

Run: `.venv/bin/pytest -q`
Expected: `64 passed` (4 + 2 + 46 + 2 + 5 + 5).

- [ ] **Step 6: Record evidence for the Definition of Done**

Run:
- `qemu-system-riscv64 -machine virt -bios none -nographic -kernel out/hello.bin; echo "exit=$?"`
- `sha256sum out/hello.bin`
- `riscv64-linux-gnu-objdump -D -b binary -m riscv:rv64 -M no-aliases,numeric out/hello.bin | head -30`

Expected:
- `Hello from Hydra`, then `exit=0`;
- `b6b66453b6357317825b8db6b818dcb1298253ae780c53413ef87e530eeff59f  out/hello.bin`;
- the 22 instructions, starting with `jal x1,0x1c`.

Paste the outputs into the final report; don't commit them.

- [ ] **Step 7: Commit**: `git add .gitattributes README.md launcher out tests`, then `git commit -m "Add the build command, the committed boot image and the QEMU test"` with the Co-Authored-By line.

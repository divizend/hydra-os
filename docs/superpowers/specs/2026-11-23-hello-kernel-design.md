# Hello kernel: a Hydra program booting on bare-metal RISC-V

- **Date:** 2026-11-23
- **Status:** draft for review (increment 1)
- **Repo:** `divizend/hydra-os` (private)

In this document "the kernel" means our OS kernel. Hydra's own core is called "Hydra's kernel" (`hydra-kernel`).

## Intent

Build a tiny OS kernel that runs in QEMU, written entirely in [Hydra](https://github.com/CategoricalData/hydra).

In Hydra, a target language is itself written in Hydra.
Its syntax is a set of Hydra types (a *syntax model*), and translating into it is a Hydra program (a *coder* plus a *serializer*).
Each host hand-writes only its primitives and a thin runtime.
Every existing Hydra host was built this way (Hydra's `docs/recipes/new-implementation.md`).

This project applies the same idea one level down: **bare metal becomes the next Hydra host.**
The kernel is an ordinary, portable Hydra program.
A RISC-V syntax model, coder, runtime and serializer, all written in `.hydra`, turn it into a boot image.
Every byte of that image is computed by Hydra code.

The operator chose to start small, so this increment only boots and prints one line.
Keyboard input, interrupts and everything else come later, each as its own increment.

The operator is new to QEMU and works on Windows.
The build runs on cloud-admin-box (Linux).
The operator gets the result with `git pull` and runs it in QEMU on Windows.

## Definition of done

1. One documented command on cloud-admin-box builds `out/hello.bin` from the `.hydra` sources in a fresh clone.
2. Building twice gives byte-identical output, and the committed `out/hello.bin` matches a fresh build.
3. Running `qemu-system-riscv64 -machine virt -bios none -nographic -kernel out/hello.bin` writes exactly `Hello from Hydra\n` to the console, and QEMU exits with status 0.
   The captured output and exit status are recorded as evidence.
4. The same `hello.hydra`, sent through Hydra's existing Python coder and run on the Python host, writes exactly the same bytes to stdout.
5. A program outside the supported subset fails the build with an error naming the unsupported construct.
   At least one test covers this.
6. Every supported instruction has an encoding test.
   Expected bytes come from the RISC-V manual and are cross-checked against GNU binutils, never against our own encoder.
7. The README explains the Windows run: `winget install SoftwareFreedomConservancy.QEMU`, then one command.
   It can't be verified from the box, so it is the operator's check.

## Goals, non-goals, anti-goals

**Goals**

- `main` is a real Hydra program and runs unchanged on the Python host.
- A minimal RISC-V host written in `.hydra`: machine model, runtime, coder, encoder.
- Every byte of the image is computed by Hydra code.

**Non-goals for this increment**

- Keyboard input, interrupts, timers, memory management, multiple programs.
- A general Hydra-to-RISC-V compiler.
  The coder supports exactly what `hello.hydra` uses.
  Functions, closures, recursion, data structures and polymorphism come later.
- x86, ARM, real hardware.
- Contributing to `CategoricalData/hydra` (no upstream changes, no issues filed), or tracking Hydra's `main` branch.
- A `hydra run` command, CI, building on Windows.

**Anti-goals** (each counts as failure even if the image boots)

- Any byte of the image comes from a non-Hydra tool (assembler, linker, C compiler), or the repo contains hand-written assembly.
- The Python launcher knows anything about RISC-V; it only calls Hydra's published functions in order.
- `hello.hydra` contains anything RISC-V-specific.
- A silent fallback: an unsupported construct yields an image or a warning instead of an error.

## Approaches considered

| | Approach | Trade-off |
|---|---|---|
| **1 (chosen)** | RISC-V, compiling a real Hydra program from day one | Proves the actual idea. RISC-V is the simplest real CPU to model and compile to. Output appears on a serial console, not a PC screen. |
| 2 | x86 PC boot sector | Prettier first boot (text after the BIOS banner). But x86 encoding is irregular and a boot sector runs in 16-bit mode, so growing means a CPU mode switch and a coder rework. |
| 3 | Machine code only, no coder | Smallest step, but the kernel is assembly written as Hydra data, not a Hydra program. Approach 1 passes through this as a milestone anyway. |
| dropped | Emit assembly text for an external assembler (the pattern of Hydra's WebAssembly target, which relies on `wat2wasm`) | A non-Hydra tool would produce the bytes. |

The operator picked 1.

## Data flow

```
WHAT WE WRITE  (every file is .hydra)
  hello.hydra          the kernel: main = writeStdout (encodeUtf8 "Hello…")
  riscv/model.hydra    RISC-V instructions, described as Hydra types
  riscv/runtime.hydra  start-up code + the bare-metal writeStdout, as data
  riscv/coder.hydra    typed Hydra program  →  RISC-V program
  riscv/encode.hydra   RISC-V program       →  raw bytes

BUILD  (on cloud-admin-box: Hydra 0.18.1 running on Python)
  hello.hydra (text)
    │  parse      Hydra's parser
    ▼
  main as a term tree: writeStdout(encodeUtf8("Hello…"))
    │  infer      Hydra's type inference
    ▼
  the same tree with types: effect<either<SystemError, unit>>
    │  compile    our coder
    ▼
  a RISC-V program, as Hydra data:
    start-up → call writeStdout(message, 17) → power off
    + the writeStdout routine + the 17 bytes of the message
    │  encode     our encoder, 4 bytes per instruction,
    ▼             e.g. lui t0, 0x10000 → b7 02 00 10
  out/hello.bin  (well under 100 bytes, committed)

RUN  (QEMU; no Hydra or Python left)
  QEMU copies hello.bin to address 0x8000_0000 and starts the CPU there
    → the routine writes each byte to the serial port at 0x1000_0000
    → QEMU shows "Hello from Hydra", then the runtime powers off

SIDE PATH  (the same program on an ordinary host)
  hello.hydra → parse → infer → Hydra's own Python coder → Python code
    → writeStdout is Hydra's Python version → same bytes on stdout
```

`writeStdout` is the only place the two hosts differ.
On Python it is Hydra's own implementation; on bare metal it is the routine in `riscv/runtime.hydra`.

## Toolchain

- **Hydra 0.18.1 from PyPI, pinned.**
  `hydra-kernel==0.18.1` contains:
  - the `.hydra` parser, `hydra.core.parse.packaging.parse_modules(dep_modules, sources)`;
  - type inference, `hydra.core.codegen.infer_modules_given`;
  - the evaluator, `hydra.core.reduction.reduce_term`;
  - the Python host's primitives, `hydra.core.overlay.python.sources.libraries.standard_library()`;
  - every Hydra kernel module as JSON, under `hydra/hydra_kernel_json/`.

  `hydra-python==0.18.1` contains the Python coder (`hydra.python.coder.module_to_python`).
  Both need Python 3.12 or later.
  On the box, use the durable Python 3.13 at `/work/toolchain/uv-python/cpython-3.13.18-linux-x86_64-gnu`.
- **Don't build Hydra from source or track its `main`.**
  The `.hydra` syntax is weeks old and under active revision (Hydra #857).
- **Reference material.**
  Hydra's docs are in the read-only checkout `/work/hydra` (at `efd1579de7`, a few commits before 0.18.1) and the wiki is at `/work/hydra-wiki`.
  The most useful pages:
  - `docs/recipes/downstream-codegen.md`, the supported path for a downstream project;
  - `docs/recipes/new-implementation.md`;
  - `heads/wasm/host-abi.md`, the closest precedent for a target with no garbage collector;
  - the wiki's `Textual-syntax-by-example.md` and `Effects.md`;
  - `docs/hydra-lexicon.txt`, every primitive's signature.
- **QEMU on the box.**
  Debian's `qemu-system-misc` (QEMU 7.2) provides `qemu-system-riscv64`.
  An apt install lives on the pod's ephemeral overlay, so it has to be redone after a restart, or installed under `/work/toolchain`.
  Don't bake it into the box image.
- **Test oracle only.**
  Debian's `binutils-riscv64-linux-gnu` provides `as` and `objdump`.
  It never takes part in a build.
- **Windows.**
  winget installs the current QEMU release (11.1 is the newest as of this writing).
  The build doesn't run on Windows.

## The machine

QEMU's `virt` machine.
The facts below were checked in the source of 7.2 (the box's version) and 11.1 (the newest release, for Windows): `hw/riscv/virt.c`, `hw/riscv/boot.c`, `include/hw/misc/sifive_test.h`.
The first boot confirms them in practice.

- **Boot.**
  With `-bios none` there is no firmware.
  QEMU loads a raw (non-ELF) image at the start of DRAM, `0x8000_0000`, and the reset vector jumps there in machine mode.
  At that point `a0` holds the hart ID and `a1` the device-tree address.
  There is one hart by default.
  The image is a flat binary: byte 0 is the first instruction.
- **Serial port.**
  UART0 is an NS16550A at `0x1000_0000`, and a byte written to offset 0 (THR) is transmitted.
  The routine polls LSR (offset 5) for bit 5 (THRE) before each write, as the 16550 protocol requires, even though QEMU doesn't need it.
  (My call.)
- **Power-off.**
  The test device is at `0x0010_0000`.
  A 32-bit store of `0x5555` exits QEMU with status 0; `(code << 16) | 0x3333` exits with a failure code.

## Components

All components are `.hydra` modules under `src/main/hydra/hydraos/`, each named after its path (Hydra's convention).
The builder may rename them.

### `hydraos.riscv.model`: the RISC-V syntax model

- **Source of truth:** *The RISC-V Instruction Set Manual, Volume I: Unprivileged ISA* (ratified edition), plus *Volume II: Privileged* for `wfi` and machine mode.
  Record the edition and URL in the module's doc comment, as Hydra's new-implementation recipe asks.
- **Target:** RV64I, as run by `qemu-system-riscv64`.
- **Coverage:** only what this increment emits, as Hydra types:
  - the registers;
  - the base instruction formats;
  - the instructions used (likely `lui`, `auipc`, `addi`, `andi`, `lbu`, `sb`, `sw`, `beq`, `bne`, `jal`, `jalr`, `wfi`);
  - a `Program`, which is a list of label definitions, instructions and data bytes.
    Branch, jump and address operands may name labels.
- **Pitfall:** on RV64, `lui` sign-extends bit 31, so an upper immediate of `0x80000` or above yields `0xFFFF_FFFF_8…`.
  Reach addresses inside the image (`0x8000_0000` and up) PC-relatively with `auipc` and `addi`.
  The device addresses `0x1000_0000` and `0x0010_0000` are safe with `lui`.

### `hydraos.riscv.encode`: the serializer

- **Signature:** `Program → either<string, binary>`.
  It lays out the items, resolves labels, and writes each instruction as one 32-bit little-endian word, followed by the data bytes.
- **No bitwise primitives.**
  Hydra has none, so build bit fields with arithmetic.
  `math.div` and `math.mod` return `optional`.
  Use `int64` or `bigint` so nothing overflows, and form two's complement by adding 2^k.
- **No bytes-to-binary primitive.**
  Hydra has `binaryToBytes` but not its inverse.
  Produce the `binary` through a small base64 encoder written in Hydra plus `literals.base64ToBinary`.
  This is a known gap; don't file it upstream.
- **Range checks.**
  An immediate or offset out of range is an error naming the instruction and value.
  Never truncate.

### `hydraos.riscv.runtime`: the host's runtime, as Hydra data

This is the counterpart of a Hydra overlay, the hand-written part of a host, but written as `Program` data rather than assembly text.

- **Start-up at byte 0:** call `main`.
  When it returns, power off with `0x5555`, then loop on `wfi` in case power-off fails.
  No stack is needed in this increment, because `writeStdout` is a leaf routine; later increments add one.
- **`writeStdout`:** the native implementation of the primitive `hydra.core.lib.system.writeStdout`.
  The buffer address arrives in `a0` and the length in `a1`.
  It sends each byte unchanged, with no newline translation, because both hosts must produce the same bytes.
- **No return value.**
  The primitive's `either<SystemError, unit>` result isn't materialized, because the runtime ignores `main`'s result.
  The module's doc comment says so.

### `hydraos.riscv.coder`: the coder

- **Signature:** (inferred `hydraos.hello` module, graph of Hydra primitives for evaluation) → `either<string, Program>`.
- **Supported:** a term definition `main` whose body, once annotations, type lambdas and type applications are stripped, is `writeStdout x`.
  `x` must be pure, and the kernel's own `reduce_term` must reduce it to a `binary` literal.
  Using Hydra's own evaluator means "pure part" follows Hydra semantics exactly, not a hand-rolled subset.
  (My call.)
- **Output:** the start-up code, then `main` as a call to `writeStdout(message, length)`, then the runtime routines and the message bytes.
- **Anything else** is an error naming the construct and where it is.
- **Not wired into `codegen.generate_source_files`,** which produces text files.
  This target's output is binary, so the launcher calls the coder directly.

### `hydraos.hello`: the kernel

```
module hydraos.hello

import hydra.core.lib.system
import hydra.core.lib.text

## Print a greeting.
term main = writeStdout (encodeUtf8 "Hello from Hydra\n")
```

This is a syntax sketch; confirm it against the 0.18.1 parser.
`main` has type `effect<either<hydra.core.error.system.SystemError, unit>>`.
Hydra's examples use `main : effect<unit>`, but nothing requires it, and the runtime ignores the result.

## The launcher

The launcher is host-side Python glue, the role a Hydra `heads/` driver plays.
It exists because Hydra has no `hydra run` command yet (Hydra #440).

1. Pin `hydra-kernel==0.18.1` and `hydra-python==0.18.1`.
2. Load the Hydra kernel's modules from the bundled JSON.
   There's no published Python `load_kernel_modules()` helper yet (Hydra #786), so decode them with the kernel's own JSON decoder.
3. Parse our `.hydra` files with `parse_modules`.
4. Fold the kernel type modules into the graph.
   Without this, primitives that mention kernel types fail with `NoSuchBinding` (Hydra #640).
5. Run `infer_modules_given` over our modules.
6. Generate Python for our modules with `module_to_python`, deriving `overlay_subs` as the downstream recipe shows (Hydra #644).
7. Import the generated coder and encoder and call them on the inferred `hydraos.hello`.
8. Write the resulting `binary` to `out/hello.bin`.

A second command runs the side path: the generated `hydraos.hello.main` on the Python host.
On that host effects are transparent (`pure(a) = a`).
Read the generated code to see how a nullary, effect-typed definition is emitted, as a module-level value or a `Lazy(...)` wrapper; that decides how to invoke it.
Hydra has no convention for running `effect` entry points yet (an open question on the Effects wiki page).

Running the coder as generated Python is how Hydra runs every coder: natively, on a host.
There is deliberately no interpreted fallback.
A coder that calls `reduce_term` needs the host's primitive graph, and Hydra can't encode a `Graph` as a term (its primitives hold host-native functions), so Hydra's interpreter can't run this coder.
If a Python-coder bug blocks the generated path, restructure our `.hydra` source to avoid the construct that triggers it.
If that isn't possible, stop and report the bug with evidence rather than patching around it in the launcher or in generated code.
(My call.)

The launcher contains no RISC-V knowledge and no project logic.

## Verification

- **Encoder unit tests.**
  For each instruction, the expected word comes from the manual's encoding tables, and is confirmed by assembling the same instruction with `riscv64-linux-gnu-as`.
- **Coder tests.**
  The supported program produces the expected `Program`.
  Unsupported programs (a lambda, a different primitive, an argument that doesn't reduce to a literal) each produce their specific error.
- **End to end.**
  Boot QEMU under `timeout`, capture the serial output, compare it byte for byte, and check exit status 0.
  Disassemble `out/hello.bin` with `riscv64-linux-gnu-objdump -D -b binary -m riscv:rv64` for the evidence trail.
- **Python host.**
  Run the side path and compare stdout byte for byte.
- **Test language.**
  Tests run on the host (pytest), since they contribute nothing to the image.
  (My call.)
- **Memory safety on the box.**
  Run Python-host inference over the kernel universe under `/work/bin/run-capped.sh` until its memory peak is known (a box rule).

## Running on Windows

1. `winget install SoftwareFreedomConservancy.QEMU`.
   It usually installs to `C:\Program Files\qemu` and isn't added to `PATH`.
2. From the cloned repo, in PowerShell:
   `& "C:\Program Files\qemu\qemu-system-riscv64.exe" -machine virt -bios none -nographic -kernel out\hello.bin`
3. Expected: the line appears, then QEMU exits.
4. If the console misbehaves with `-nographic`, drop it and add `-no-shutdown`.
   The line then appears in the QEMU window's serial console, and the window stays open after power-off.

## Delivery

- **Repo:** GitHub `divizend/hydra-os`, private (my call; it can be made public any time).
- **Build output:** `out/hello.bin` is committed, because the operator gets files with `git pull`, never by copying them off the box.

## Risks to retire first, in order

1. **The downstream pipeline on 0.18.1.**
   Send the smallest slice through it: a trivial `.hydra` module parsed, inferred, generated to Python and imported.
2. **The boot path.**
   Have the encoder produce a four-instruction image that only powers off, and check that QEMU exits with status 0.
   That confirms the load address and the test device before any UART code exists.
3. **How the Python host runs `main`** (see the launcher section).

## Left to the builder

- Exact Python API calls and argument shapes.
- Generated-code layout.
- The launcher's command-line shape.
- Module and file names.
- The encoding helpers.
- Register choice in the runtime.
- Test layout.
- README wording.

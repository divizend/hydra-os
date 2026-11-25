# hydra-os

A tiny OS kernel written entirely in [Hydra](https://github.com/CategoricalData/hydra), booting on
64-bit RISC-V in QEMU.

This first increment boots and prints one line:

```
$ qemu-system-riscv64 -machine virt -bios none -nographic -kernel out/hello.bin
Hello from Hydra
```

## How it works

In Hydra, a target language is itself written in Hydra: a syntax model (types), a coder and a
serializer. This repo applies that to bare metal, so the RISC-V machine becomes one more Hydra host.

```
hello.hydra            the kernel: main = writeStdout (encodeUtf8 "Hello from Hydra\n")
  → parse, infer       Hydra 0.18.1's own parser and type inference
  → riscv/coder.hydra  main becomes a RISC-V program, as Hydra data, joined with riscv/runtime.hydra
  → riscv/encode.hydra the program becomes bytes, each field derived as an atom of the build's record
  → out/hello.bin      105 bytes; QEMU loads them at 0x8000_0000 and the CPU runs them
    out/hello.derivation.json   where every bit of them came from
```

Every byte of `out/hello.bin` is computed by Hydra code: no assembler, linker or C compiler is
involved. In this increment the coder accepts `main = writeStdout x` for any pure `x` of at most
2047 bytes. `x` may use the module's other definitions, and Hydra's own evaluator computes it during
the build. Anything else fails the build with an error that names the construct. `writeStdout` is the only place the two hosts differ. On bare metal it is the routine in
`riscv/runtime.hydra`, which sends each byte to the serial port. The same `hello.hydra` also runs on
Hydra's Python host, where `writeStdout` is Hydra's own implementation.

The design is in [docs/superpowers/specs](docs/superpowers/specs/2026-11-23-hello-kernel-design.md).

## Run it on Windows

1. Install QEMU (once): `winget install SoftwareFreedomConservancy.QEMU`
2. In PowerShell, from your clone of this repo:

   ```powershell
   & "C:\Program Files\qemu\qemu-system-riscv64.exe" -machine virt -bios none -nographic -kernel out\hello.bin
   ```

3. You should see `Hello from Hydra`, and then QEMU exits by itself: the kernel powers the machine
   off once `main` returns.
4. If the console misbehaves with `-nographic`, drop it and add `-no-shutdown`. The line then
   appears on the serial console in QEMU's window, and the window stays open after power-off.

These steps have not been tried on Windows yet.

## Run it on Linux

```
qemu-system-riscv64 -machine virt -bios none -nographic -kernel out/hello.bin
```

On Debian or Ubuntu, QEMU's RISC-V emulator comes from `apt install qemu-system-misc`.

## Build it

The build needs Python 3.12 or newer:

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m launcher build
```

This writes `out/hello.bin` and its derivation record, `out/hello.derivation.json` (see below). The
first build decodes Hydra's kernel (about a minute) and caches it under `build/cache/`. Later builds
take about two minutes, almost all of it Hydra's type inference and code generation on the Python
host.

## Explain it

`build` also reports how much of the image its record explains:

```
derivation: 840 of 840 bits explained, 840 traced to source, 336 atoms
```

The record, [`out/hello.derivation.json`](out/hello.derivation.json), lists the *atoms* of the build:
every piece of data that went into the image, such as a character of the message, an operand, a
constant of the encoder, an offset or a field of an instruction. Each atom has

- a place: where it is written in a `.hydra` source (a Hydra `SubtermPath` in a definition's body,
  resolved to its file, line, column, text and a GitHub link to that line), a named intermediate
  value of the build, or bits of the image;
- a value: a number, or the name of a label;
- a formula that gives its value from earlier atoms: stated (written in a source), copy, sum,
  difference, product, quotient, bits, count, utf8 or labelOffset;
- a rule: the Hydra definition whose code applied that formula.

The record also lists the program's 29 items, each with the call that wrote it (`wfi`, item 6, is
written in `runtime.hydra`'s `startup`) and the atoms of its operands.

The encoder computes every field of the image through these formulas and assembles the image from the
atoms that live in it, so the bytes and their explanation are one computation; the build fails if the
atoms do not tile the image exactly. Following any field back ends in source text. Byte 0x31, for
example, holds bits of `beq a1 zero "writeStdout.done"`: its `rs1` bits copy the 11 written in
`dsl.hydra`'s definition of `a1`, its `funct3` bits come from `encode.hydra`'s table of encodings, and
its offset bits are the offset of the label `writeStdout.done` minus the branch's own.

The coder traces each operand by reading the sources as data, and checks every value it traces against
the program Hydra evaluated. The design is in
[the spec](docs/superpowers/specs/2026-11-25-derivation-record-design.md).

### Check the record

```
.venv/bin/python -m launcher check-derivation --jobs 8 --report derivation-check.txt
```

This changes one source atom at a time in a copy of the sources (each character of the message, each
operand in `runtime.hydra` and `coder.hydra`, each register number in `dsl.hydra`, each constant in
`encode.hydra`: 694 changes), rebuilds each copy with `build` in a fresh process, and compares the
image with what the record predicts for that change. Every build that succeeds must match its
prediction bit for bit. Builds that one of the encoder's own checks rejects (a value out of range, a
misaligned target, a size that disagrees with the encoding) are listed with their error; any other
failed build fails the check. A full run takes about three and a half hours with 8 builds at a time,
and about 4 GB of memory. The report of the last full run, with every change and its outcome, is in
[docs/evidence](docs/evidence/2026-11-25-derivation-check.txt).

### Keep it current

Each span's link pins the commit that last changed its file. After changing a `.hydra` file, commit it
first, then run `build` and commit the new record; `tests/test_record.py` fails while the committed
record differs from a fresh build. Merge such commits as they are, with a merge commit or a
fast-forward: a squash or a rebase gives them new commits, and the record's links would then name
commits the merged branch does not have, until the record is built and committed again.

## Run it on Hydra's Python host

```
.venv/bin/python -m launcher run-hello
```

This prints the same line, through Hydra's own `writeStdout`.

## Tests

```
.venv/bin/pytest
```

The tests need `qemu-system-riscv64` and `riscv64-linux-gnu-objdump`; on Debian or Ubuntu, run
`apt install qemu-system-misc binutils-riscv64-linux-gnu`. objdump is only a test oracle: it decodes
the bytes the encoder produces, to check them, and never produces any itself.

## Layout

```
src/main/hydra/hydraos/   the kernel (hello.hydra) and the RISC-V host (riscv/*.hydra)
launcher/                 Python glue that runs Hydra's pipeline, writes the record and runs its check;
                          it holds no project logic
tests/                    the pytest suite, with its .hydra fixtures
out/hello.bin             the committed boot image
out/hello.derivation.json its committed derivation record
docs/superpowers/         the designs and the implementation plans
docs/evidence/            reports of runs, such as the derivation check
```

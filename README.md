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
  → riscv/encode.hydra the program becomes bytes
  → out/hello.bin      105 bytes; QEMU loads them at 0x8000_0000 and the CPU runs them
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

This writes `out/hello.bin`. The first build decodes Hydra's kernel (about a minute) and caches it
under `build/cache/`. Later builds take about 40 seconds, almost all of it Hydra's type inference on
the Python host.

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
launcher/                 Python glue that runs Hydra's pipeline; it holds no project logic
tests/                    the pytest suite, with its .hydra fixtures
out/hello.bin             the committed boot image
docs/superpowers/         the design and the implementation plan
```

# Derivation record: hello.bin explains itself

- **Date:** 2026-11-25
- **Status:** approved by the operator on 2026-11-25 ("yes" to the next step proposed in the research note
  <https://claude.ai/artifact/CYGcThnX8bB2SsUJDpT3PL>)
- **Builds on:** [the hello kernel design](2026-11-23-hello-kernel-design.md)

## Intent

Make the build record its own derivation, before any interface is built on it.
Every piece of data that went into `out/hello.bin` (a character, an operand, a constant in the encoder, a
label offset, an instruction field) is an *atom*: where it lives, its value, the formula that gives its
value from other atoms, and the Hydra definition whose code applied that formula.
The steps that compute the bytes emit these atoms as they compute, and the image is assembled from them,
so the bytes and their explanation cannot disagree.

## Definition of done

1. **Coverage.** `python -m launcher build` writes `out/hello.derivation.json` beside `out/hello.bin` and
   prints how many of the image's bits the record explains. All 840 bits of hello.bin resolve to atoms
   with a rule, inputs and a formula, and every one of them traces back to source text: 0 unexplained.
   A build whose atoms do not tile the image exactly fails.
2. **Mutation check.** `python -m launcher check-derivation` changes one source atom at a time, rebuilds
   for real, and compares the new image with what the record predicts when it is re-evaluated with the
   changed value. Source atoms: each character of the message, each operand written in runtime.hydra and
   coder.hydra, each register number in dsl.hydra, each constant in encode.hydra. Every build that
   succeeds must match the prediction bit for bit. Builds the encoder rejects are listed with their error.
   The report is committed under `docs/evidence/`.
3. The mockup's reconstruction script (`/work/hydra-os-viz/gen/`) is deleted. Any viewer from now on reads
   only the record.

## Non-goals

- No viewer or other interface. The record is JSON; the next increment draws it.
- No change to Hydra itself. Origins inside Hydra's evaluator would be the general home for this (see
  below), and stays a candidate for later.
- Messages computed by library functions (the `computed` fixture) are traced only as a whole: each byte is
  an atom given by Hydra's evaluator, placed on the argument term. Fine-grained tracing covers `encodeUtf8`
  applied to a string literal, directly or through definitions of the same module.
- Structure is recorded but not mutated: which constructor an item uses, the order of items, and the
  RISC-V format layouts (field positions and widths), which are the rules themselves.

## Model

Types in a new types-only module `hydraos.riscv.derivation`:

- `Value`: a `number` (bigint) or a `name` (a label).
- `Place`: `source` (a definition, a Hydra `SubtermPath` inside its body, and for a string literal an
  optional character index), `intermediate` (a named value of the build), or `image` (byte offset of a
  word or byte, lowest bit, width).
- `Formula`: `given`, `copy`, `sum`, `difference`, `product`, `quotient` (floor), `bits` (lo, width, two's
  complement), `count`, `utf8` (byte k of a code point's encoding), `labelOffset` (the offset of the label
  an atom names).
- `Rule`: the Hydra definition whose code applied the formula, and a short detail.
- `Atom`: id, place, value, formula, rule. `Derivation`: the atoms, each formula referring only to atoms
  before it.

One small evaluator module computes a formula's value, re-evaluates a whole derivation with one atom's
value changed (`predict`), assembles the image from the image atoms, and counts coverage. The encoder uses
the same evaluator to compute every field, which is what makes the bytes and the record one computation.

## Who records what

- **Coder.** The message's characters (source places in the string literal), their UTF-8 bytes, the
  message's length. For each item of the program: the subterm that wrote it and an atom per operand:
  int32 literals and label names as given source atoms, registers as copies of the register numbers in
  dsl.hydra, the length immediate as `count` of the message bytes.
- **Encoder.** Its constants, now kept as data in `encode.hydra`: a table of opcode and fixed fields per
  mnemonic (`wfi` becomes its SYSTEM fields instead of one magic word), the instruction, `la` and label
  sizes, and the `la` page constants. Then the size and offset of every item, every label's offset, every
  branch and jump offset, `la`'s upper and lower halves, and one image atom per instruction field and data
  byte.

A finding shaped the coder's part: Hydra 0.18.1's evaluator keeps annotations through beta-reduction only
on the constructor's own parameter occurrences and on definitions, and drops those on call-site
arguments. Origins therefore cannot ride through `reduceTerm` alone. The coder reads the source terms of
the item lists as data (code as data, which Hydra is built for), and every traced value is checked against
the program Hydra evaluates; a disagreement fails the build.

## Checks the encoder gains

- Its own constants are range-checked like operands (opcode below 128, funct3 below 8, funct12 below 4096),
  so a bad constant fails the build instead of spilling into a neighboring field.
- Each item's encoded length must equal its recorded size.
- The image Hydra's encoder produces must equal the image assembled from the record.

## Mutation check

Each mutation is realized in a copy of the sources and built with the real pipeline in a fresh process.
- Characters: flip bits 0 to 6, written back with Hydra's own string escaping.
- Numbers: flip each bit below the width of the field the number feeds, or below one more than its bit
  length where it feeds arithmetic.
- Register operands: a register number with one bit flipped, written as a register defined for the copy in
  dsl.hydra when no existing one has that number.
- Label operands: every other label.

The prediction is `predict` on the original record with that atom's value replaced. Report: per kind,
mutations run, matched, rejected by the build (with the error), mismatched (with the bits).

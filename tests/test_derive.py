"""The derivation record's evaluator: formulas, the image assembled from atoms, prediction, coverage."""

import pytest
from hydra.core.overlay.python.dsl.python import Given, Left, Right
from hydra.core.overlay.python.util.cons_list import ConsList
from hydra.core.paths import SubtermPath

BEQ = [  # beq a1, zero, +36 = 0x02058263: (field, lo, width, value)
    ("imm[12]", 31, 1, 0), ("imm[10:5]", 25, 6, 1), ("rs2", 20, 5, 0), ("rs1", 15, 5, 11),
    ("funct3", 12, 3, 0), ("imm[4:1]", 8, 4, 2), ("imm[11]", 7, 1, 0), ("opcode", 0, 7, 99),
]


@pytest.fixture(scope="module")
def d(project):
    return project.module("hydraos.riscv.derivation")


@pytest.fixture(scope="module")
def derive(project):
    return project.module("hydraos.riscv.derive")


def atom(d, key, value, formula=None, place=None):
    value = d.ValueNumber(value) if isinstance(value, int) else d.ValueName(value)
    return d.Atom(d.AtomId(key), place or d.PlaceIntermediate(key), value, formula or d.FormulaStated(), d.Rule("test", key))


def image(d, key, offset, lo, width, value, formula=None):
    return atom(d, key, value, formula, d.PlaceImage(d.ImagePlace(offset, lo, width)))


def value_of(derive, atoms, formula):
    r = derive.evaluate(derive.atom_values(ConsList.of(*atoms)), formula)
    assert isinstance(r, Right), r
    return r.value.value


def test_bits_of_a_negative_number_are_its_twos_complement(d, derive):
    assert value_of(derive, [atom(d, "imm", -1)], d.FormulaBits(d.BitsOf(d.AtomId("imm"), 0, 12))) == 4095


def test_bits_select_a_slice(d, derive):
    assert value_of(derive, [atom(d, "offset", 36)], d.FormulaBits(d.BitsOf(d.AtomId("offset"), 1, 4))) == 2


def test_quotient_rounds_toward_minus_infinity(d, derive):
    atoms = [atom(d, "a", -1), atom(d, "b", 4096)]
    assert value_of(derive, atoms, d.FormulaQuotient(d.Operands(d.AtomId("a"), d.AtomId("b")))) == -1


def test_utf8_gives_one_byte_of_a_code_points_encoding(d, derive):
    assert value_of(derive, [atom(d, "u", 0xFC)], d.FormulaUtf8(d.Utf8Byte(d.AtomId("u"), 1))) == 0xBC


def test_count_is_the_number_of_atoms(d, derive):
    atoms = [atom(d, f"b{i}", i) for i in range(17)]
    assert value_of(derive, atoms, d.FormulaCount(ConsList.of(*[d.AtomId(f"b{i}") for i in range(17)]))) == 17


def test_label_offset_reads_the_label_an_atom_names(d, derive):
    atoms = [atom(d, "label/main", 28), atom(d, "target", "main")]
    assert value_of(derive, atoms, d.FormulaLabelOffset(d.AtomId("target"))) == 28


def test_assemble_packs_fields_little_endian(d, derive):
    atoms = [image(d, f, 0, lo, w, v) for f, lo, w, v in BEQ] + [image(d, "byte", 4, 0, 8, 0x48)]
    assert derive.assemble(ConsList.of(*atoms)) == Right(bytes.fromhex("6382050248"))


def test_assemble_names_an_unexplained_bit(d, derive):
    atoms = [image(d, f, 0, lo, w, v) for f, lo, w, v in BEQ if f != "imm[11]"]
    assert derive.assemble(ConsList.of(*atoms)) == Left("image: bit 7 of the unit at offset 0 is not explained by any atom")


def test_assemble_names_a_bit_explained_twice(d, derive):
    atoms = [image(d, f, 0, lo, w, v) for f, lo, w, v in BEQ] + [image(d, "extra", 0, 3, 2, 0)]
    assert derive.assemble(ConsList.of(*atoms)) == Left("image: bit 3 of the unit at offset 0 is explained by two atoms")


def test_assemble_names_an_unexplained_byte(d, derive):
    atoms = [image(d, "first", 0, 0, 8, 1), image(d, "third", 2, 0, 8, 3)]
    assert derive.assemble(ConsList.of(*atoms)) == Left("image: byte 1 is not explained by any atom")


def char_derivation(d, place):
    char = atom(d, "char", ord("H"), place=place)
    byte = atom(d, "byte", 0x48, d.FormulaUtf8(d.Utf8Byte(d.AtomId("char"), 0)))
    out = image(d, "out", 0, 0, 8, 0x48, d.FormulaCopy(d.AtomId("byte")))
    return d.Derivation(ConsList.of(char, byte, out))


def test_predict_reevaluates_with_one_value_changed(d, derive):
    deriv = char_derivation(d, None)
    assert derive.predict(deriv, d.AtomId("char"), d.ValueNumber(ord("I"))) == Right(b"I")
    assert derive.predict(deriv, d.AtomId("char"), d.ValueNumber(ord("H"))) == Right(b"H")


def test_coverage_counts_bits_and_bits_traced_to_source(d, derive):
    source = d.PlaceSource(d.SourcePlace("hydraos.hello.main", SubtermPath(ConsList.of()), Given(0)))
    assert derive.coverage(char_derivation(d, source)) == d.Coverage(8, 8, 3)
    assert derive.coverage(char_derivation(d, None)) == d.Coverage(8, 0, 3)


def test_an_atom_that_refers_to_a_later_atom_is_not_traced_to_source(d, derive):
    # A derivation lists each atom after the atoms its formula refers to; coverage reads it in one pass.
    source = d.PlaceSource(d.SourcePlace("hydraos.hello.main", SubtermPath(ConsList.of()), Given(0)))
    out = image(d, "out", 0, 0, 8, 0x48, d.FormulaCopy(d.AtomId("char")))
    char = atom(d, "char", ord("H"), place=source)
    assert derive.coverage(d.Derivation(ConsList.of(out, char))) == d.Coverage(8, 0, 2)

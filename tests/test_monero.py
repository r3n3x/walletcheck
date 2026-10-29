"""Monero support (offline): 25-word seeds (and 24-word without checksum word) are
detected, the primary address is derived, and nothing is ever checked online.
Cross-validated against the independent monero-python library. No network."""
import csv
import os

import pytest

import walletcheck as W

# Fixed vector: bip_utils and monero-python agree on every value for this mnemonic
MNEMONIC = ("fawns bowling arsenic syndrome items fifteen solved atom racetrack oven large "
            "wonders selfish broken acumen licks rural dewdrop cupcake strained unquoted "
            "goggles paddles puzzled fawns")
ADDRESS = "49WpyDh52VKh1PWTR82nAqPSu33EcjtT8X5ga67WcsuoLK63wpk7ThZAX2z3KVHMZyCt2rRffcxYnZddJivn5bXTHiWcLc3"
SPEND = "851466f170f7d1dd88325d9f6b89328166fa23e3af712e74aa27cb16837ac10d"
VIEW = "dc63cf4dd81f2151a934e9a624bb98f38204c82e77fb3842223b4ca590b06d0c"


def xmr_rows(b):
    seqs = []
    label = W.derive_item(b, MNEMONIC, 1, None, seqs)
    return label, seqs


def test_primary_address_matches_fixed_vector(b):
    label, seqs = xmr_rows(b)
    assert label == "seed25-Monero"
    row = seqs[0].fn(0)[0]
    assert row[2] == "xmr" and row[4] == "monero account 0"
    assert row[5] == ADDRESS


def test_24_word_seed_without_checksum_word_gives_same_address(b):
    seqs = []
    label = W.derive_item(b, " ".join(MNEMONIC.split()[:24]), 1, None, seqs)
    assert label == "seed24-Monero (no checksum word)"
    assert seqs[0].fn(0)[0][5] == ADDRESS


def test_keys_agree_with_fixed_vector(b):
    from bip_utils import Monero, MoneroSeedGenerator
    m = Monero.FromSeed(MoneroSeedGenerator(MNEMONIC).Generate())
    assert m.PrivateSpendKey().Raw().ToHex() == SPEND
    assert m.PrivateViewKey().Raw().ToHex() == VIEW


def test_cross_validation_against_monero_python(b):
    monero = pytest.importorskip("monero.seed")
    s = monero.Seed(MNEMONIC)
    assert s.public_address() == ADDRESS
    _, seqs = xmr_rows(b)
    assert seqs[0].fn(0)[0][5] == s.public_address()


def test_bip39_phrase_is_never_taken_as_monero(b):
    bip24 = ("food return real bamboo wood fever gallery hurdle cereal bargain cry usual "
             "wreck equal husband transfer valley winner wing hat bar gate multiply way").split()
    seqs = []
    label = W.derive_item(b, " ".join(bip24), 1, None, seqs)
    assert label.startswith("seed24 -> BIP39")  # BIP39 wins, no xmr rows
    assert all(s.family != "xmr" for s in seqs)


def test_xmr_is_never_looked_up_online(tmp_path, monkeypatch):
    def no_network(*_a, **_k):
        raise AssertionError("network used for xmr")
    monkeypatch.setattr(W, "_session", no_network)
    inp = tmp_path / "s.txt"
    inp.write_text(MNEMONIC + "\n")
    out = tmp_path / "addrs.csv"
    W.main(["derive", "--in", str(inp), "--out", str(out)])
    rows = list(csv.DictReader(open(out)))
    assert [r["family"] for r in rows] == ["xmr"] and rows[0]["address"] == ADDRESS


def test_report_has_monero_section_and_no_false_no_history(tmp_path, capsys):
    rows = [{"line": "1", "source": "monero-seed", "family": "xmr",
             "type": "primary-address", "path": "monero account 0", "address": ADDRESS}]
    W.report(rows, {}, {}, str(tmp_path / "b.csv"))
    out = capsys.readouterr().out
    assert "[5] MONERO - primary address derived offline, NOT checked online" in out
    assert ADDRESS in out and "monero-wallet-cli" in out
    assert "line(s): -" in out.split("[3] NO HISTORY AT ALL")[1].split("[4]")[0]
    assert "line 1" not in out.split("[1] BALANCES FOUND")[1].split("[2]")[0]  # not a balance hit


def test_derive_output_never_contains_mnemonic_words(tmp_path, capsys):
    inp = tmp_path / "s.txt"
    inp.write_text(MNEMONIC + "\n")
    out = tmp_path / "addrs.csv"
    W.main(["derive", "--in", str(inp), "--out", str(out)])
    printed = capsys.readouterr()
    for frag in ("fawns bowling", "goggles paddles", MNEMONIC[:30]):
        assert frag not in printed.out + printed.err
        assert frag not in out.read_text()

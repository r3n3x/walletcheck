"""Published test vectors: BIP44/49/84/86, Ethereum, BIP173, and Electrum's own test suite
(spesmilo/electrum tests/test_wallet_vertical.py)."""
import pytest

from conftest import derive_lines

ABANDON = "abandon " * 11 + "about"


@pytest.mark.parametrize("path,addr", [
    ("m/44'/0'/0'/0/0", "1LqBGSKuX5yYUonjxT5qGfpUsXKYYWeabA"),
    ("m/49'/0'/0'/0/0", "37VucYSaXLCAsxYyAPfbSi9eh4iEcbShgf"),
    ("m/84'/0'/0'/0/0", "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"),
    ("m/86'/0'/0'/0/0", "bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr"),
    ("m/44'/60'/0'/0/0", "0x9858EfFD232B4033E47d90003D41EC34EcaEda94"),
])
def test_bip39_vectors(b, path, addr):
    rows, _ = derive_lines(b, [ABANDON], 1, 1, 1)
    assert (path, addr) in {(r[4], r[5]) for r in rows}


def test_bip173_private_key_one(b):
    # BIP173: the P2WPKH address for the private key 1
    rows, _ = derive_lines(b, ["00" * 31 + "01"])
    assert "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4" in {r[5] for r in rows}


@pytest.mark.parametrize("words,receive0,change0", [
    ("cycle rocket west magnet parrot shuffle foot correct salt library feed song",
     "1NNkttn1YvVGdqBW4PR6zvc3Zx3H5owKRf", "1KSezYMhAJMWqFbVFB2JshYg69UpmEXR4D"),
    ("bitter grass shiver impose acquire brush forget axis eager alone wine silver",
     "bc1q3g5tmkmlvxryhh843v4dz026avatc0zzr6h3af", "bc1qdy94n2q5qcp0kg7v9yzwe6wvfkhnvyzje7nx2p"),
    ("powerful random nobody notice nothing important anyway look away hidden message over",
     "1FJEEB8ihPMbzs2SkLmr37dHyRFzakqUmo", "1KRW8pH6HFHZh889VDq6fEKvmrsmApwNfe"),
    ("treat dwarf wealth gasp brass outside high rent blood crowd make initial",
     "16j7Dqk3Z9DdTdBtHcCVLaNQy9MTgywUUo", "1GG5bVeWgAp5XW7JLCphse14QaC4qiHyWn"),
])
def test_electrum_official_vectors(b, words, receive0, change0):
    rows, _ = derive_lines(b, [words], 1, 1, 1)
    addrs = {r[5] for r in rows}
    assert receive0 in addrs and change0 in addrs


def test_electrum_seed_with_extension(b):
    # Electrum test_electrum_seed_segwit_passphrase uses a unicode passphrase; check plain ASCII
    # extension changes the wallet (different addresses than without).
    words = "bitter grass shiver impose acquire brush forget axis eager alone wine silver"
    plain, _ = derive_lines(b, [words], 1, 1, 1)
    ext, _ = derive_lines(b, [words + " | my extension"], 1, 1, 1)
    assert {r[5] for r in plain}.isdisjoint({r[5] for r in ext})


def test_abbreviated_seed_is_expanded(b):
    abbreviated = " ".join(w[:4] for w in ABANDON.split())
    rows, rejected = derive_lines(b, [abbreviated], 1, 1, 1)
    assert not rejected
    assert "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu" in {r[5] for r in rows}


def test_invalid_inputs_are_rejected(b):
    rows, rejected = derive_lines(b, [
        "abandon " * 12,                        # all real words, bad checksum
        "hello world this is not a seed",       # random note
        "xpub" + "1" * 107,                     # broken extended key
    ])
    assert rows == [] and rejected == [1, 2, 3]

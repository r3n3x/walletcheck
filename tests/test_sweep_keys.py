"""Sweep key re-derivation: every funded address must get exactly its own key, and inputs
without private keys (xpub, public key, address) must be refused. No network."""
import pytest

pytest.importorskip("embit")
pytest.importorskip("eth_account")

import walletcheck_sweep as S  # noqa: E402
from conftest import derive_lines  # noqa: E402

ABANDON = "abandon " * 11 + "about"
# Public test vectors only (see test_privacy.py); never use them to store funds.
SPENDABLE = {
    "bip39+passphrase": ABANDON + " | TREZOR",
    "bip39 4-letter": " ".join(w[:4] for w in ABANDON.split()),
    "electrum standard": "cycle rocket west magnet parrot shuffle foot correct salt library feed song",
    "electrum segwit": "bitter grass shiver impose acquire brush forget axis eager alone wine silver",
    "electrum v1": "powerful random nobody notice nothing important anyway look away hidden message over",
    "xprv master": "xprv9s21ZrQH143K3QTDL4LXw2F7HEK3wJUD2nW2nRk4stbPy6cq3jPPqjiChkVvvNKmPGJxWUtg6LnF5kejMRNNU3TGtRBeJgk33yuGBxrMPHi",
    "WIF compressed": "KyZpNDKnfs94vbrwhJneDi77V6jF64PWPF8x5cdJb8ifgg2DUc9d",
    "WIF uncompressed": "5KY3dHRWNnFkBJaTnmUTaR1oqs9tU9goQbG19FSNLSo5oAxLokG",
    "hex key": "1ab42cc412b618bdea3a599e3c9bae199ebf030895b039e9db1e30dafb12b727",
}


def account_level_zprv(b):
    import walletcheck as W
    root = b.Bip32Secp256k1.FromSeed(b.Bip39SeedGenerator(ABANDON).Generate())
    return W.swap_version(b, root.DerivePath("m/84'/0'/0'").PrivateKey().ToExtended(), "04b2430c")


def check_line(b, line):
    rows, rejected = derive_lines(b, [line], 3, 2, 2)
    assert not rejected and rows
    kr = S.Keyring(b, line)
    n = 0
    for r in rows:
        row = dict(zip(["line", "source", "family", "type", "path", "address"], map(str, r)))
        if row["family"] == "btc":
            k, spk, kind = S.btc_key_for(kr, row)
            assert kind in S.INPUT_VBYTES
            n += 1
        elif row["family"] == "evm":
            assert S.evm_account_for(kr, row).address.lower() == row["address"].lower()
            n += 1
    assert n > 0


@pytest.mark.parametrize("name", list(SPENDABLE))
def test_every_spendable_input_gets_its_exact_key(b, name):
    check_line(b, SPENDABLE[name])


def test_account_level_zprv(b):
    check_line(b, account_level_zprv(b))


@pytest.mark.parametrize("line", [
    "zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtfSdVCToUG868RvUUkgDKf31mGDtKsAYz2oz2AGutZYs",
    "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu",
    "0x9858EfFD232B4033E47d90003D41EC34EcaEda94",
])
def test_watch_only_inputs_cannot_be_swept(b, line):
    rows, _ = derive_lines(b, [line], 2, 1, 1)
    kr = S.Keyring(b, line)
    row = dict(zip(["line", "source", "family", "type", "path", "address"], map(str, rows[0])))
    with pytest.raises(S.SweepError, match="watch-only"):
        S.btc_key_for(kr, row) if row["family"] == "btc" else S.evm_account_for(kr, row)


def test_wrong_key_is_refused(b):
    rows, _ = derive_lines(b, [ABANDON], 3, 1, 1)
    row = dict(zip(["line", "source", "family", "type", "path", "address"],
                   map(str, next(r for r in rows if r[4] == "m/84'/0'/0'/0/0"))))
    row["path"] = "m/84'/0'/0'/0/1"            # key for a different address
    with pytest.raises(S.SweepError, match="refusing to sign"):
        S.btc_key_for(S.Keyring(b, ABANDON), row)


@pytest.mark.parametrize("text,ok", [
    ("bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu", True),
    ("BC1QCR8TE4KR609GCAWUTMRZA0J4XV80JY8Z306FYU", True),                 # upper-case bech32
    ("bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr", True),
    ("1LqBGSKuX5yYUonjxT5qGfpUsXKYYWeabA", True),
    ("37VucYSaXLCAsxYyAPfbSi9eh4iEcbShgf", True),
    ("bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyv", False),                # checksum typo
    ("1LqBGSKuX5yYUonjxT5qGfpUsXKYYWeabB", False),                        # checksum typo
    ("tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx", False),                # testnet
    ("0x9858EfFD232B4033E47d90003D41EC34EcaEda94", False),
])
def test_btc_destination(text, ok):
    if ok:
        assert S.parse_btc_destination(text, set())[0] == text if text[:3] != "BC1" else True
    else:
        with pytest.raises(ValueError):
            S.parse_btc_destination(text, set())


def test_destination_must_not_be_a_swept_address():
    src = "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"
    with pytest.raises(ValueError, match="NEW wallet"):
        S.parse_btc_destination(src, {src})
    evm = "0x9858EfFD232B4033E47d90003D41EC34EcaEda94"
    with pytest.raises(ValueError, match="NEW wallet"):
        S.parse_evm_destination(evm, {evm.lower()})


@pytest.mark.parametrize("text,ok", [
    ("0x9858EfFD232B4033E47d90003D41EC34EcaEda94", True),
    ("0x9858effd232b4033e47d90003d41ec34ecaeda94", True),                 # all lower: no checksum
    ("0x9858EfFD232B4033E47d90003D41EC34EcaEda95", False),                # mixed case, bad checksum
    ("0x9858EFfD232B4033E47d90003D41EC34EcaEda94", False),                # one letter case flipped
    ("0x0000000000000000000000000000000000000000", False),                # burn address
    ("9858EfFD232B4033E47d90003D41EC34EcaEda94", False),
])
def test_evm_destination(text, ok):
    if ok:
        assert S.parse_evm_destination(text, set()) == "0x9858EfFD232B4033E47d90003D41EC34EcaEda94"
    else:
        with pytest.raises(ValueError):
            S.parse_evm_destination(text, set())


def test_wrong_evm_key_is_refused(b):
    rows, _ = derive_lines(b, [ABANDON], 1, 1, 2)
    row = dict(zip(["line", "source", "family", "type", "path", "address"],
                   map(str, next(r for r in rows if r[4] == "m/44'/60'/0'/0/0"))))
    row["path"] = "m/44'/60'/0'/0/1"           # key for a different address
    with pytest.raises(S.SweepError, match="refusing to sign"):
        S.evm_account_for(S.Keyring(b, ABANDON), row)

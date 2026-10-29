"""The core promise: secrets never appear in terminal output or in any written file,
and nothing goes online when there is nothing valid to check."""
import os

import pytest

import walletcheck as W

ABANDON = "abandon " * 11 + "about"
# All values below are PUBLIC test vectors (BIP39 "legal winner" vector, Electrum test suite,
# BIP32 test vector 1, keys of the "abandon ... about" test seed). They are publicly known;
# never use them to store funds.
SECRETS = {
    "seed": "legal winner thank year wave sausage worth useful legal winner thank yellow",
    "passphrase": "Sup3rS3cretPassphrase",
    "electrum": "cycle rocket west magnet parrot shuffle foot correct salt library feed song",
    "xprv": "xprv9s21ZrQH143K3QTDL4LXw2F7HEK3wJUD2nW2nRk4stbPy6cq3jPPqjiChkVvvNKmPGJxWUtg6LnF5kejMRNNU3TGtRBeJgk33yuGBxrMPHi",
    "wif": "KyZpNDKnfs94vbrwhJneDi77V6jF64PWPF8x5cdJb8ifgg2DUc9d",
    "hexkey": "1ab42cc412b618bdea3a599e3c9bae199ebf030895b039e9db1e30dafb12b727",
}


def write_inputs(tmp_path):
    lines = [
        SECRETS["seed"] + " | " + SECRETS["passphrase"],
        SECRETS["electrum"],
        SECRETS["xprv"],
        SECRETS["wif"],
        SECRETS["hexkey"],
        "legal winner thank year wave sausage worth useful legal winner thank thank",  # bad checksum
        "this line is some random note about my wallet",
    ]
    p = tmp_path / "secrets.txt"
    p.write_text("\n".join(lines) + "\n")
    return p


def secret_fragments():
    frags = set(SECRETS.values())
    frags |= {SECRETS["seed"][:30], SECRETS["electrum"][:30], SECRETS["xprv"][4:40], SECRETS["wif"][2:30]}
    frags.add("random note about my wallet")
    return frags


@pytest.mark.parametrize("flags", [[], ["-v"], ["-q"]])
def test_derive_never_leaks_secrets(tmp_path, capsys, flags):
    inp = write_inputs(tmp_path)
    out = tmp_path / "addresses.csv"
    W.main(["derive", "--in", str(inp), "--out", str(out)] + flags)
    printed = capsys.readouterr()
    written = out.read_text()
    for frag in secret_fragments():
        assert frag not in printed.out and frag not in printed.err, f"leaked to terminal: {frag[:12]}..."
        assert frag not in written, f"leaked to file: {frag[:12]}..."
    # Only the two invalid lines are rejected
    assert "line(s) 6, 7" in printed.out


def test_scan_with_only_invalid_input_never_goes_online(tmp_path, monkeypatch, capsys):
    def no_network(*_a, **_k):
        raise AssertionError("network used")
    monkeypatch.setattr(W, "_session", no_network)
    p = tmp_path / "bad.txt"
    p.write_text("abandon " * 12 + "\n")
    os.chdir(tmp_path)
    with pytest.raises(SystemExit) as e:
        W.main(["scan", "--in", str(p)])
    assert e.value.code == 1
    assert "NO balance check was performed" in capsys.readouterr().out


def test_check_with_empty_file_fails_loudly(tmp_path, capsys):
    p = tmp_path / "addresses.csv"
    p.write_text("line,source,family,type,path,address\n")
    with pytest.raises(SystemExit) as e:
        W.main(["check", "--in", str(p), "--out", str(tmp_path / "b.csv")])
    assert e.value.code == 1
    assert "NO balance check performed" in capsys.readouterr().out


def test_failed_lookups_are_reported_not_hidden(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(W, "btc_lookup", lambda sess, ad: None)
    monkeypatch.setattr(W.time, "sleep", lambda *_: None)
    p = tmp_path / "addresses.csv"
    p.write_text("line,source,family,type,path,address\n1,address,btc,address,-,"
                 "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu\n")
    W.main(["check", "--in", str(p), "--out", str(tmp_path / "b.csv"), "--chains", "ethereum"])
    out = capsys.readouterr().out
    assert "lookup(s) FAILED" in out and "UNKNOWN, not empty" in out

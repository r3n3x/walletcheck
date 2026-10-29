"""The interactive `walletcheck sweep` command end to end: scan -> prompts -> signed plan ->
broadcast, for Bitcoin (fake Esplora) and Ethereum (in-process chain). Also checks that the
seed never appears in the output and that --dry-run and 'no' answers never broadcast."""
import builtins

import pytest

pytest.importorskip("embit")
pytest.importorskip("eth_account")
eth_tester = pytest.importorskip("eth_tester")
from embit import script  # noqa: E402
from eth_utils import to_checksum_address  # noqa: E402

import walletcheck as W  # noqa: E402
import walletcheck_sweep as S  # noqa: E402
from test_sweep_btc import FakeEsplora  # noqa: E402
from test_sweep_evm import TesterSession  # noqa: E402

ABANDON = "abandon " * 11 + "about"
BTC_SRC = "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"        # m/84'/0'/0'/0/0
EVM_SRC = "0x9858EfFD232B4033E47d90003D41EC34EcaEda94"        # m/44'/60'/0'/0/0
BTC_DEST = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
EVM_DEST = to_checksum_address("0x" + "00" * 19 + "aa")


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(W.time, "sleep", lambda *_: None)
    monkeypatch.setattr(S.time, "sleep", lambda *_: None)
    monkeypatch.chdir(tmp_path)
    # Scan: one funded BTC address and one funded ETH address, everything else unused
    monkeypatch.setattr(W, "btc_lookup", lambda sess, ad: {"sats": 80_000 if ad == BTC_SRC else 0,
                                                          "txs": 1 if ad == BTC_SRC else 0})
    monkeypatch.setattr(W, "utxo_lookup", lambda sess, fam, ad: {"sats": 0, "txs": 0})

    def evm_check(sess, chain, cfg, addrs, results):
        for ad in addrs:
            funded = ad.lower() == EVM_SRC.lower() and chain == "ethereum"
            results.setdefault(ad.lower(), {})[chain] = {"native": 0.2 if funded else 0, "nonce": 0,
                                                         "tokens": {}, "error": False}
    monkeypatch.setattr(W, "evm_check_chain", evm_check)
    # Bitcoin endpoint: real previous transaction paying the source address
    api = FakeEsplora(fee=4.0)
    api.fund(BTC_SRC, script.address_to_scriptpubkey(BTC_SRC), 80_000)
    monkeypatch.setattr(S, "Esplora", lambda sess, base: api)
    # Ethereum endpoint: in-process chain where the source holds 0.2 ETH
    t = eth_tester.EthereumTester()
    t.send_transaction({"from": t.get_accounts()[0], "to": EVM_SRC, "value": 2 * 10 ** 17, "gas": 21000})
    real_rpc = S.EvmRpc

    class Rpc(real_rpc):
        def __init__(self, sess, url):
            super().__init__(TesterSession(t), url)
    monkeypatch.setattr(S, "EvmRpc", Rpc)
    monkeypatch.setitem(S.EVM_CHAIN_IDS, "ethereum", t.backend.chain.chain_id)
    secrets = tmp_path / "secrets.txt"
    secrets.write_text(ABANDON + "\n")
    return api, t, str(secrets)


def assert_no_secrets(out):
    """Neither the seed nor any derived private key (hex or WIF) may appear in the output."""
    b = W._bip()
    root = b.Bip32Secp256k1.FromSeed(b.Bip39SeedGenerator(ABANDON).Generate())
    assert "abandon" not in out
    for path in ("m/84'/0'/0'/0/0", "m/44'/60'/0'/0/0"):
        raw = root.DerivePath(path).PrivateKey().Raw().ToBytes()
        assert raw.hex() not in out.lower()
        assert b.WifEncoder.Encode(raw, net_ver=b"\x80") not in out


def run(monkeypatch, capsys, answers, args):
    answers = iter(answers)
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))
    W.main(["sweep", "--delay", "0", "--wait", "5", "--chains", "ethereum"] + args)
    return capsys.readouterr().out


def test_full_sweep_btc_and_eth(env, monkeypatch, capsys):
    api, t, secrets = env
    out = run(monkeypatch, capsys,
              ["y", "bc1qtypo", BTC_DEST, "", "y",                 # BTC: typo is re-asked
               "y", EVM_DEST, "", "y"], ["--in", secrets])
    assert len(api.broadcasted) == 1 and "BROADCAST OK" in out
    from embit.transaction import Transaction
    tx = Transaction.parse(bytes.fromhex(api.broadcasted[0]))
    assert tx.vout[0].script_pubkey.data == script.address_to_scriptpubkey(BTC_DEST).data
    assert t.get_balance(EVM_DEST) > 19 * 10 ** 16 and "confirmed" in out
    assert_no_secrets(out)


def test_dry_run_never_broadcasts(env, monkeypatch, capsys):
    api, t, secrets = env
    out = run(monkeypatch, capsys, ["y", BTC_DEST, "", "y", EVM_DEST, ""], ["--in", secrets, "--dry-run"])
    assert api.broadcasted == [] and t.get_balance(EVM_DEST) == 0
    assert out.count("DRY RUN") == 2
    assert_no_secrets(out)


def test_answering_no_never_broadcasts(env, monkeypatch, capsys):
    api, t, secrets = env
    run(monkeypatch, capsys, ["y", BTC_DEST, "", "n", "y", EVM_DEST, "", "n"], ["--in", secrets])
    assert api.broadcasted == [] and t.get_balance(EVM_DEST) == 0


def test_sweeping_to_a_source_address_is_refused(env, monkeypatch, capsys):
    api, t, secrets = env
    out = run(monkeypatch, capsys, ["y", BTC_SRC, "", "n"], ["--in", secrets])
    assert "NEW wallet" in out and api.broadcasted == []


def test_unusual_fee_needs_typed_yes(env, monkeypatch, capsys):
    api, t, secrets = env
    api.fee = 250.0                                            # far above normal, ~35% of 80,000 sats
    out = run(monkeypatch, capsys, ["y", BTC_DEST, "", "y", "n"], ["--in", secrets])
    assert "UNUSUAL FEE" in out and api.broadcasted == []      # a plain 'y' is not enough
    out = run(monkeypatch, capsys, ["y", BTC_DEST, "", "yes", "n"], ["--in", secrets])
    assert len(api.broadcasted) == 1


def test_failed_lookups_are_listed(env, monkeypatch, capsys):
    api, t, secrets = env
    real = W.btc_lookup
    monkeypatch.setattr(W, "btc_lookup", lambda sess, ad: None if ad == "1LqBGSKuX5yYUonjxT5qGfpUsXKYYWeabA"
                        else real(sess, ad))
    out = run(monkeypatch, capsys, ["n", "n"], ["--in", secrets])
    assert "1LqBGSKuX5yYUonjxT5qGfpUsXKYYWeabA - lookup FAILED" in out

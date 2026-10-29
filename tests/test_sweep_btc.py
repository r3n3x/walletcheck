"""Bitcoin sweep, fully offline: a fake Esplora endpoint serves real previous transactions.
Every signature is verified INDEPENDENTLY of the signer (bitcoin-utils computes the sighash,
coincurve checks the signature), so a signing bug cannot pass by grading itself."""
import hashlib
import math
import os

import pytest

pytest.importorskip("embit")
pytest.importorskip("bitcoinutils")
import coincurve  # noqa: E402
from bitcoinutils.script import Script as BUScript  # noqa: E402
from bitcoinutils.setup import setup  # noqa: E402
from bitcoinutils.transactions import Transaction as BUTx  # noqa: E402
from embit import ec, script  # noqa: E402
from embit.transaction import Transaction, TransactionInput, TransactionOutput  # noqa: E402

import walletcheck_sweep as S  # noqa: E402

setup("mainnet")
KINDS = ["p2pkh", "p2pkh-u", "p2sh-p2wpkh", "p2wpkh", "p2tr"]
DEST = script.p2wpkh(ec.PrivateKey(bytes(31) + b"\x07").get_public_key())


def make_input(kind, seed_byte):
    k = ec.PrivateKey(bytes(31) + bytes([seed_byte]), compressed=(kind != "p2pkh-u"))
    spk = S._btc_script(k.get_public_key(), "p2pkh" if kind == "p2pkh-u" else kind)
    return spk.address(), k, spk, kind


class FakeEsplora:
    """Serves UTXOs backed by real (unsigned) previous transactions; can be told to lie."""

    def __init__(self, fee=5.0):
        self.fee, self.txs, self.utxo = fee, {}, {}
        self.broadcasted = []

    def fund(self, addr, spk, value, confirmed=True):
        prev = Transaction(vin=[TransactionInput(os.urandom(32), 0)], vout=[TransactionOutput(value, spk)])
        txid = prev.txid().hex()
        self.txs[txid] = prev.serialize().hex()
        self.utxo.setdefault(addr, []).append({"txid": txid, "vout": 0, "value": value,
                                               "status": {"confirmed": confirmed}})
        return txid

    def utxos(self, addr):
        return self.utxo.get(addr, [])

    def tx_hex(self, txid):
        return self.txs[txid]

    def fee_rate_1h(self):
        return self.fee

    def broadcast(self, raw):
        self.broadcasted.append(raw)
        return Transaction.parse(bytes.fromhex(raw)).txid().hex()


def verify_independently(plan):
    """Recompute every sighash with bitcoin-utils and check each signature with coincurve."""
    tx, ins = plan["tx"], plan["inputs"]
    bt = BUTx.from_raw(plan["raw"])
    spks = [BUScript.from_raw(u["spk"].data.hex()) for u in ins]
    amounts = [u["value"] for u in ins]
    for i, u in enumerate(ins):
        pub = u["key"].get_public_key()
        if u["kind"] in ("p2pkh", "p2pkh-u"):
            ss = tx.vin[i].script_sig.data
            sig, pk = ss[1:1 + ss[0]][:-1], ss[2 + ss[0]:]
            digest = bt.get_transaction_digest(i, spks[i])
            assert pk == pub.sec() and coincurve.PublicKey(pk).verify(sig, digest, hasher=None)
        elif u["kind"] in ("p2wpkh", "p2sh-p2wpkh"):
            h160 = hashlib.new("ripemd160", hashlib.sha256(pub.sec()).digest()).hexdigest()
            code = BUScript(["OP_DUP", "OP_HASH160", h160, "OP_EQUALVERIFY", "OP_CHECKSIG"])
            digest = bt.get_transaction_segwit_digest(i, code, amounts[i])
            assert coincurve.PublicKey(pub.sec()).verify(tx.vin[i].witness.items[0][:-1], digest, hasher=None)
            if u["kind"] == "p2sh-p2wpkh":
                assert tx.vin[i].script_sig.data[1:] == script.p2wpkh(pub).data
        else:
            digest = bt.get_transaction_taproot_digest(i, spks, amounts)
            assert coincurve.PublicKeyXOnly(u["spk"].data[2:]).verify(tx.vin[i].witness.items[0], digest)


def all_kinds_plan(fee=5.0, values=None):
    api = FakeEsplora(fee)
    inputs = []
    for n, kind in enumerate(KINDS):
        addr, k, spk, kd = make_input(kind, n + 1)
        api.fund(addr, spk, (values or {}).get(kind, 20_000 + n * 1000))
        inputs.append((addr, k, spk, kd))
    return api, inputs, S.build_btc_sweep(api, inputs, DEST, fee)


def test_all_input_types_signed_correctly():
    _, _, plan = all_kinds_plan()
    verify_independently(plan)
    tx = plan["tx"]
    assert len(tx.vout) == 1 and tx.vout[0].script_pubkey.data == DEST.data
    assert all(i.sequence == 0xFFFFFFFD for i in tx.vin)            # replace-by-fee possible


def test_independent_verifier_catches_a_wrong_signature():
    _, _, plan = all_kinds_plan()
    plan["inputs"][3]["value"] += 1                                # sighash now commits to a wrong amount
    with pytest.raises(AssertionError):
        verify_independently(plan)


def test_fee_and_amount():
    _, _, plan = all_kinds_plan(fee=7.0)
    n = len(plan["inputs"])
    assert plan["fee"] >= plan["vsize"] * 7.0                      # never below the target rate
    assert plan["fee"] <= math.ceil((plan["vsize"] + 2 * n) * 7.0) # and at most ~1 vB margin per input
    assert plan["out_value"] == plan["total"] - plan["fee"]
    assert plan["tx"].vout[0].value == plan["out_value"]


def test_unconfirmed_and_uneconomic_outputs_are_skipped():
    api = FakeEsplora(10.0)
    addr, k, spk, kind = make_input("p2wpkh", 9)
    api.fund(addr, spk, 50_000)
    api.fund(addr, spk, 40_000, confirmed=False)
    api.fund(addr, spk, 600)                                       # costs ~680 sats to spend at 10 sat/vB
    plan = S.build_btc_sweep(api, [(addr, k, spk, kind)], DEST, 10.0)
    assert plan["total"] == 50_000
    assert plan["skipped_unconfirmed"] == 40_000 and plan["skipped_uneconomic"] == 600


def test_dust_result_is_refused():
    api = FakeEsplora(5.0)
    addr, k, spk, kind = make_input("p2pkh-u", 11)
    api.fund(addr, spk, 1_500)        # ~1,110 sats fee at 5 sat/vB leaves ~390 < 546 dust limit
    with pytest.raises(S.SweepError, match="dust"):
        S.build_btc_sweep(api, [(addr, k, spk, kind)], DEST, 5.0)


@pytest.mark.parametrize("lie", ["amount", "txid", "script"])
def test_lying_endpoint_is_caught(lie):
    api = FakeEsplora(5.0)
    addr, k, spk, kind = make_input("p2wpkh", 12)
    txid = api.fund(addr, spk, 30_000)
    if lie == "amount":
        api.utxo[addr][0]["value"] = 3_000_000                      # claims more than the real output
    elif lie == "txid":
        other = api.fund("x", spk, 30_000)
        api.txs[txid] = api.txs[other]                             # serves a different transaction
    else:
        foreign = script.p2wpkh(ec.PrivateKey(bytes(31) + b"\x63").get_public_key())
        api.txs[txid] = Transaction(vin=[TransactionInput(os.urandom(32), 0)],
                                    vout=[TransactionOutput(30_000, foreign)]).serialize().hex()
        api.utxo[addr][0]["txid"] = Transaction.parse(bytes.fromhex(api.txs[txid])).txid().hex()
        api.txs[api.utxo[addr][0]["txid"]] = api.txs[txid]
    with pytest.raises(S.SweepError):
        S.build_btc_sweep(api, [(addr, k, spk, kind)], DEST, 5.0)


def test_nothing_spendable_is_an_error():
    api = FakeEsplora(5.0)
    addr, k, spk, kind = make_input("p2wpkh", 13)
    with pytest.raises(S.SweepError, match="no confirmed outputs"):
        S.build_btc_sweep(api, [(addr, k, spk, kind)], DEST, 5.0)


# ---- regression tests for the independent review findings ----
def test_duplicate_outputs_from_endpoint_are_used_once():
    api = FakeEsplora(5.0)
    addr, k, spk, kind = make_input("p2wpkh", 21)
    api.fund(addr, spk, 30_000)
    api.utxo[addr].append(dict(api.utxo[addr][0]))           # endpoint lists the same output twice
    plan = S.build_btc_sweep(api, [(addr, k, spk, kind)], DEST, 5.0)
    assert len(plan["inputs"]) == 1 and plan["total"] == 30_000
    verify_independently(plan)


def test_transaction_stays_below_standard_size(monkeypatch):
    monkeypatch.setattr(S, "MAX_TX_VBYTES", 11 + 43 + 3 * 68)  # room for exactly 3 p2wpkh inputs
    api = FakeEsplora(1.0)
    addr, k, spk, kind = make_input("p2wpkh", 22)
    for v in (10_000, 20_000, 30_000, 40_000, 50_000):
        api.fund(addr, spk, v)
    plan = S.build_btc_sweep(api, [(addr, k, spk, kind)], DEST, 1.0)
    assert sorted(u["value"] for u in plan["inputs"]) == [30_000, 40_000, 50_000]   # largest first
    assert plan["skipped_over_limit"] == 30_000
    assert plan["vsize"] <= S.MAX_TX_VBYTES


def test_malformed_base58_destination_is_refused():
    from embit.base58 import encode_check
    bad = encode_check(b"\x00" + bytes(range(21)))          # valid checksum, 21-byte payload
    with pytest.raises(ValueError, match="malformed"):
        S.parse_btc_destination(bad, set())

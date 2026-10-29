"""Regression tests: a failed lookup must never look like an empty wallet.
All lookups are mocked - no network."""
import io
import os
import contextlib

import pytest

import walletcheck as W

ADDR = "0x9858EfFD232B4033E47d90003D41EC34EcaEda94"
BTC = "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"
USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(W.time, "sleep", lambda *_: None)


def cfg(tokens=None):
    return {"symbol": "ETH", "rpcs": ["http://unused"], "tokens": tokens or {}}


def test_partial_rpc_failure_is_not_reported_as_empty(monkeypatch):
    # eth_getBalance errors inside an otherwise successful batch (result None)
    def batch(sess, rpcs, calls):
        return [None if m == "eth_getBalance" else "0x0" for m, _ in calls]
    monkeypatch.setattr(W, "rpc_batch", batch)
    res = {}
    W.evm_check_chain(None, "ethereum", cfg(), [ADDR], res)
    entry = res[ADDR.lower()]["ethereum"]
    assert entry["error"] is True
    assert entry["native"] is None


def test_failed_token_decimals_are_not_silently_dropped(monkeypatch):
    # decimals() fails, so the USDC balance is unknown and must be flagged
    def batch(sess, rpcs, calls):
        out = []
        for m, p in calls:
            if m == "eth_call" and p[0]["data"] == "0x313ce567":
                out.append(None)
            elif m == "eth_call":
                out.append(hex(5_000_000 * 10 ** 6))
            elif m == "eth_getBalance":
                out.append("0x0")
            else:
                out.append("0x1")
        return out
    monkeypatch.setattr(W, "rpc_batch", batch)
    res = {}
    W.evm_check_chain(None, "ethereum", cfg({"USDC": USDC}), [ADDR], res)
    entry = res[ADDR.lower()]["ethereum"]
    assert entry["error"] is True
    assert "USDC" not in entry["tokens"]


def test_unknown_chain_name_is_rejected(capsys):
    with pytest.raises(SystemExit) as e:
        W.main(["check", "--in", "/nonexistent.csv", "--chains", "ethereum_typo"])
    assert "Unknown EVM chain(s): ethereum_typo" in str(e.value)


def test_failed_btc_lookup_is_not_listed_as_no_history(tmp_path, capsys):
    rows = [{"line": "1", "source": "address", "family": "btc", "type": "address",
             "path": "-", "address": BTC}]
    W.report(rows, {BTC: None}, {}, str(tmp_path / "b.csv"))
    out = capsys.readouterr().out
    no_history = out.split("[3] NO HISTORY AT ALL")[1].split("[4]")[0]
    assert "line(s): -" in no_history
    assert "[4] UNKNOWN" in out and "line(s): 1" in out.split("[4] UNKNOWN")[1]


def test_partial_failure_with_found_balance_is_still_reported(tmp_path, capsys):
    rows = [{"line": "1", "source": "address", "family": "evm", "type": "address",
             "path": "-", "address": ADDR}]
    evm = {ADDR.lower(): {"ethereum": {"native": 1.5, "nonce": None, "tokens": {}, "error": True}}}
    W.report(rows, {}, evm, str(tmp_path / "b.csv"))
    out = capsys.readouterr().out
    assert "[1] BALANCES FOUND" in out and "1.5 ETH" in out
    assert "lookup(s) FAILED" in out

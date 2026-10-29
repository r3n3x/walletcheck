import argparse
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import walletcheck as W  # noqa: E402


@pytest.fixture(scope="session")
def b():
    return W._bip()


def derive_args(receive=6, change=3, eth=4):
    return argparse.Namespace(btc_receive=receive, btc_change=change, eth_count=eth)


def derive_lines(b, lines, receive=6, change=3, eth=4):
    """Run the real classification + fixed expansion on input lines; returns rows."""
    a = derive_args(receive, change, eth)
    seqs, _, rejected = W.parse_inputs(b, lines, a)
    return W.expand_static(seqs, a), rejected


@pytest.fixture(autouse=True)
def isolated_token_lists(tmp_path_factory, monkeypatch):
    """Never read the developer's real ~/.config/walletcheck/tokens.csv during tests, and restore
    the built-in token configuration after tests that load other lists."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("xdg")))
    saved = ({c: dict(cfg["tokens"]) for c, cfg in W.EVM_CHAINS.items()}, list(W.TOKEN_ENTRIES))
    yield
    for c, toks in saved[0].items():
        W.EVM_CHAINS[c]["tokens"] = toks
    W.TOKEN_ENTRIES = saved[1]

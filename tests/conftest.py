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

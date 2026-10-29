"""Adaptive (gap-limit) scanning, tested with a mocked lookup - no network."""
import argparse

import pytest

import walletcheck as W

ABANDON = "abandon " * 11 + "about"


def args(**kw):
    base = dict(initial=10, eth_initial=5, gap=3, max_index=1000, proxy=None, delay=0, chains=None)
    base.update(kw)
    return argparse.Namespace(**base)


class MockScanner(W.Scanner):
    def __init__(self, a, used):
        super().__init__(a)
        self.U = set(used)

    def lookup(self, rows):
        self.lookups += len(rows)

    def used(self, r):
        return r[4] in self.U

    def failed(self, r):
        return False


def seq(family="btc", kind="recv"):
    return W.Seq(1, "t", family, kind, "S", lambda i: [[1, "t", family, "x", f"S/{i}", f"S/{i}"]])


@pytest.mark.parametrize("used,expected", [
    ([], 10),            # nothing used: only the initial window
    ([0], 10),           # gap already satisfied inside the window
    ([9], 13),           # used at the edge: extend by 3
    ([9, 11], 15),
    ([9, 12, 15], 19),   # keeps following activity
    ([13], 10),          # beyond the window with no bridge: not found (documented trade-off)
])
def test_btc_gap(used, expected):
    _, n, _, _ = MockScanner(args(), [f"S/{i}" for i in used]).walk(seq())
    assert n == expected


@pytest.mark.parametrize("used,expected", [([], 5), ([4], 8)])
def test_evm_gap(used, expected):
    _, n, _, _ = MockScanner(args(), [f"S/{i}" for i in used]).walk(seq("evm", "evm"))
    assert n == expected


def test_max_index_cap():
    _, n, _, _ = MockScanner(args(max_index=12), ["S/9", "S/10", "S/11"]).walk(seq())
    assert n == 12


def test_gap_20_equals_wallet_standard():
    # With --gap 20 at least 20 addresses are checked even if --initial is 10,
    # which matches the BIP44 wallet-discovery standard.
    _, n, _, _ = MockScanner(args(gap=20), []).walk(seq())
    assert n == 20
    _, n, _, _ = MockScanner(args(gap=20), ["S/15"]).walk(seq())
    assert n == 36


def walk_bip84(b, used_paths):
    a = args()
    seqs = []
    root = b.Bip32Secp256k1.FromSeed(b.Bip39SeedGenerator(ABANDON).Generate(""))
    W.derive_from_root(b, root, 1, a, seqs, "t")
    queue = [s for s in seqs if s.family == "btc" and "84'" in s.desc]
    sc, visited = MockScanner(a, used_paths), []
    while queue:
        s = queue.pop(0)
        _, n, last, _ = sc.walk(s)
        s.used = last >= 0
        visited.append(s.desc.split()[0])
        if s.used:
            queue[0:0] = s.followups + (s.next_account() if s.next_account else [])
    return visited


def test_change_and_accounts_only_when_used(b):
    assert walk_bip84(b, []) == ["m/84'/0'/0'/0/*"]
    assert walk_bip84(b, ["m/84'/0'/0'/0/2"]) == ["m/84'/0'/0'/0/*", "m/84'/0'/0'/1/*", "m/84'/0'/1'/0/*"]
    assert walk_bip84(b, ["m/84'/0'/0'/0/0", "m/84'/0'/1'/0/0"])[-1] == "m/84'/0'/2'/0/*"

"""Independent cross-validation.

Random inputs of every supported format are run through walletcheck, and the full
expected address set is recomputed from the wallet standards with DIFFERENT libraries:
embit (Bitcoin) and eth-account (Ethereum), plus hashlib for Electrum's seed scheme.
walletcheck's own path labels are ignored - only addresses are compared.
"""
import hashlib
import random

import pytest

from conftest import derive_lines

embit = pytest.importorskip("embit")
eth_account = pytest.importorskip("eth_account")
from embit import bip32, bip39, script  # noqa: E402
from embit.networks import NETWORKS  # noqa: E402
from eth_account import Account  # noqa: E402
from eth_keys import keys as eth_keys  # noqa: E402

Account.enable_unaudited_hdwallet_features()
NET = NETWORKS["main"]
RECV, CHG, ETHN = 6, 3, 4
T4 = ["p2pkh", "p2sh-p2wpkh", "p2wpkh", "p2tr"]


def btc(pub, t):
    return {"p2pkh": lambda: script.p2pkh(pub), "p2sh-p2wpkh": lambda: script.p2sh(script.p2wpkh(pub)),
            "p2wpkh": lambda: script.p2wpkh(pub), "p2tr": lambda: script.p2tr(pub)}[t]().address(NET)


def uncompressed(pub):
    pub.compressed = False
    raw, addr = pub.sec()[1:], script.p2pkh(pub).address(NET)
    pub.compressed = True
    return raw, addr


def evm(pub):
    return eth_keys.PublicKey(uncompressed(pub)[0]).to_checksum_address()


def expect_seed(m, pp):
    root = bip32.HDKey.from_seed(bip39.mnemonic_to_seed(m, password=pp))
    E = set()
    for purpose, t in ((44, "p2pkh"), (49, "p2sh-p2wpkh"), (84, "p2wpkh"), (86, "p2tr")):
        for c, n in ((0, RECV), (1, CHG)):
            for i in range(n):
                E.add(btc(root.derive(f"m/{purpose}h/0h/0h/{c}/{i}").key.get_public_key(), t))
    for i in range(ETHN):
        for path in (f"m/44'/60'/0'/0/{i}", f"m/44'/60'/{i}'/0/0", f"m/44'/60'/0'/{i}"):
            E.add(Account.from_mnemonic(m, passphrase=pp, account_path=path).address)
    return E


def expect_account(node, types, with_evm):
    E = {btc(node.derive([c, i]).key, t) for c, n in ((0, RECV), (1, CHG)) for i in range(n) for t in types}
    if with_evm:
        E |= {evm(node.derive([0, i]).key) for i in range(ETHN)}
    return E


def build_cases():
    import bip_utils as bu  # only used to GENERATE random test inputs
    rnd = random.Random(1234)
    cases = []
    for k in range(6):
        m = bu.Bip39MnemonicGenerator().FromWordsNumber(rnd.choice([12, 24])).ToStr()
        pp = f"pass {k}!" if k % 2 else ""
        cases.append((m + (f" | {pp}" if pp else ""), expect_seed(m, pp)))
        if k < 2:
            root = bip32.HDKey.from_seed(bip39.mnemonic_to_seed(m, password=pp))
            a44, a49, a84 = (root.derive(f"m/{p}h/0h/0h") for p in (44, 49, 84))
            ver = lambda h: bytes.fromhex(h)  # noqa: E731
            cases += [
                (a44.to_public().to_base58(version=ver("0488b21e")), expect_account(a44.to_public(), T4, True)),
                (a84.to_public().to_base58(version=ver("04b24746")), expect_account(a84.to_public(), ["p2wpkh"], False)),
                (a49.to_public().to_base58(version=ver("049d7cb2")),
                 expect_account(a49.to_public(), ["p2sh-p2wpkh"], False)),
                (a84.to_base58(version=ver("04b2430c")), expect_account(a84.to_public(), ["p2wpkh"], False)),
            ]
            pk = root.derive("m/84h/0h/0h/0/0").key
            pub = pk.get_public_key()
            cases.append((pk.wif(NET), {btc(pub, t) for t in T4} | {evm(pub)}))
            epk = root.derive("m/44h/60h/0h/0/0").key
            epub = epk.get_public_key()
            cases.append(("0x" + epk.secret.hex(),
                          {btc(epub, t) for t in T4} | {uncompressed(epub)[1], Account.from_key(epk.secret).address}))
            cases.append((epub.sec().hex(), {btc(epub, t) for t in T4} | {evm(epub)}))
    E2 = bu.ElectrumV2MnemonicTypes
    for k in range(4):
        std = k % 2 == 0
        m = bu.ElectrumV2MnemonicGenerator(E2.STANDARD if std else E2.SEGWIT).FromWordsNumber(12).ToStr()
        pp = "ext" if k >= 2 else ""
        root = bip32.HDKey.from_seed(hashlib.pbkdf2_hmac("sha512", m.encode(), b"electrum" + pp.encode(), 2048))
        if std:
            E = {script.p2pkh(root.derive([c, i]).key).address(NET) for c, n in ((0, RECV), (1, CHG)) for i in range(n)}
        else:
            acc = root.derive("m/0h")
            E = {script.p2wpkh(acc.derive([c, i]).key).address(NET) for c, n in ((0, RECV), (1, CHG)) for i in range(n)}
        cases.append((m + (f" | {pp}" if pp else ""), E))
    return cases


CASES = build_cases()


@pytest.mark.parametrize("idx", range(len(CASES)))
def test_matches_independent_libraries(b, idx):
    line, expected = CASES[idx]
    rows, rejected = derive_lines(b, [line], RECV, CHG, ETHN)
    assert not rejected
    assert {r[5] for r in rows} == expected

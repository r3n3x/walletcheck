#!/usr/bin/env python3
"""
walletcheck - check whether old seed phrases, keys or xpubs still hold funds,
without your secrets ever leaving your computer.

Secrets are only used locally to derive PUBLIC addresses. Only those public
addresses are sent to public block explorers / RPC nodes. No secret is ever
written to disk, printed, or transmitted.

Commands:
  scan        derive + check in one go, adaptive (recommended)
  derive      secrets -> addresses.csv with fixed counts (no network)
  check       addresses.csv -> balances and usage history
  sweep       MOVE found BTC/EVM funds to a new wallet (optional, needs walletcheck[sweep])
  selftest    verify the derivation code against published test vectors

Examples:
  walletcheck selftest
  walletcheck scan                       # hidden prompt, paste one item at a time
  walletcheck scan --in secrets.txt -v   # from a file, verbose
  walletcheck derive --in secrets.txt && walletcheck check

Checks: Bitcoin, 7 EVM chains (native coins + major tokens), Zcash/Firo transparent
addresses. Monero: address derived offline only. Sweep: Bitcoin and EVM.

Input formats (one per line in a file, '#' lines ignored):
  12-24 word seed phrase (BIP39, Electrum v1/v2), optionally "<words> | <passphrase>"
  25-word Monero seed (24 without checksum word): address derived offline, not checked online
  xpub/ypub/zpub/xprv/yprv/zprv, WIF private key, 64-hex private key,
  hex public key, BTC address (1.../3.../bc1...), EVM address (0x...)

Project: https://github.com/r3n3x/walletcheck  -  Public domain (The Unlicense).
NO WARRANTY. Use at your own risk.
"""

import argparse
import csv
import getpass
import os
import re
import sys
import time

__version__ = "1.2.0"

# Output verbosity: 0 = quiet (results only), 1 = normal, 2 = verbose (every address)
VERBOSITY = 1


def say(msg="", level=1):
    """Print msg if the current verbosity is at least `level`."""
    if VERBOSITY >= level:
        print(msg, flush=True)


def banner(lines):
    """Loud warning block - always printed, even in quiet mode."""
    print("\n" + "!" * 72)
    for line in lines:
        print(f"!!! {line}")
    print("!" * 72, flush=True)

# --------------------------------------------------------------------------
# Config: EVM chains, RPC endpoints (tried in order), tokens to check.
# Add chains/tokens freely. Token decimals are read on-chain.
# --------------------------------------------------------------------------
EVM_CHAINS = {
    "ethereum": {
        "symbol": "ETH",
        "rpcs": ["https://ethereum-rpc.publicnode.com", "https://eth.drpc.org", "https://eth.llamarpc.com"],
        "tokens": {
            "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
            "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
            "DAI": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
            "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
            "WBTC": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
        },
    },
    "arbitrum": {
        "symbol": "ETH",
        "rpcs": ["https://arbitrum-one-rpc.publicnode.com", "https://arb1.arbitrum.io/rpc", "https://arbitrum.drpc.org"],
        "tokens": {
            "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            "USDC.e": "0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8",
            "USDT": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",
            "ARB": "0x912CE59144191C1204E64559FE8253a0e49E6548",
        },
    },
    "polygon": {
        "symbol": "POL",
        "rpcs": ["https://polygon-bor-rpc.publicnode.com", "https://polygon.drpc.org"],
        "tokens": {
            "USDC": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
            "USDC.e": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
            "USDT": "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",
        },
    },
    "base": {
        "symbol": "ETH",
        "rpcs": ["https://base-rpc.publicnode.com", "https://mainnet.base.org", "https://base.drpc.org"],
        "tokens": {"USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"},
    },
    "optimism": {
        "symbol": "ETH",
        "rpcs": ["https://optimism-rpc.publicnode.com", "https://mainnet.optimism.io", "https://optimism.drpc.org"],
        "tokens": {
            "USDC": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",
            "OP": "0x4200000000000000000000000000000000000042",
        },
    },
    "bsc": {
        "symbol": "BNB",
        "rpcs": ["https://bsc-rpc.publicnode.com", "https://bsc-dataseed.binance.org", "https://bsc.drpc.org"],
        "tokens": {
            "USDT": "0x55d398326f99059fF775485246999027B3197955",
            "USDC": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
        },
    },
    "avalanche": {
        "symbol": "AVAX",
        "rpcs": ["https://avalanche-c-chain-rpc.publicnode.com", "https://api.avax.network/ext/bc/C/rpc", "https://avalanche.drpc.org"],
        "tokens": {},
    },
}

BTC_APIS = ["https://mempool.space/api", "https://blockstream.info/api"]

# Transparent (t-address / P2PKH) Zcash and Firo. Shielded addresses are out of scope:
# they need viewing keys and a light-client scan, so they cannot be checked privately.
# p2pkh = mainnet version bytes (Zcash chainparams PUBKEY_ADDRESS {0x1C,0xB8}; Firo PUBKEY_ADDRESS 82).
UTXO_CHAINS = {
    "zec": {"name": "Zcash", "symbol": "ZEC", "coin": 133, "p2pkh": b"\x1c\xb8",
            "api": "https://api.blockchair.com/zcash/dashboards/address/{addr}?limit=0"},
    "firo": {"name": "Firo", "symbol": "FIRO", "coin": 136, "p2pkh": b"\x52",
             "api": "https://explorer.firo.org/insight-api-zcoin/addr/{addr}"},
}

# Extended key version bytes (mainnet)
XPUB_VERS = {"xpub": "0488b21e", "ypub": "049d7cb2", "zpub": "04b24746"}
XPRV_VERS = {"xprv": "0488ade4", "yprv": "049d7878", "zprv": "04b2430c"}

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
RE_EVM_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
RE_BTC_LEGACY = re.compile(r"^[13][" + B58 + r"]{25,34}$")
RE_BTC_BECH32 = re.compile(r"^bc1[ac-hj-np-z02-9]{11,87}$")
RE_HEX64 = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")
RE_WIF = re.compile(r"^[5KL][" + B58 + r"]{50,51}$")


# ==========================================================================
# DERIVE (offline)
# ==========================================================================
def _bip():
    try:
        import bip_utils  # noqa
        return bip_utils
    except ImportError:
        sys.exit('Missing dependency. Run: pip install "bip-utils>=2.9,<3" "requests[socks]"')


def btc_addrs_from_pub(b, pub, types):
    """pub: IPublicKey. Returns list of (script_type, address)."""
    out = []
    for t in types:
        if t == "p2pkh":
            out.append((t, b.P2PKHAddrEncoder.EncodeKey(pub, net_ver=b"\x00")))
        elif t == "p2pkh-uncompressed":
            out.append(("p2pkh", b.P2PKHAddrEncoder.EncodeKey(
                pub, net_ver=b"\x00", pub_key_mode=b.P2PKHPubKeyModes.UNCOMPRESSED)))
        elif t == "p2sh-p2wpkh":
            out.append((t, b.P2SHAddrEncoder.EncodeKey(pub, net_ver=b"\x05")))
        elif t == "p2wpkh":
            out.append((t, b.P2WPKHAddrEncoder.EncodeKey(pub, hrp="bc", wit_ver=0)))
        elif t == "p2tr":
            out.append((t, b.P2TRAddrEncoder.EncodeKey(pub, hrp="bc")))
    return out


def eth_addr(b, pub):
    return b.EthAddrEncoder.EncodeKey(pub)


ALL_BTC = ["p2pkh", "p2sh-p2wpkh", "p2wpkh", "p2tr"]
BIP_PURPOSE = {44: "p2pkh", 49: "p2sh-p2wpkh", 84: "p2wpkh", 86: "p2tr"}


class Seq:
    """One ordered address sequence (a wallet 'chain', e.g. BIP84 account 0 receive).
    fn(i) -> list of rows [item, label, family, type, path, address] for index i.
    kind: 'recv' | 'change' | 'evm' | 'static'
    followups: sequences that only matter if this one was used (e.g. change chain).
    next_account: callable -> list[Seq] for the next account (adaptive scan only)."""

    def __init__(self, item, label, family, kind, desc, fn, followups=None, next_account=None):
        self.item, self.label, self.family, self.kind, self.desc, self.fn = item, label, family, kind, desc, fn
        self.followups = followups or []
        self.next_account = next_account
        self.used = False


MAX_ACCOUNTS = 20


def _chain_seqs(b, item, label, node, chain_types, base_desc, next_account=None):
    """Receive (chain 0) + change (chain 1) sequences for one account-level BIP32 node.
    chain_types: list of BTC script types; one sequence pair per type."""
    out = []
    for t in chain_types:
        def mk(chain, t=t):
            ch = node.ChildKey(chain)
            return lambda i: [[item, label, "btc", t if t != "p2pkh-uncompressed" else "p2pkh",
                               f"{base_desc}/{chain}/{i}", addr]
                              for _, addr in btc_addrs_from_pub(b, ch.ChildKey(i).PublicKey().KeyObject(), [t])]
        change = Seq(item, label, "btc", "change", f"{base_desc}/1/* {t}", mk(1))
        out.append(Seq(item, label, "btc", "recv", f"{base_desc}/0/* {t}", mk(0), [change],
                       next_account if len(chain_types) == 1 else None))
    return out


def _utxo_account(b, root, item, label, fam, acct):
    """BIP44 account `acct` of a transparent UTXO chain: receive + change, next account on demand."""
    cfg = UTXO_CHAINS[fam]
    base = f"m/44'/{cfg['coin']}'/{acct}'"
    nxt = (lambda: _utxo_account(b, root, item, label, fam, acct + 1)) if acct + 1 < MAX_ACCOUNTS else None
    node = root.DerivePath(base)

    def mk(chain):
        ch = node.ChildKey(chain)
        return lambda i: [[item, label, fam, "p2pkh", f"{base}/{chain}/{i}",
                           b.P2PKHAddrEncoder.EncodeKey(ch.ChildKey(i).PublicKey().KeyObject(),
                                                        net_ver=cfg["p2pkh"])]]
    change = Seq(item, label, fam, "change", f"{base}/1/*", mk(1))
    return [Seq(item, label, fam, "recv", f"{base}/0/*", mk(0), [change], nxt)]


def derive_from_root(b, root, item, a, seqs, label):
    """root: Bip32Secp256k1 master (private). Standard wallet paths."""
    # Bitcoin: BIP44/49/84/86, receive + change, accounts discovered adaptively
    def account(purpose, stype, acct):
        nxt = (lambda: account(purpose, stype, acct + 1)) if acct + 1 < MAX_ACCOUNTS else None
        node = root.DerivePath(f"m/{purpose}'/0'/{acct}'")
        return _chain_seqs(b, item, label, node, [stype], f"m/{purpose}'/0'/{acct}'", nxt)

    for purpose, stype in BIP_PURPOSE.items():
        seqs.extend(account(purpose, stype, 0))
    # EVM: three common path schemes
    for scheme, tmpl in (
        ("metamask/trezor", "m/44'/60'/0'/0/{i}"),
        ("ledger-live", "m/44'/60'/{i}'/0/0"),
        ("ledger-legacy", "m/44'/60'/0'/{i}"),
    ):
        def fn(i, scheme=scheme, tmpl=tmpl):
            path = tmpl.format(i=i)
            return [[item, label, "evm", scheme, path, eth_addr(b, root.DerivePath(path).PublicKey().KeyObject())]]
        seqs.append(Seq(item, label, "evm", "evm", f"{scheme} {tmpl.replace('{i}', '*')}", fn))
    # Transparent Zcash and Firo (BIP44 accounts, same discovery rules as BTC)
    for fam in UTXO_CHAINS:
        seqs.extend(_utxo_account(b, root, item, label, fam, 0))


def swap_version(b, key_str, new_ver_hex):
    raw = b.Base58Decoder.CheckDecode(key_str)
    return b.Base58Encoder.CheckEncode(bytes.fromhex(new_ver_hex) + raw[4:])


_WL = {}


def _wordlist(b, rel):
    if rel not in _WL:
        with open(os.path.join(os.path.dirname(b.__file__), rel), encoding="utf-8") as f:
            _WL[rel] = [w.strip() for w in f if w.strip()]
    return _WL[rel]


def _valid(fn):
    try:
        return fn()
    except Exception:
        return False


def _electrum_seqs(item, lab, w, stype, base):
    def mk(chain):
        return lambda i: [[item, lab, "btc", stype, f"{base}/{chain}/{i}", w.GetAddress(chain, i)]]
    change = Seq(item, lab, "btc", "change", f"{base}/1/*", mk(1))
    return Seq(item, lab, "btc", "recv", f"{base}/0/*", mk(0), [change])


def _seed_interpretations(b, m, passphrase, item, a, seqs, n_words):
    """Derive every interpretation the phrase validates as. Returns list of labels."""
    labels = []
    pp_tag = "+passphrase" if passphrase else ""

    # BIP39 (Trezor, Ledger, MetaMask, Sparrow, BlueWallet, most wallets)
    if _valid(lambda: b.Bip39MnemonicValidator().IsValid(m)):
        root = b.Bip32Secp256k1.FromSeed(b.Bip39SeedGenerator(m).Generate(passphrase))
        lab = f"seed{n_words}-BIP39{pp_tag}"
        derive_from_root(b, root, item, a, seqs, lab)
        labels.append("BIP39")

    # Electrum 2.x+ native seeds (not BIP39)
    E2 = b.ElectrumV2MnemonicTypes
    for etype, cls, stype, base in (
        (E2.STANDARD, b.ElectrumV2Standard, "p2pkh", "m"),
        (E2.SEGWIT, b.ElectrumV2Segwit, "p2wpkh", "m/0'"),
    ):
        if _valid(lambda: b.ElectrumV2MnemonicValidator(etype).IsValid(m)):
            w = cls.FromSeed(b.ElectrumV2SeedGenerator(m).Generate(passphrase))
            lab = f"seed{n_words}-Electrum-{stype}{pp_tag}"
            seqs.append(_electrum_seqs(item, lab, w, stype, f"electrum {base}"))
            labels.append(f"Electrum-{'segwit' if stype == 'p2wpkh' else 'standard'}")
    for etype in (E2.STANDARD_2FA, E2.SEGWIT_2FA):
        if _valid(lambda: b.ElectrumV2MnemonicValidator(etype).IsValid(m)):
            labels.append("Electrum-2FA(not derivable: needs TrustedCoin cosigner)")

    # Electrum 1.x legacy seeds (12 words, own wordlist, no passphrase)
    if n_words == 12 and _valid(lambda: b.ElectrumV1MnemonicValidator().IsValid(m)):
        w = b.ElectrumV1.FromSeed(b.ElectrumV1SeedGenerator(m).Generate())
        seqs.append(_electrum_seqs(item, "seed12-ElectrumV1", w, "p2pkh", "electrum-v1 m"))
        labels.append("Electrum-v1")
    return labels


def _monero_seqs(b, words, item, seqs):
    """If the words form a valid Monero seed (25 words, or 24 without the checksum word),
    append the primary address as an offline ('xmr') sequence. Returns True on success.
    Monero balances cannot be looked up privately without the private view key, so the
    address is only derived here and the run tells the user how to check it offline."""
    if len(words) not in (24, 25):
        return False
    mn = " ".join(words)
    if not b.MoneroMnemonicValidator().IsValid(mn):
        return False
    m = b.Monero.FromSeed(b.MoneroSeedGenerator(mn).Generate())
    addr = m.PrimaryAddress()
    rows = [[item, "monero-seed", "xmr", "primary-address", "monero account 0", addr]]
    seqs.append(Seq(item, rows[0][1], "xmr", "static", "monero (not checked online)", lambda i: rows))
    return True


def derive_seed(b, words, passphrase, item, a, seqs):
    n = len(words)
    labels = _seed_interpretations(b, " ".join(words), passphrase, item, a, seqs, n)
    if labels:
        return f"seed{n} -> " + " + ".join(labels)

    # Retry with 4-letter abbreviations expanded (steel plates store only 4 letters)
    bip39 = _wordlist(b, "bip/bip39/wordlist/english.txt")
    bset = set(bip39)
    expanded = []
    for w in words:
        cands = [x for x in bip39 if x.startswith(w)] if (w not in bset and len(w) == 4) else []
        expanded.append(cands[0] if len(cands) == 1 else w)
    if expanded != words:
        labels = _seed_interpretations(b, " ".join(expanded), passphrase, item, a, seqs, n)
        if labels:
            return f"seed{n} (4-letter words expanded) -> " + " + ".join(labels)

    # Monero seed without checksum word (24 words): only if BIP39/Electrum failed
    if n == 24 and _monero_seqs(b, words, item, seqs):
        return "seed24-Monero (no checksum word)"

    # Diagnose without revealing any word: report positions only
    e1 = set(_wordlist(b, "electrum/mnemonic_v1/wordlist/english.txt"))
    bad = [i for i, w in enumerate(expanded, 1) if w not in bset]
    if not bad:
        why = (f"all {n} words are valid BIP39 words but checksum fails -> one word is wrong "
               "(but still a real word), the order is off, or a word is missing/extra")
    elif all(w in e1 for w in words) and n == 12:
        why = "words fit the old Electrum v1 list but the phrase does not validate"
    else:
        why = f"word position(s) {', '.join(map(str, bad))} not in the BIP39 English list (typo?)"
    return f"INVALID seed{n}: {why}"


def derive_item(b, line, item, a, seqs):
    """Classify one input line and append address sequences to seqs.
    Never prints or stores the secret itself. Returns a short type label."""
    s = line.strip()

    # --- seed phrase (optional "| passphrase") ---
    words_part, _, passphrase = s.partition("|")
    words = words_part.lower().split()
    if len(words) == 25 and all(w.isalpha() for w in words):
        if _monero_seqs(b, words, item, seqs):
            return "seed25-Monero"
    if len(words) in (12, 13, 15, 18, 21, 24) and all(w.isalpha() for w in words):
        return derive_seed(b, words, passphrase.strip(), item, a, seqs)

    # --- extended keys ---
    pfx = s[:4]
    if pfx in XPUB_VERS or pfx in XPRV_VERS:
        is_prv = pfx in XPRV_VERS
        std = swap_version(b, s, XPRV_VERS["xprv"] if is_prv else XPUB_VERS["xpub"])
        node = b.Bip32Secp256k1.FromExtendedKey(std)
        kind = pfx[0]  # x / y / z
        if is_prv and node.Depth().ToInt() == 0:
            derive_from_root(b, node, item, a, seqs, f"{pfx}(master)")
            return f"{pfx} master key"
        types = {"x": ALL_BTC, "y": ["p2sh-p2wpkh"], "z": ["p2wpkh"]}[kind]
        label = f"{pfx}(depth {node.Depth().ToInt()})"
        seqs.extend(_chain_seqs(b, item, label, node, types, "<key>"))
        if kind == "x":  # an xpub could also be an EVM account key (m/44'/60'/0')
            ch = node.ChildKey(0)
            seqs.append(Seq(item, label, "evm", "evm", "<key>/0/* as EVM",
                            lambda i: [[item, label, "evm", "xpub-as-evm-account", f"<key>/0/{i}",
                                        eth_addr(b, ch.ChildKey(i).PublicKey().KeyObject())]]))
        return label

    # --- single keys / addresses: one fixed set, nothing to scan sequentially ---
    rows = []
    label = _single_item(b, s, item, rows)
    if rows:
        seqs.append(Seq(item, rows[0][1], "mixed", "static", "single key/address", lambda i: rows))
    return label


def _single_item(b, s, item, rows):
    # --- WIF private key ---
    if RE_WIF.match(s):
        try:
            key_bytes, mode = b.WifDecoder.Decode(s, net_ver=b"\x80")
        except Exception:
            return "INVALID WIF key (checksum fail)"
        pub = b.Secp256k1PrivateKey.FromBytes(key_bytes).PublicKey()
        if mode == b.P2PKHPubKeyModes.UNCOMPRESSED:
            types = ["p2pkh-uncompressed"]
        else:
            types = ALL_BTC
        for t, addr in btc_addrs_from_pub(b, pub, types):
            rows.append([item, "WIF", "btc", t, "-", addr])
        rows.append([item, "WIF", "evm", "same-key", "-", eth_addr(b, pub)])
        if mode != b.P2PKHPubKeyModes.UNCOMPRESSED:  # Zcash/Firo: compressed keys only
            for fam, cfg in UTXO_CHAINS.items():
                rows.append([item, "WIF", fam, "p2pkh", "-",
                             b.P2PKHAddrEncoder.EncodeKey(pub, net_ver=cfg["p2pkh"])])
        return "WIF private key"

    # --- hex private key (EVM style, also checked as BTC) ---
    if RE_HEX64.match(s):
        try:
            pub = b.Secp256k1PrivateKey.FromBytes(bytes.fromhex(s[2:] if s.startswith("0x") else s)).PublicKey()
        except Exception:
            return "INVALID hex private key"
        rows.append([item, "hex-privkey", "evm", "same-key", "-", eth_addr(b, pub)])
        for fam, cfg in UTXO_CHAINS.items():  # compressed key (the default for this input)
            rows.append([item, "hex-privkey", fam, "p2pkh", "-",
                         b.P2PKHAddrEncoder.EncodeKey(pub, net_ver=cfg["p2pkh"])])
        for t, addr in btc_addrs_from_pub(b, pub, ALL_BTC + ["p2pkh-uncompressed"]):
            rows.append([item, "hex-privkey", "btc", t, "-", addr])
        return "hex private key"

    # --- raw public key ---
    h = s[2:] if s.startswith("0x") else s
    if re.fullmatch(r"(02|03)[0-9a-fA-F]{64}|04[0-9a-fA-F]{128}", h):
        try:
            pub = b.Secp256k1PublicKey.FromBytes(bytes.fromhex(h))
        except Exception:
            return "INVALID public key"
        types = ALL_BTC + (["p2pkh-uncompressed"] if h.startswith("04") else [])
        for t, addr in btc_addrs_from_pub(b, pub, types):
            rows.append([item, "pubkey", "btc", t, "-", addr])
        rows.append([item, "pubkey", "evm", "same-key", "-", eth_addr(b, pub)])
        if h[:2] in ("02", "03"):  # Zcash/Firo: compressed keys only
            for fam, cfg in UTXO_CHAINS.items():
                rows.append([item, "pubkey", fam, "p2pkh", "-",
                             b.P2PKHAddrEncoder.EncodeKey(pub, net_ver=cfg["p2pkh"])])
        return "public key"

    # --- plain addresses ---
    if RE_EVM_ADDR.match(s):
        rows.append([item, "address", "evm", "address", "-", s])
        return "EVM address"
    if RE_BTC_LEGACY.match(s) or RE_BTC_BECH32.match(s.lower()):
        rows.append([item, "address", "btc", "address", "-", s if RE_BTC_LEGACY.match(s) else s.lower()])
        return "BTC address"

    return f"UNRECOGNISED ({len(s)} chars) - skipped"


def read_secrets_interactive():
    print("Paste ONE item per prompt and press Enter. Input is hidden (nothing is shown).")
    print("Press Enter on an empty prompt when done.\n")
    items = []
    while True:
        v = getpass.getpass(f"Item {len(items) + 1}: ").strip()
        if not v:
            break
        words = v.split()
        if len(words) in (12, 13, 15, 18, 21, 24) and "|" not in v:
            pp = getpass.getpass("  Passphrase / seed extension for this seed (Enter = none): ")
            if pp:
                v = f"{v} | {pp}"
        items.append(v)
    print()
    return items


def read_lines(a):
    if a.infile:
        with open(a.infile, encoding="utf-8") as f:
            return [l.rstrip("\n") for l in f]
    return read_secrets_interactive()


def parse_inputs(b, lines, a):
    """Classify every input line into address sequences. Returns (seqs, n_items, rejected_lines)."""
    seqs, n, rejected = [], 0, []
    for idx, line in enumerate(lines, 1):
        if not line.strip() or line.strip().startswith("#"):
            continue
        n += 1
        before = len(seqs)
        try:
            kind = derive_item(b, line, idx, a, seqs)
        except Exception as e:  # never echo the input
            kind = f"ERROR {type(e).__name__} - skipped"
        added = len(seqs) - before
        if added == 0:
            rejected.append(idx)
        say(f"  line {idx:>3}: {kind}" + ("" if added else "\n            -> nothing to check"))
    say(f"  {n} input(s) read, {n - len(rejected)} usable, {len(rejected)} rejected.")
    return seqs, n, rejected


def expand_static(seqs, a):
    """Fixed-count expansion (derive command): account 0 only, receive + change always."""
    count = {"recv": a.btc_receive, "change": a.btc_change, "evm": a.eth_count, "static": 1}
    rows, todo = [], list(seqs)
    while todo:
        s = todo.pop(0)
        for i in range(count[s.kind]):
            rows.extend(s.fn(i))
        todo[0:0] = s.followups
    return rows


def rejected_banner(rejected):
    if rejected:
        banner([f"REJECTED, NOT CHECKED: line(s) {', '.join(map(str, rejected))}.",
                "Any 'no balance' result below says NOTHING about these inputs."])


def cmd_derive(a):
    b = _bip()
    lines = read_lines(a)

    seqs, n, rejected = parse_inputs(b, lines, a)
    rows = expand_static(seqs, a)
    uniq = {(r[2], r[5].lower()) for r in rows}
    with open(a.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["line", "source", "family", "type", "path", "address"])
        w.writerows(rows)
    if VERBOSITY >= 2:
        for r in rows:
            say(f"    line {r[0]} {r[2]:<3} {r[4]:<28} {r[5]}", 2)
    say(f"\n{n} items -> {len(rows)} rows ({len(uniq)} unique public addresses) written to {a.out}", 0)
    say("This file contains PUBLIC data only. Next: walletcheck check --in " + a.out)
    rejected_banner(rejected)
    return len(rows)


# ==========================================================================
# CHECK (online, public addresses only)
# ==========================================================================
def _session(proxy):
    try:
        import requests
    except ImportError:
        sys.exit('Missing dependency. Run: pip install "requests[socks]"')
    s = requests.Session()
    s.headers["User-Agent"] = f"walletcheck/{__version__}"
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    return s


def btc_lookup(sess, addr):
    for base in BTC_APIS:
        for attempt in range(3):
            try:
                r = sess.get(f"{base}/address/{addr}", timeout=20)
                if r.status_code == 429:
                    time.sleep(2 + attempt * 3)
                    continue
                r.raise_for_status()
                d = r.json()
                cs, ms = d["chain_stats"], d["mempool_stats"]
                conf = cs["funded_txo_sum"] - cs["spent_txo_sum"]
                unconf = ms["funded_txo_sum"] - ms["spent_txo_sum"]
                return {"sats": conf + unconf, "txs": cs["tx_count"] + ms["tx_count"]}
            except Exception:
                time.sleep(1)
    return None


def utxo_lookup(sess, fam, addr):
    """Transparent Zcash/Firo address -> {'sats', 'txs'}, or None when the lookup failed.

    Units: both explorers return the balance in the chain's smallest unit (1 coin = 10^8 units).
    Zcash: Blockchair 'balance' is in zatoshi. Verified on a funded address (t1MafeF942Pqv3uTJ1SeHTt3rf8kUM9bcmR):
    Blockchair reports 100000000000, and the funding transaction's output to that address is also
    100000000000 zatoshi = 1000 ZEC. Zcash COIN = 100000000 (src/amount.h).
    Firo: Insight 'balanceSat' is in satoshi-like units (Firo COIN = 100000000, src/amount.h).
    """
    cfg = UTXO_CHAINS[fam]
    for attempt in range(3):
        try:
            r = sess.get(cfg["api"].format(addr=addr), timeout=20)
            if r.status_code in (429, 430):  # Blockchair signals rate limits with 430
                time.sleep(2 + attempt * 3)
                continue
            r.raise_for_status()
            j = r.json()
            if fam == "zec":
                info = j["data"][addr]["address"]
                txs = info["transaction_count"]
                if txs is None:  # Blockchair leaves this null when there is no history
                    txs = 1 if info["received"] else 0
                return {"sats": int(info["balance"]), "txs": int(txs)}
            # Firo Insight: confirmed balance only; field name 'txApperances' is the API's spelling
            return {"sats": int(j["balanceSat"]), "txs": int(j["txApperances"])}
        except Exception:
            time.sleep(1)
    return None


def rpc_batch(sess, rpcs, calls):
    """calls: list of (method, params). Returns list of results (None on per-call error)."""
    payload = [{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)]
    for url in rpcs:
        try:
            r = sess.post(url, json=payload, timeout=30)
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, list):
                continue
            byid = {d.get("id"): d.get("result") for d in data}
            return [byid.get(i) for i in range(len(calls))]
        except Exception:
            continue
    return None


def _hexint(v):
    """Hex string -> int. A failed call (None) stays None; it is never coerced to 0."""
    if v is None:
        return None
    try:
        return int(v, 16) if v and v != "0x" else 0
    except (TypeError, ValueError):
        return None


def select_chains(names):
    """Validate --chains names. Unknown names are an error, never silently skipped."""
    unknown = [c for c in (names or []) if c not in EVM_CHAINS]
    if unknown:
        sys.exit(f"Unknown EVM chain(s): {', '.join(unknown)}. Valid: {', '.join(EVM_CHAINS)}")
    return [c for c in EVM_CHAINS if not names or c in names]


def balance_of_data(addr):
    return "0x70a08231" + addr[2:].lower().rjust(64, "0")


def evm_check_chain(sess, chain, cfg, addrs, results):
    tokens = cfg["tokens"]
    # token decimals once per chain
    decimals = {}
    if tokens:
        res = rpc_batch(sess, cfg["rpcs"], [("eth_call", [{"to": c, "data": "0x313ce567"}, "latest"]) for c in tokens.values()])
        for (sym, _), v in zip(tokens.items(), res or [None] * len(tokens)):
            decimals[sym] = _hexint(v)

    per_addr = 2 + len(tokens)
    chunk = max(1, 40 // per_addr)
    for k in range(0, len(addrs), chunk):
        group = addrs[k:k + chunk]
        calls = []
        for ad in group:
            calls.append(("eth_getBalance", [ad, "latest"]))
            calls.append(("eth_getTransactionCount", [ad, "latest"]))
            for c in tokens.values():
                calls.append(("eth_call", [{"to": c, "data": balance_of_data(ad)}, "latest"]))
        res = rpc_batch(sess, cfg["rpcs"], calls)
        for j, ad in enumerate(group):
            entry = results.setdefault(ad.lower(), {})
            if res is None:
                entry[chain] = {"error": True}
                continue
            sl = res[j * per_addr:(j + 1) * per_addr]
            native = _hexint(sl[0])
            nonce = _hexint(sl[1])
            toks, tok_failed = {}, False
            for (sym, _), v in zip(tokens.items(), sl[2:]):
                raw = _hexint(v)
                dec = decimals.get(sym)
                if raw is None or dec is None:
                    tok_failed = True  # unknown balance, not zero
                    continue
                if raw:
                    toks[sym] = raw / 10 ** dec
            entry[chain] = {
                "native": native / 1e18 if native is not None else None,
                "nonce": nonce,
                "tokens": toks,
                "error": native is None or nonce is None or tok_failed,
            }
        time.sleep(0.2)


def cmd_check(a):
    chains = select_chains(a.chains)  # fail fast on a typo in --chains
    sess = _session(a.proxy)
    with open(a.infile, newline="") as f:
        rows = list(csv.DictReader(f))
    btc = sorted({r["address"] for r in rows if r["family"] == "btc"})
    evm = sorted({r["address"] for r in rows if r["family"] == "evm"}, key=str.lower)
    utxo = sorted({(r["family"], r["address"]) for r in rows if r["family"] in UTXO_CHAINS})
    xmr = [r for r in rows if r["family"] == "xmr"]
    if not btc and not evm and not utxo and not xmr:
        banner([f"No addresses in {a.infile} - NO balance check performed."])
        sys.exit(1)
    say(f"Checking {len(btc)} BTC address(es) and {len(evm)} EVM address(es) "
        f"on {len(chains)} EVM chain(s) ...")
    if a.proxy:
        say(f"Using proxy {a.proxy}")
    t0 = time.time()

    btc_res = {}
    for i, ad in enumerate(btc, 1):
        btc_res[ad] = btc_lookup(sess, ad)
        if i % 10 == 0 or i == len(btc):
            say(f"  Bitcoin: {i}/{len(btc)} looked up")
        time.sleep(a.delay)

    utxo_res = {}
    for fam, ad in utxo:
        say(f"  {UTXO_CHAINS[fam]['name']}: {ad}")
        utxo_res[(fam, ad)] = utxo_lookup(sess, fam, ad)
        time.sleep(a.delay)

    evm_res = {}
    if evm:
        for chain in chains:
            say(f"  EVM: checking {chain} ...")
            evm_check_chain(sess, chain, EVM_CHAINS[chain], evm, evm_res)
    if xmr:
        say(f"  Monero: {len(xmr)} address(es) derived offline, NOT checked online")
    say(f"  Done in {time.time() - t0:.0f}s.")
    report(rows, btc_res, evm_res, a.out, utxo_res)


def fmt_amount(v):
    """Human-readable amount; tiny non-zero balances are shown as dust instead of 0.000000."""
    if not v:
        return "0"
    if v < 0.000001:
        return f"{v:.2e} (dust)"
    return f"{v:,.6f}".rstrip("0").rstrip(".")


def report(rows, btc_res, evm_res, out_path, utxo_res=None):
    utxo_res = utxo_res or {}
    """rows: dicts with line/source/family/type/path/address. Writes CSV, prints summary."""
    out_rows, hits, errors = [], [], 0
    unknown_lines = set()  # lines with a failed lookup: unknown, never 'no history'
    xmr_lines = []         # Monero: derived offline, never checked online
    for r in rows:
        ad, fam = r["address"], r["family"]
        base = [r["line"], r["source"], fam, r["type"], r["path"], ad]
        if fam == "xmr":
            out_rows.append(base + ["monero", "", "", "", "NOT CHECKED (offline)"])
            xmr_lines.append((r["line"], ad))
            continue
        if fam == "btc":
            d = btc_res.get(ad)
            if d is None:
                errors += 1
                unknown_lines.add(r["line"])
                out_rows.append(base + ["bitcoin", "", "", "", "LOOKUP FAILED"])
                say(f"    ? line {r['line']} {r['path']:<28} {ad}  bitcoin LOOKUP FAILED", 2)
                continue
            btc_amt = d["sats"] / 1e8
            out_rows.append(base + ["bitcoin", f"{btc_amt:.8f}", d["txs"], "", ""])
            say(f"    {'*' if d['sats'] else '-'} line {r['line']} {r['path']:<28} {ad}  "
                f"{btc_amt:.8f} BTC, {d['txs']} tx", 2)
            if d["sats"] or d["txs"]:
                hits.append((r["line"], "bitcoin", r["type"], r["path"], ad,
                             f"{btc_amt:.8f} BTC", f"{d['txs']} txs", d["sats"] > 0))
        elif fam in UTXO_CHAINS:
            cfg = UTXO_CHAINS[fam]
            d = utxo_res.get((fam, ad))
            if d is None:
                errors += 1
                unknown_lines.add(r["line"])
                out_rows.append(base + [cfg["name"], "", "", "", "LOOKUP FAILED"])
                say(f"    ? line {r['line']} {r['path']:<28} {ad}  {cfg['name']} LOOKUP FAILED", 2)
                continue
            amt = d["sats"] / 1e8
            out_rows.append(base + [cfg["name"], f"{amt:.8f}", d["txs"], "", ""])
            say(f"    {'*' if d['sats'] else '-'} line {r['line']} {r['path']:<28} {ad}  "
                f"{amt:.8f} {cfg['symbol']}, {d['txs']} tx", 2)
            if d["sats"] or d["txs"]:
                hits.append((r["line"], cfg["name"], r["type"], r["path"], ad,
                             f"{amt:.8f} {cfg['symbol']}", f"{d['txs']} txs", d["sats"] > 0))
        else:
            for chain, d in evm_res.get(ad.lower(), {}).items():
                sym = EVM_CHAINS[chain]["symbol"]
                tok = "; ".join(f"{k}={fmt_amount(v)}" for k, v in d.get("tokens", {}).items())
                native, nonce = d.get("native"), d.get("nonce")
                if d.get("error"):
                    errors += 1
                    unknown_lines.add(r["line"])
                    out_rows.append(base + [chain, "" if native is None else f"{native:.18f}".rstrip("0").rstrip(".") or "0",
                                            "" if nonce is None else nonce, tok, "LOOKUP FAILED (partial)"])
                    say(f"    ? line {r['line']} {r['path']:<28} {ad}  {chain} LOOKUP FAILED", 2)
                    if not (native or d.get("tokens")):
                        continue  # nothing found: stays UNKNOWN
                    # a real balance was found despite the failure: still report it
                else:
                    out_rows.append(base + [chain, f"{native:.18f}".rstrip("0").rstrip(".") or "0",
                                            nonce, tok, ""])
                if native or nonce or d.get("tokens"):
                    bal = f"{fmt_amount(native or 0)} {sym}" + (f" + {tok}" if tok else "")
                    nonce_txt = "unknown" if nonce is None else nonce  # a failed call is not 'None'
                    say(f"    {'*' if native or d.get('tokens') else '-'} line {r['line']} "
                        f"{r['path']:<28} {ad}  {chain}: {bal}, nonce {nonce_txt}", 2)
                    hits.append((r["line"], chain, r["type"], r["path"], ad, bal, f"nonce {nonce_txt}",
                                 bool(native) or bool(d.get("tokens"))))

    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["line", "source", "family", "type", "path", "address", "chain",
                    "native_balance", "tx_count_or_nonce", "tokens", "note"])
        w.writerows(out_rows)

    # De-duplicate hits (same address/chain can appear under several path labels)
    seen, funded, used = set(), [], {}
    for h in hits:
        line, chain, typ, path, ad, bal, hist, has_bal = h
        key = (line, chain, ad.lower())
        if key in seen:
            continue
        seen.add(key)
        if has_bal:
            funded.append(h)
        else:
            used.setdefault(line, set()).add(f"{chain}:{ad[:10]}")

    src = {r["line"]: r["source"] for r in rows}
    say("\n" + "=" * 72, 0)
    say("RESULTS", 0)
    say("=" * 72, 0)
    say("\n[1] BALANCES FOUND (funds you can still move)", 0)
    if not funded:
        say("    None on the checked addresses, chains and tokens.", 0)
    for line, chain, typ, path, ad, bal, hist, _ in funded:
        say(f"    line {line} [{src.get(line)}] {chain} {path}\n      {ad}\n      -> {bal} ({hist})", 0)

    say("\n[2] USED BEFORE, NOW EMPTY (the wallet was real, funds moved out)", 0)
    if not used:
        say("    None.", 0)
    for line in sorted(used, key=lambda x: int(x)):
        say(f"    line {line} [{src.get(line)}]: {len(used[line])} address/chain combination(s) with history", 0)

    never = sorted({r["line"] for r in rows} - set(used) - {f[0] for f in funded} - unknown_lines
                   - {l for l, _ in xmr_lines}, key=lambda x: int(x))
    say("\n[3] NO HISTORY AT ALL on the checked addresses", 0)
    say(f"    line(s): {', '.join(never) if never else '-'}", 0)
    if unknown_lines:
        say("\n[4] UNKNOWN - a lookup failed, these were NOT fully checked (re-run)", 0)
        say(f"    line(s): {', '.join(sorted(unknown_lines, key=lambda x: int(x)))}", 0)
    if xmr_lines:
        say("\n[5] MONERO - primary address derived offline, NOT checked online", 0)
        say("    (only the first address, account 0 index 0; subaddresses are not derived)", 0)
        for line, ad in xmr_lines:
            say(f"    line {line} [{src.get(line)}] {ad}", 0)
        say("    Monero balances cannot be checked here privately: the chain must be scanned", 0)
        say("    with the private view key, and no explorer can do that without learning it.", 0)
        say("    Check it with monero-wallet-cli connected to your own node:", 0)
        say("      --restore-deterministic-wallet   restores the FULL wallet from the seed ('balance')", 0)
        say("      --generate-from-view-key         view-only: needs the address and private view key", 0)
        say("    The wallet scans locally; only your node sees the scan. Guide: getmonero.org", 0)
        say("    resources, 'How to restore your wallet from seed'.", 0)

    say(f"\nFull per-address results: {out_path}   Lookup failures: {errors}", 0)
    if funded:
        say("Tip: keys that were stored in plain text should be treated as exposed - "
            "move any funds to a fresh wallet.", 0)
    if errors:
        banner([f"{errors} lookup(s) FAILED (see 'LOOKUP FAILED' rows in {out_path}).",
                "Those addresses are UNKNOWN, not empty. Re-run to retry."])


# ==========================================================================
# SELFTEST - published BIP test vectors ("abandon ... about" seed)
# ==========================================================================
def cmd_selftest(_a):
    b = _bip()
    m = "abandon " * 11 + "about"
    root = b.Bip32Secp256k1.FromSeed(b.Bip39SeedGenerator(m).Generate(""))
    exp = {
        "m/44'/0'/0'/0/0": ("p2pkh", "1LqBGSKuX5yYUonjxT5qGfpUsXKYYWeabA"),
        "m/49'/0'/0'/0/0": ("p2sh-p2wpkh", "37VucYSaXLCAsxYyAPfbSi9eh4iEcbShgf"),
        "m/84'/0'/0'/0/0": ("p2wpkh", "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"),
        "m/86'/0'/0'/0/0": ("p2tr", "bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr"),
    }
    ok = True
    for path, (t, want) in exp.items():
        got = btc_addrs_from_pub(b, root.DerivePath(path).PublicKey().KeyObject(), [t])[0][1]
        ok &= got == want
        print(f"{'OK ' if got == want else 'FAIL'} {path:<18} {got}")
    got = eth_addr(b, root.DerivePath("m/44'/60'/0'/0/0").PublicKey().KeyObject())
    want = "0x9858EfFD232B4033E47d90003D41EC34EcaEda94"
    ok &= got == want
    print(f"{'OK ' if got == want else 'FAIL'} m/44'/60'/0'/0/0   {got}")

    # Electrum official test vectors (spesmilo/electrum tests/test_wallet_vertical.py)
    class _A:
        btc_receive, btc_change, eth_count = 1, 1, 1
    for words, want, name in (
        ("cycle rocket west magnet parrot shuffle foot correct salt library feed song",
         "1NNkttn1YvVGdqBW4PR6zvc3Zx3H5owKRf", "Electrum standard"),
        ("bitter grass shiver impose acquire brush forget axis eager alone wine silver",
         "bc1q3g5tmkmlvxryhh843v4dz026avatc0zzr6h3af", "Electrum segwit"),
        ("powerful random nobody notice nothing important anyway look away hidden message over",
         "1FJEEB8ihPMbzs2SkLmr37dHyRFzakqUmo", "Electrum v1 (old)"),
    ):
        seqs = []
        derive_seed(b, words.split(), "", 1, _A, seqs)
        hit = want in {r[5] for r in expand_static(seqs, _A)}
        ok &= hit
        print(f"{'OK ' if hit else 'FAIL'} {name:<18} {want}")
    print("\nSELFTEST PASSED" if ok else "\nSELFTEST FAILED - do not trust derive output")
    sys.exit(0 if ok else 1)


# ==========================================================================
# SCAN - adaptive (gap-limit) derive + check
# ==========================================================================
class Scanner:
    """Looks up addresses on demand, caches results, and decides 'used'."""

    def __init__(self, a):
        self.a = a
        self.sess = _session(a.proxy)
        self.btc_res, self.evm_res, self.utxo_res = {}, {}, {}
        self.lookups = 0
        self.chains = {c: EVM_CHAINS[c] for c in select_chains(a.chains)}

    def lookup(self, rows):
        for fam, ad in dict.fromkeys((r[2], r[5]) for r in rows if r[2] in UTXO_CHAINS):
            if (fam, ad) not in self.utxo_res:
                self.utxo_res[(fam, ad)] = utxo_lookup(self.sess, fam, ad)
                self.lookups += 1
                time.sleep(self.a.delay)
        btc = [r[5] for r in rows if r[2] == "btc" and r[5] not in self.btc_res]
        evm = sorted({r[5] for r in rows if r[2] == "evm" and r[5].lower() not in self.evm_res}, key=str.lower)
        for ad in dict.fromkeys(btc):
            self.btc_res[ad] = btc_lookup(self.sess, ad)
            self.lookups += 1
            time.sleep(self.a.delay)
        if evm:
            for chain, cfg in self.chains.items():
                evm_check_chain(self.sess, chain, cfg, evm, self.evm_res)
            self.lookups += len(evm)

    def used(self, row):
        fam, ad = row[2], row[5]
        if fam in UTXO_CHAINS:
            d = self.utxo_res.get((fam, ad))
            return bool(d and (d["sats"] or d["txs"]))
        if fam == "btc":
            d = self.btc_res.get(ad)
            return bool(d and (d["sats"] or d["txs"]))
        return any(d.get("native") or d.get("nonce") or d.get("tokens")
                   for d in self.evm_res.get(ad.lower(), {}).values())

    def failed(self, row):
        if row[2] in UTXO_CHAINS:
            return self.utxo_res.get((row[2], row[5])) is None
        if row[2] == "btc":
            return self.btc_res.get(row[5]) is None
        return any(d.get("error") for d in self.evm_res.get(row[5].lower(), {}).values())

    def walk(self, s):
        """Gap-limit walk: check the first `initial` indices, then keep going while a used
        address sits within `gap` of the end. Returns (rows, n_checked, last_used, failures)."""
        a = self.a
        if s.kind == "static":
            rows = s.fn(0)
            self.lookup(rows)
            return rows, 1, (0 if any(self.used(r) for r in rows) else -1), sum(self.failed(r) for r in rows)
        initial = a.eth_initial if s.family == "evm" else a.initial
        rows, i, last, fails = [], 0, -1, 0
        while True:
            target = min(max(initial, last + 1 + a.gap), a.max_index)
            if i >= target:
                break
            batch = [(j, r) for j in range(i, target) for r in s.fn(j)]
            self.lookup([r for _, r in batch])
            for j, r in batch:
                rows.append(r)
                u = self.used(r)
                if u:
                    last = max(last, j)
                fails += self.failed(r)
                say(f"      #{j:<3} {r[5]}  {'FAILED' if self.failed(r) else ('used' if u else 'unused')}", 2)
            i = target
        return rows, i, last, fails


def scan_seqs(a, seqs):
    """Adaptive walk over all address sequences. Returns (rows, scanner, lookup_failures).
    Shared by `scan` and `sweep`."""
    sc = Scanner(a)
    all_rows, queue, total_fail = [], list(seqs), 0
    while queue:
        s = queue.pop(0)
        if s.kind != "static":
            say(f"    line {s.item:>3} {s.desc}", 2)
        rows, n_checked, last, fails = sc.walk(s)
        all_rows.extend(rows)
        total_fail += fails
        s.used = last >= 0
        state = ("OFFLINE (not checked online - see results)" if s.family == "xmr"
                 else f"USED (last used #{last})" if s.used else "unused")
        if s.kind != "static":
            say(f"  line {s.item:>3} {s.desc:<38} checked {n_checked:>3}  {state}"
                + (f"  ({fails} lookup failures)" if fails else ""))
        else:
            say(f"  line {s.item:>3} {s.desc:<38} checked {len(rows):>3}  {state}")
        if s.used:
            # change chain only matters if receive was used; next account only if this one was
            queue[0:0] = s.followups + (s.next_account() if s.next_account else [])

    return all_rows, sc, total_fail


def cmd_scan(a):
    b = _bip()
    t0 = time.time()
    say("Step 1/3 - Reading inputs (secrets stay on this computer)")
    seqs, n, rejected = parse_inputs(b, read_lines(a), a)
    if not seqs:
        rejected_banner(rejected)
        banner(["Nothing valid to check - stopped. NO balance check was performed."])
        sys.exit(1)

    say(f"\nStep 2/3 - Checking public addresses online (adaptive: first {a.initial} BTC / "
        f"{a.eth_initial} EVM per chain,")
    say(f"           continuing while a used address is within {a.gap} of the end; "
        f"change/next account only if used)")
    if a.proxy:
        say(f"           via proxy {a.proxy}")
    all_rows, sc, total_fail = scan_seqs(a, seqs)

    with open(a.addresses, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["line", "source", "family", "type", "path", "address"])
        w.writerows(all_rows)
    uniq = len({(r[2], r[5].lower()) for r in all_rows})
    say(f"\n  {uniq} unique addresses checked with {sc.lookups} online lookups "
        f"in {time.time() - t0:.0f}s. Address list: {a.addresses}")
    rejected_banner(rejected)

    say("\nStep 3/3 - Results")
    keys = ["line", "source", "family", "type", "path", "address"]
    report([{k: str(v) for k, v in zip(keys, r)} for r in all_rows], sc.btc_res, sc.evm_res, a.out,
           sc.utxo_res)
    if total_fail:
        say("NOTE: failed lookups count as 'unused' for the gap rule, so a chain may have "
            "stopped early. Re-run to be sure.", 0)


def main(argv=None):
    global VERBOSITY
    common = argparse.ArgumentParser(add_help=False)
    g = common.add_mutually_exclusive_group()
    g.add_argument("-v", "--verbose", action="store_true", help="show every address and its result")
    g.add_argument("-q", "--quiet", action="store_true", help="only show the results summary")

    p = argparse.ArgumentParser(prog="walletcheck", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"walletcheck {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def derive_opts(x):
        x.add_argument("--btc-receive", type=int, default=20, help="receive addresses per BTC chain (default 20)")
        x.add_argument("--btc-change", type=int, default=10, help="change addresses per BTC chain (default 10)")
        x.add_argument("--eth-count", type=int, default=5, help="addresses per EVM path scheme (default 5)")

    def check_opts(x):
        x.add_argument("--proxy", help="route lookups through a proxy, e.g. socks5h://127.0.0.1:9050 (Tor)")
        x.add_argument("--delay", type=float, default=0.3, help="seconds between BTC/Zcash/Firo lookups (default 0.3)")
        x.add_argument("--chains", nargs="*", metavar="CHAIN",
                      help=f"limit the EVM chains (default all): {' '.join(EVM_CHAINS)}")

    s = sub.add_parser("scan", parents=[common], help="derive + check in one run, adaptive (recommended)")
    s.add_argument("--in", dest="infile", help="secrets file (omit for a hidden prompt)")
    s.add_argument("--addresses", default="addresses.csv",
                   help="where to save the checked addresses (default addresses.csv)")
    s.add_argument("--out", default="balances.csv", help="where to save per-address results (default balances.csv)")
    s.add_argument("--initial", type=int, default=10, help="BTC addresses always checked per chain (default 10)")
    s.add_argument("--eth-initial", type=int, default=5, help="EVM addresses always checked per scheme (default 5)")
    s.add_argument("--gap", type=int, default=3,
                   help="stop after this many unused addresses follow the last used one "
                        "(default 3; wallet standard is 20)")
    s.add_argument("--max-index", type=int, default=1000, help="hard cap per chain (default 1000)")
    check_opts(s)
    s.set_defaults(fn=cmd_scan)

    d = sub.add_parser("derive", parents=[common], help="secrets -> addresses.csv, fixed counts, no network")
    d.add_argument("--in", dest="infile", help="secrets file (omit for a hidden prompt)")
    d.add_argument("--out", default="addresses.csv", help="where to save the addresses (default addresses.csv)")
    derive_opts(d)
    d.set_defaults(fn=cmd_derive)

    c = sub.add_parser("check", parents=[common], help="addresses.csv -> balances (public data only)")
    c.add_argument("--in", dest="infile", default="addresses.csv",
                   help="address list from `derive` (default addresses.csv)")
    c.add_argument("--out", default="balances.csv", help="where to save per-address results (default balances.csv)")
    check_opts(c)
    c.set_defaults(fn=cmd_check)

    w = sub.add_parser("sweep", parents=[common],
                       help="MOVE found funds to a new wallet (BTC + EVM); needs walletcheck[sweep]")
    w.add_argument("--in", dest="infile", help="secrets file (omit for a hidden prompt)")
    w.add_argument("--dry-run", action="store_true", help="build and sign, show the plan, never broadcast")
    w.add_argument("--wait", type=int, default=600, help="seconds to wait for EVM confirmations (default 600)")
    w.add_argument("--initial", type=int, default=10, help="BTC addresses always checked per chain (default 10)")
    w.add_argument("--eth-initial", type=int, default=5, help="EVM addresses always checked per scheme (default 5)")
    w.add_argument("--gap", type=int, default=3, help="unused addresses after the last used one (default 3)")
    w.add_argument("--max-index", type=int, default=1000, help="hard cap per chain (default 1000)")
    check_opts(w)
    w.set_defaults(fn=lambda args: __import__("walletcheck_sweep").cmd_sweep(args))

    t = sub.add_parser("selftest", parents=[common], help="verify derivation against published test vectors")
    t.set_defaults(fn=cmd_selftest)

    a = p.parse_args(argv)
    VERBOSITY = 2 if a.verbose else 0 if a.quiet else 1
    try:
        a.fn(a)
    except KeyboardInterrupt:
        print("\nAborted by user.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()

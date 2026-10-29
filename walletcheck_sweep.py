"""
walletcheck sweep - move funds that walletcheck found into a new wallet.

This is the only part of walletcheck that MOVES FUNDS. It is opt-in, lives in its own
module, and needs extra libraries:  pip install "walletcheck[sweep]"

How it works
  1. The same adaptive scan as `walletcheck scan` finds funded addresses.
  2. Private keys are re-derived in memory for those addresses only. Every key must
     re-produce the exact scanned address (checked with a second, independent library)
     or the sweep refuses to sign.
  3. Per chain you choose to sweep: you type the destination address and the broadcast
     endpoint, the signed plan is shown, and one y/N confirms the broadcast.
  4. Only SIGNED transactions are sent. Secrets never leave the computer.

Supported: Bitcoin (p2pkh incl. uncompressed, p2sh-p2wpkh, p2wpkh, p2tr) and the EVM chains
in walletcheck.EVM_CHAINS (native coin + configured tokens). Zcash/Firo and Monero are
reported but not swept. Watch-only inputs (xpub, public keys, addresses) cannot be swept.
"""

import math
import os
import re
import sys
import time

import walletcheck as W
from walletcheck import banner, say

DEPS_MSG = 'Sweeping needs extra libraries. Install them with:  pip install "walletcheck[sweep]"'

# Chain ids guard against a broadcast endpoint that points at the wrong network.
EVM_CHAIN_IDS = {"ethereum": 1, "arbitrum": 42161, "polygon": 137, "base": 8453,
                 "optimism": 10, "bsc": 56, "avalanche": 43114}
OP_STACK = {"base", "optimism"}                     # extra L1 data fee
GAS_PRICE_ORACLE = "0x420000000000000000000000000000000000000F"
SEL_GET_L1_FEE = "49948e0e"                         # getL1Fee(bytes)
SEL_TRANSFER = "a9059cbb"                           # transfer(address,uint256)
SEL_DECIMALS = "0x313ce567"                         # decimals()

DUST_SATS = 546
# Approximate input sizes (vbytes) used to skip outputs that cost more to spend than they hold
INPUT_VBYTES = {"p2pkh": 148, "p2pkh-u": 180, "p2sh-p2wpkh": 91, "p2wpkh": 68, "p2tr": 58}
MAX_TX_VBYTES = 95_000          # standard relay limit is 100,000 vB; keep a margin
HIGH_FEE_SHARE = 0.10           # fees above 10% of the amount need a typed 'yes'
HIGH_BTC_FEE_RATE = 100         # sat/vB above which a typed 'yes' is needed
SEED_LENGTHS = (12, 13, 15, 18, 21, 24)


class SweepError(Exception):
    """A sweep step could not be completed safely; nothing was broadcast for it."""


def _deps():
    try:
        import embit  # noqa: F401
        import eth_account  # noqa: F401
    except ImportError:
        sys.exit(DEPS_MSG)


# ==========================================================================
# Keys: re-derived in memory, verified against the scanned address
# ==========================================================================
def _expand_abbreviations(b, words):
    """Same rule as the scanner: unique 4-letter prefixes become full BIP39 words."""
    bip39 = W._wordlist(b, "bip/bip39/wordlist/english.txt")
    bset = set(bip39)
    out = []
    for w in words:
        cands = [x for x in bip39 if x.startswith(w)] if (w not in bset and len(w) == 4) else []
        out.append(cands[0] if len(cands) == 1 else w)
    return out


class Keyring:
    """Private keys for ONE input line. Built only when that line holds funds; kept in memory."""

    def __init__(self, b, line):
        self.b, self.roots, self.single = b, {}, None
        s = line.strip()
        words_part, _, passphrase = s.partition("|")
        words = words_part.lower().split()
        if len(words) in SEED_LENGTHS and all(w.isalpha() for w in words):
            for cand in (words, _expand_abbreviations(b, words)):
                self._seed(" ".join(cand), passphrase.strip(), len(words))
                if self.roots:
                    break
            return
        if s[:4] in W.XPRV_VERS:
            node = b.Bip32Secp256k1.FromExtendedKey(W.swap_version(b, s, W.XPRV_VERS["xprv"]))
            self.roots["bip32" if node.Depth().ToInt() == 0 else "account"] = node
        elif W.RE_WIF.match(s):
            self.single = b.WifDecoder.Decode(s, net_ver=b"\x80")[0]
        elif W.RE_HEX64.match(s):
            self.single = bytes.fromhex(s[2:] if s.startswith("0x") else s)

    def _seed(self, m, passphrase, n_words):
        b = self.b
        if W._valid(lambda: b.Bip39MnemonicValidator().IsValid(m)):
            self.roots["bip32"] = b.Bip32Secp256k1.FromSeed(b.Bip39SeedGenerator(m).Generate(passphrase))
        e2 = b.ElectrumV2MnemonicTypes
        for etype, cls, name in ((e2.STANDARD, b.ElectrumV2Standard, "electrum-std"),
                                 (e2.SEGWIT, b.ElectrumV2Segwit, "electrum-segwit")):
            if W._valid(lambda: b.ElectrumV2MnemonicValidator(etype).IsValid(m)):
                self.roots[name] = cls.FromSeed(b.ElectrumV2SeedGenerator(m).Generate(passphrase))
        if n_words == 12 and W._valid(lambda: b.ElectrumV1MnemonicValidator().IsValid(m)):
            self.roots["electrum-v1"] = b.ElectrumV1.FromSeed(b.ElectrumV1SeedGenerator(m).Generate())

    def secret_for(self, row):
        """32-byte private key for a scanned row, or SweepError if this input has no key for it."""
        path = row["path"]
        for pattern, root in ((r"electrum m/0'/(\d+)/(\d+)", "electrum-segwit"),
                              (r"electrum m/(\d+)/(\d+)", "electrum-std"),
                              (r"electrum-v1 m/(\d+)/(\d+)", "electrum-v1")):
            m = re.fullmatch(pattern, path)
            if m:
                w = self._root(root)
                return w.GetPrivateKey(int(m[1]), int(m[2])).Raw().ToBytes()
        m = re.fullmatch(r"<key>/(\d+)/(\d+)", path)
        if m:
            node = self._root("account")
            return node.ChildKey(int(m[1])).ChildKey(int(m[2])).PrivateKey().Raw().ToBytes()
        if path.startswith("m/"):
            return self._root("bip32").DerivePath(path).PrivateKey().Raw().ToBytes()
        if path == "-" and self.single is not None:
            return self.single
        raise SweepError("watch-only input (no private key)")

    def _root(self, name):
        if name not in self.roots:
            raise SweepError("watch-only input (no private key)")
        return self.roots[name]


def _btc_script(pub, stype):
    from embit import script
    if stype == "p2pkh":
        return script.p2pkh(pub)
    if stype == "p2sh-p2wpkh":
        return script.p2sh(script.p2wpkh(pub))
    if stype == "p2wpkh":
        return script.p2wpkh(pub)
    if stype == "p2tr":
        return script.p2tr(pub)
    return None


def btc_key_for(keyring, row):
    """embit PrivateKey + scriptPubKey + input kind for a funded BTC row. The address is
    rebuilt with embit (independent of the bip_utils scanner) and must match exactly."""
    from embit import ec
    from embit.networks import NETWORKS
    secret = keyring.secret_for(row)
    for compressed in (True, False):
        k = ec.PrivateKey(secret, compressed=compressed)
        spk = _btc_script(k.get_public_key(), row["type"])
        if spk is not None and spk.address(NETWORKS["main"]) == row["address"]:
            kind = row["type"] if compressed else "p2pkh-u"
            return k, spk, kind
    raise SweepError(f"re-derived key does not match {row['address']} - refusing to sign")


def evm_account_for(keyring, row):
    """eth_account LocalAccount for a funded EVM row; must re-produce the scanned address."""
    from eth_account import Account
    acct = Account.from_key(keyring.secret_for(row))
    if acct.address.lower() != row["address"].lower():
        raise SweepError(f"re-derived key does not match {row['address']} - refusing to sign")
    return acct


# ==========================================================================
# Destination validation
# ==========================================================================
def parse_btc_destination(text, source_addresses):
    """Validated mainnet Bitcoin destination -> (address, scriptPubKey). ValueError if unusable."""
    from embit import script
    addr = text.strip()
    if addr.lower().startswith("bc1") and addr == addr.upper():
        addr = addr.lower()                           # bech32 may be written in upper case
    if not (W.RE_BTC_LEGACY.match(addr) or W.RE_BTC_BECH32.match(addr)):
        raise ValueError("not a Bitcoin mainnet address (expected 1..., 3... or bc1...)")
    from embit.networks import NETWORKS
    try:
        spk = script.address_to_scriptpubkey(addr)
    except Exception:
        raise ValueError("address checksum is invalid - probably a typo")
    try:
        roundtrip = spk.address(NETWORKS["main"])
    except Exception:
        roundtrip = None
    if roundtrip != addr:                            # catches malformed payloads with a valid checksum
        raise ValueError("address is malformed")
    if addr.lower() in source_addresses:
        raise ValueError("this is one of the addresses being swept - use a NEW wallet")
    return addr, spk


def parse_evm_destination(text, source_addresses):
    """Validated EVM destination -> checksummed address. ValueError if unusable."""
    from eth_utils import is_checksum_address, to_checksum_address
    addr = text.strip()
    if not W.RE_EVM_ADDR.match(addr):
        raise ValueError("not an EVM address (expected 0x followed by 40 hex characters)")
    if addr[2:] != addr[2:].lower() and addr[2:] != addr[2:].upper() and not is_checksum_address(addr):
        raise ValueError("checksum (upper/lower case pattern) is wrong - probably a typo")
    if int(addr, 16) == 0:
        raise ValueError("the zero address burns funds")
    if addr.lower() in source_addresses:
        raise ValueError("this is one of the addresses being swept - use a NEW wallet")
    return to_checksum_address(addr)


# ==========================================================================
# Bitcoin
# ==========================================================================
class Esplora:
    """Minimal Esplora client (mempool.space, blockstream.info or your own instance)."""

    def __init__(self, sess, base):
        self.sess, self.base = sess, base.rstrip("/")

    def _get(self, path):
        r = self.sess.get(self.base + path, timeout=30)
        r.raise_for_status()
        return r

    def utxos(self, addr):
        return self._get(f"/address/{addr}/utxo").json()

    def tx_hex(self, txid):
        return self._get(f"/tx/{txid}/hex").text.strip()

    def fee_rate_1h(self):
        """sat/vB expected to confirm within about an hour."""
        try:
            return float(self._get("/v1/fees/recommended").json()["hourFee"])   # mempool.space
        except Exception:
            est = self._get("/fee-estimates").json()                             # plain Esplora
            for target in ("6", "5", "4", "3", "2", "1"):
                if target in est:
                    return float(est[target])
            raise SweepError("endpoint returned no fee estimates")

    def broadcast(self, raw_hex):
        r = self.sess.post(self.base + "/tx", data=raw_hex, timeout=30)
        if r.status_code != 200:
            raise SweepError(f"broadcast rejected: {r.text.strip()[:300]}")
        return r.text.strip()


def _vsize(tx):
    """Virtual size per BIP141: (3 * stripped size + total size) / 4, rounded up."""
    from embit.transaction import Transaction, TransactionInput
    full = len(tx.serialize())
    stripped = Transaction(version=tx.version, locktime=tx.locktime, vout=tx.vout,
                           vin=[TransactionInput(i.txid, i.vout, script_sig=i.script_sig, sequence=i.sequence)
                                for i in tx.vin])
    return math.ceil((3 * len(stripped.serialize()) + full) / 4)


def _sign_btc(utxos, dest_spk, out_value):
    from embit import script
    from embit.script import Script, Witness
    from embit.transaction import SIGHASH, Transaction, TransactionInput, TransactionOutput
    tx = Transaction(version=2, locktime=0,
                     vin=[TransactionInput(bytes.fromhex(u["txid"]), u["vout"], sequence=0xFFFFFFFD)
                          for u in utxos],                                  # RBF enabled
                     vout=[TransactionOutput(out_value, dest_spk)])
    spks, values = [u["spk"] for u in utxos], [u["value"] for u in utxos]
    for i, u in enumerate(utxos):
        k, pub, kind = u["key"], u["key"].get_public_key(), u["kind"]
        if kind in ("p2pkh", "p2pkh-u"):
            sig = k.sign(tx.sighash_legacy(i, spks[i])).serialize() + bytes([SIGHASH.ALL])
            tx.vin[i].script_sig = Script(bytes([len(sig)]) + sig + bytes([len(pub.sec())]) + pub.sec())
        elif kind in ("p2wpkh", "p2sh-p2wpkh"):
            sig = k.sign(tx.sighash_segwit(i, script.p2pkh(pub), values[i])).serialize() + bytes([SIGHASH.ALL])
            tx.vin[i].witness = Witness([sig, pub.sec()])
            if kind == "p2sh-p2wpkh":
                redeem = script.p2wpkh(pub).data
                tx.vin[i].script_sig = Script(bytes([len(redeem)]) + redeem)
        elif kind == "p2tr":
            h = tx.sighash_taproot(i, script_pubkeys=spks, values=values, sighash=SIGHASH.DEFAULT)
            tx.vin[i].witness = Witness([k.taproot_tweak(b"").schnorr_sign(h).serialize()])
        else:
            raise SweepError(f"unsupported input type {kind}")
    return tx


def build_btc_sweep(client, inputs, dest_spk, fee_rate):
    """inputs: list of (address, embit PrivateKey, scriptPubKey, kind).
    Every UTXO is checked against its full previous transaction (hash, script and amount),
    so an endpoint cannot misreport amounts and make the fee wrong. Returns a plan dict."""
    from embit.transaction import Transaction
    utxos, unconfirmed, uneconomic, seen = [], 0, 0, set()
    for addr, key, spk, kind in inputs:
        for u in client.utxos(addr):
            outpoint = (u["txid"], int(u["vout"]))
            if outpoint in seen:                     # an endpoint listing an output twice
                continue
            seen.add(outpoint)
            if not (u.get("status") or {}).get("confirmed"):
                unconfirmed += int(u["value"])
                continue
            prev = Transaction.parse(bytes.fromhex(client.tx_hex(u["txid"])))
            if prev.txid().hex() != u["txid"]:
                raise SweepError(f"endpoint returned a transaction that does not match id {u['txid']}")
            out = prev.vout[int(u["vout"])]
            if out.script_pubkey.data != spk.data:
                raise SweepError(f"output {u['txid']}:{u['vout']} does not belong to {addr}")
            if out.value != int(u["value"]):
                raise SweepError(f"endpoint misreported the amount of {u['txid']}:{u['vout']}")
            if out.value <= INPUT_VBYTES[kind] * fee_rate:
                uneconomic += out.value
                continue
            utxos.append({"txid": u["txid"], "vout": int(u["vout"]), "value": out.value, "spk": spk,
                          "key": key, "kind": kind, "address": addr})
    if not utxos:
        raise SweepError("no confirmed outputs worth spending at the current fee rate")
    # Stay below the standard transaction size: largest outputs first, the rest for a next run
    utxos.sort(key=lambda u: -u["value"])
    est, keep, over_limit = 11 + 43, [], 0
    for u in utxos:
        if est + INPUT_VBYTES[u["kind"]] <= MAX_TX_VBYTES:
            keep.append(u)
            est += INPUT_VBYTES[u["kind"]]
        else:
            over_limit += u["value"]
    utxos = keep
    total = sum(u["value"] for u in utxos)
    # Size is measured on a real signed draft; +1 vbyte per input covers signature-length variation
    draft = _sign_btc(utxos, dest_spk, total)
    fee = math.ceil((_vsize(draft) + len(utxos)) * fee_rate)
    out_value = total - fee
    if out_value < DUST_SATS:
        raise SweepError(f"after a fee of {fee} sats only {out_value} sats would remain (below dust)")
    tx = _sign_btc(utxos, dest_spk, out_value)
    return {"tx": tx, "raw": tx.serialize().hex(), "txid": tx.txid().hex(), "inputs": utxos,
            "total": total, "fee": fee, "out_value": out_value, "vsize": _vsize(tx), "fee_rate": fee_rate,
            "skipped_unconfirmed": unconfirmed, "skipped_uneconomic": uneconomic,
            "skipped_over_limit": over_limit}


# ==========================================================================
# EVM
# ==========================================================================
class EvmRpc:
    """Single JSON-RPC calls with explicit errors (a failed call is never treated as zero)."""

    def __init__(self, sess, url):
        self.sess, self.url, self._id = sess, url, 0

    def call(self, method, params):
        self._id += 1
        r = self.sess.post(self.url, json={"jsonrpc": "2.0", "id": self._id, "method": method,
                                           "params": params}, timeout=30)
        r.raise_for_status()
        j = r.json()
        if j.get("error") or "result" not in j:
            raise SweepError(f"{method} failed: {(j.get('error') or {}).get('message', 'no result')}")
        return j["result"]


def _int(v):
    """JSON-RPC quantity -> int. '0x' (empty return, e.g. no contract at that address) is 0."""
    if isinstance(v, str):
        return int(v, 16) if v not in ("0x", "") else 0
    return int(v)


def _l1_fee(rpc, chain, _acct, tx):
    """OP-stack chains (Base, Optimism) charge an extra L1 data fee; 50% headroom.
    The fee depends only on the transaction's size, so it is priced with a size-identical copy
    signed by a THROWAWAY key: the endpoint never sees a transaction it could broadcast from
    the user's address (a real signed transaction only leaves after the user confirms)."""
    if chain not in OP_STACK:
        return 0
    from eth_account import Account
    raw = bytes(Account.from_key(os.urandom(32)).sign_transaction(tx).raw_transaction)
    data = ("0x" + SEL_GET_L1_FEE + (32).to_bytes(32, "big").hex() + len(raw).to_bytes(32, "big").hex()
            + raw.hex() + "00" * ((32 - len(raw) % 32) % 32))
    fee = _int(rpc.call("eth_call", [{"to": GAS_PRICE_ORACLE, "data": data}, "latest"]))
    return math.ceil(fee * 1.5)


def build_evm_sweep(rpc, chain, acct, dest, tokens, expected_chain_id=None):
    """Tokens first, then the native coin minus every fee. Fees: EIP-1559 with
    max fee = 2 x base fee + tip, which normally confirms within minutes. Returns a plan dict."""
    expected = EVM_CHAIN_IDS.get(chain) if expected_chain_id is None else expected_chain_id
    chain_id = _int(rpc.call("eth_chainId", []))
    if chain_id != expected:
        raise SweepError(f"endpoint is chain id {chain_id}, but {chain} is {expected} - wrong network")
    src = acct.address
    nonce = _int(rpc.call("eth_getTransactionCount", [src, "pending"]))
    confirmed_nonce = _int(rpc.call("eth_getTransactionCount", [src, "latest"]))
    if nonce < confirmed_nonce:
        raise SweepError("the endpoint returned inconsistent data (lagging node?). Try again or use another endpoint")
    if nonce > confirmed_nonce:
        raise SweepError(f"{src} has {nonce - confirmed_nonce} pending transaction(s). Wait until they "
                         "confirm (or replace them in a wallet), then sweep again")
    balance = _int(rpc.call("eth_getBalance", [src, "latest"]))
    block = rpc.call("eth_getBlockByNumber", ["latest", False])
    base = _int(block.get("baseFeePerGas") or 0)
    gas_price = _int(rpc.call("eth_gasPrice", []))
    try:
        tip = _int(rpc.call("eth_maxPriorityFeePerGas", []))
    except SweepError:
        tip = 0
    # Some public endpoints suggest a 0 tip; use what was actually paid recently instead:
    # median over the last 20 blocks of each block's 75th-percentile tip (aims at < 1 hour).
    paid = 0
    try:
        hist = rpc.call("eth_feeHistory", ["0x14", "latest", [75]])
        rewards = sorted(_int(r[0]) for r in (hist.get("reward") or []) if r)
        paid = rewards[len(rewards) // 2] if rewards else 0
    except SweepError:
        pass
    gap = max(gas_price - base, 0)
    if paid:
        # The endpoint's own suggestions are capped at 3x what recent blocks actually paid,
        # so an endpoint cannot inflate the (non-refundable) tip.
        tip = max(paid, min(tip, 3 * paid), min(gap, 3 * paid))
    else:
        tip = max(tip, gap, 0)                   # effective price never below the node's suggestion
    max_fee = max(2 * base + tip, gas_price)
    fee_fields = {"type": 2, "chainId": chain_id, "maxFeePerGas": max_fee, "maxPriorityFeePerGas": tip}

    txs, reserved, stuck, failed = [], 0, [], []
    for sym, contract in tokens.items():
        bal = _int(rpc.call("eth_call", [{"to": contract, "data": W.balance_of_data(src)}, "latest"]))
        if not bal:
            continue
        dec = _int(rpc.call("eth_call", [{"to": contract, "data": SEL_DECIMALS}, "latest"]))
        data = "0x" + SEL_TRANSFER + dest[2:].lower().rjust(64, "0") + format(bal, "064x")
        try:
            gas = math.ceil(_int(rpc.call("eth_estimateGas", [{"from": src, "to": contract, "data": data}])) * 1.2)
        except SweepError as e:
            if balance:                          # e.g. frozen/blacklisted or paused token
                failed.append((sym, str(e)[:120]))
                continue
            gas = 100_000        # some nodes refuse estimates without gas money; only used to report the need
        tx = dict(fee_fields, nonce=nonce + len(txs), to=contract, value=0, data=data, gas=gas)
        cost = gas * max_fee + _l1_fee(rpc, chain, acct, tx)
        txs.append({"kind": "token", "symbol": sym, "amount": bal / 10 ** dec, "tx": tx, "max_cost": cost})
        reserved += cost

    # value 0: the estimate must also work for addresses that only hold tokens
    try:
        est = _int(rpc.call("eth_estimateGas", [{"from": src, "to": dest, "value": "0x0"}]))
    except SweepError:
        if balance:
            raise
        est = 21000              # nothing can be sent anyway; only used to report the need
    gas = est if est == 21000 else math.ceil(est * 1.2)
    ntx = dict(fee_fields, nonce=nonce + len(txs), to=dest, value=0, data="0x", gas=gas)
    native_cost = gas * max_fee + _l1_fee(rpc, chain, acct, ntx)
    value = balance - reserved - native_cost
    if reserved and balance < reserved:
        stuck = [t["symbol"] for t in txs]
        txs = []                                   # cannot pay gas for the token transfers
    elif value > 0:
        ntx["value"] = value
        txs.append({"kind": "native", "symbol": W.EVM_CHAINS.get(chain, {}).get("symbol", "native"),
                    "amount": value / 1e18, "tx": ntx, "max_cost": native_cost})
    for t in txs:
        signed = acct.sign_transaction(t["tx"])
        t["raw"] = "0x" + bytes(signed.raw_transaction).hex()
        t["hash"] = "0x" + bytes(signed.hash).hex()
    return {"chain": chain, "chain_id": chain_id, "source": src, "dest": dest, "balance": balance,
            "max_fee": max_fee, "tip": tip, "txs": txs, "stuck_tokens": stuck, "failed_tokens": failed,
            "gas_needed": reserved + native_cost}


def send_evm(rpc, plan, wait_s=600):
    """Broadcast in nonce order, then wait for receipts. Returns list of (label, hash, status)."""
    results = []
    for t in plan["txs"]:
        h = rpc.call("eth_sendRawTransaction", [t["raw"]])
        say(f"    sent {t['symbol']}: {h}", 0)
        if str(h).lower() != t["hash"].lower():
            banner([f"The endpoint returned hash {h}, but the signed transaction is {t['hash']}.",
                    "Check both on a block explorer."])
        results.append([t["symbol"], h, "pending"])
    deadline = time.time() + wait_s
    while time.time() < deadline and any(r[2] == "pending" for r in results):
        for r in results:
            if r[2] == "pending":
                rec = rpc.call("eth_getTransactionReceipt", [r[1]])
                if rec:
                    r[2] = "confirmed" if _int(rec["status"]) == 1 else "FAILED (reverted)"
        if any(r[2] == "pending" for r in results):
            time.sleep(5)
    return results


# ==========================================================================
# Interactive flow
# ==========================================================================
def _ask(prompt):
    return input(prompt).strip()


def _yes(prompt):
    return _ask(prompt + " [y/N] ").lower() in ("y", "yes")


def _confirm_broadcast(prompt, unusual_fee_reason=None):
    """One y/N normally. An unusually high fee needs the word 'yes' typed out."""
    if unusual_fee_reason:
        say(f"  ! UNUSUAL FEE: {unusual_fee_reason}", 0)
        return _ask(prompt + " Type 'yes' to accept this fee: ").lower() == "yes"
    return _yes(prompt)


def contract_destination_check(chain, code_by_chain):
    """Decide whether an EVM destination is safe on `chain`, given where it has contract code.
    A smart-contract wallet (e.g. a Safe) usually exists only on the chains it was deployed to;
    funds sent to the same address on another chain can be lost. Returns (verdict, message)."""
    has_code = {c for c, v in code_by_chain.items() if v}
    unknown = sorted(c for c, v in code_by_chain.items() if v is None)
    if has_code and not code_by_chain.get(chain):
        return "refuse", (f"this address is a smart contract on {', '.join(sorted(has_code))} but NOT on "
                          f"{chain}. Funds sent there could be lost. Use a different destination")
    if unknown:
        return "confirm", (f"could not check whether the destination is a smart contract on {', '.join(unknown)}. "
                           f"If it is a contract wallet (e.g. a Safe) that does not exist on {chain}, funds could be lost")
    if code_by_chain.get(chain):
        return "warn", "the destination is a smart contract on this chain. Make sure it can receive these assets"
    return "ok", ""


def _code_by_chain(a, dest, chain, rpc):
    """Contract code at `dest` on every configured EVM chain (None = could not check)."""
    out, sess = {}, W._session(a.proxy)
    for c, cfg in W.EVM_CHAINS.items():
        clients = ([rpc] if c == chain else []) + [EvmRpc(sess, u) for u in cfg["rpcs"]]
        out[c] = None
        for client in clients:                       # every configured endpoint before giving up
            try:
                out[c] = client.call("eth_getCode", [dest, "latest"]) not in ("0x", "0x0", None, "")
                break
            except Exception:
                continue
    return out


def reference_tip(a, chain, url):
    """Recently paid tip from an endpoint OTHER than the one used for the sweep (independent check)."""
    sess = W._session(a.proxy)
    for u in W.EVM_CHAINS[chain]["rpcs"]:
        if u == url:
            continue
        try:
            hist = EvmRpc(sess, u).call("eth_feeHistory", ["0x14", "latest", [75]])
            rewards = sorted(_int(r[0]) for r in (hist.get("reward") or []) if r)
            if rewards:
                return rewards[len(rewards) // 2]
        except Exception:
            continue
    return None


def unusual_tip(tip, reference):
    """True if the tip is far above what an independent endpoint saw recently being paid."""
    return reference is not None and tip > 3 * reference + 10 ** 9 // 100   # +0.01 gwei slack for ~0 tips


def _ask_until_valid(prompt, parse):
    while True:
        text = _ask(prompt)
        if not text:
            return None
        try:
            return parse(text)
        except ValueError as e:
            say(f"    ! {e}. Try again, or press Enter to skip.", 0)


def collect_funds(b, lines, rows, sc):
    """Funded rows from the scan, with keys resolved. Returns (btc_inputs, evm_by_chain, notes)."""
    keyrings, btc, evm, notes = {}, {}, {}, []

    def keyring(line):
        if line not in keyrings:
            keyrings[line] = Keyring(b, lines[int(line) - 1])
        return keyrings[line]

    keys = ["line", "source", "family", "type", "path", "address"]
    for raw in rows:
        r = {k: str(v) for k, v in zip(keys, raw)}
        fam, addr = r["family"], r["address"]
        try:
            if fam == "btc":
                d = sc.btc_res.get(addr)
                if d and d["sats"] > 0 and addr not in btc:
                    k, spk, kind = btc_key_for(keyring(r["line"]), r)
                    btc[addr] = (addr, k, spk, kind, d["sats"], r["line"])
            elif fam == "evm":
                for chain, d in sc.evm_res.get(addr.lower(), {}).items():
                    if d.get("native") or d.get("tokens"):
                        per = evm.setdefault(chain, {})
                        if addr.lower() not in per:
                            per[addr.lower()] = (evm_account_for(keyring(r["line"]), r), d, r["line"])
            elif fam in W.UTXO_CHAINS:
                d = sc.utxo_res.get((fam, addr))
                if d and d["sats"] > 0:
                    notes.append(f"line {r['line']}: {d['sats'] / 1e8:.8f} {W.UTXO_CHAINS[fam]['symbol']} on "
                                 f"{addr} - not supported by sweep, use a {W.UTXO_CHAINS[fam]['name']} wallet")
        except SweepError as e:
            notes.append(f"line {r['line']}: {addr} - {e}")
        if fam in ("btc", "evm") or fam in W.UTXO_CHAINS:
            if sc.failed(raw):
                notes.append(f"line {r['line']}: {addr} - lookup FAILED, not checked; sweep again later")
    return list(btc.values()), evm, notes


def _sweep_btc(a, btc_inputs, sources):
    total = sum(i[4] for i in btc_inputs)
    say(f"\n--- Bitcoin: {total / 1e8:.8f} BTC on {len(btc_inputs)} address(es) ---", 0)
    if not _yes("Sweep Bitcoin?"):
        return
    dest = _ask_until_valid("  Destination Bitcoin address (new wallet): ",
                            lambda t: parse_btc_destination(t, sources))
    if not dest:
        return
    base = _ask(f"  Broadcast endpoint, Esplora API [Enter = {W.BTC_APIS[0]}]: ") or W.BTC_APIS[0]
    client = Esplora(W._session(a.proxy), base)
    try:
        rate = max(client.fee_rate_1h(), 1.0)
        plan = build_btc_sweep(client, [i[:4] for i in btc_inputs], dest[1], rate)
    except SweepError as e:
        banner([f"Bitcoin sweep not possible: {e}", "Nothing was broadcast."])
        return
    except Exception as e:
        banner([f"Bitcoin sweep failed while talking to {base}: {type(e).__name__}: {str(e)[:200]}",
                "Nothing was broadcast."])
        return
    say("\n  PLAN (signed, not yet broadcast)", 0)
    say(f"    from      {len(plan['inputs'])} confirmed output(s) on "
        f"{len({u['address'] for u in plan['inputs']})} address(es), total {plan['total'] / 1e8:.8f} BTC", 0)
    say(f"    to        {dest[0]}", 0)
    say(f"    amount    {plan['out_value'] / 1e8:.8f} BTC", 0)
    say(f"    fee       {plan['fee']} sats ({plan['fee_rate']:g} sat/vB, {plan['vsize']} vB, target ~1 hour, "
        f"replace-by-fee enabled)", 0)
    if plan["skipped_unconfirmed"]:
        say(f"    skipped   {plan['skipped_unconfirmed'] / 1e8:.8f} BTC unconfirmed (sweep again once confirmed)", 0)
    if plan["skipped_uneconomic"]:
        say(f"    skipped   {plan['skipped_uneconomic'] / 1e8:.8f} BTC in outputs worth less than their fee", 0)
    if plan["skipped_over_limit"]:
        say(f"    skipped   {plan['skipped_over_limit'] / 1e8:.8f} BTC that does not fit in one standard "
            f"transaction (sweep again after this one confirms)", 0)
    say(f"    txid      {plan['txid']}", 0)
    if a.dry_run:
        say(f"\n  DRY RUN - not broadcast. Signed transaction (anyone who has it can broadcast it):\n"
            f"  {plan['raw']}", 0)
        return
    unusual = None
    if plan["fee"] > plan["total"] * HIGH_FEE_SHARE:
        unusual = f"the fee is {plan['fee'] / plan['total']:.0%} of the amount"
    elif plan["fee_rate"] > HIGH_BTC_FEE_RATE:
        unusual = f"{plan['fee_rate']:g} sat/vB is far above normal (check the endpoint)"
    if not _confirm_broadcast("  Broadcast this transaction now?", unusual):
        say("  Not broadcast.", 0)
        return
    try:
        txid = client.broadcast(plan["raw"])
    except Exception as e:
        banner([f"Broadcast failed: {e}", "Nothing was sent. You can retry; the plan is unchanged."])
        return
    say(f"  BROADCAST OK  txid {txid}", 0)
    if txid.lower() != plan["txid"]:
        banner([f"The endpoint returned txid {txid}, but the signed transaction is {plan['txid']}.",
                "Check both on a block explorer."])
    say(f"  Track it: https://mempool.space/tx/{txid}", 0)


def _sweep_evm_chain(a, chain, accounts, sources, last_dest):
    sym = W.EVM_CHAINS[chain]["symbol"]
    say(f"\n--- {chain}: {len(accounts)} address(es) with funds ---", 0)
    for acct, d, line in accounts.values():
        toks = ", ".join(f"{k} {W.fmt_amount(v)}" for k, v in d.get("tokens", {}).items())
        say(f"    line {line} {acct.address}: {W.fmt_amount(d.get('native') or 0)} {sym}"
            + (f" + {toks}" if toks else ""), 0)
    if not _yes(f"Sweep {chain}?"):
        return last_dest
    hint = f" [Enter = {last_dest}]" if last_dest else " [Enter = skip]"
    while True:
        text = _ask(f"  Destination address on {chain} (new wallet){hint}: ") or (last_dest or "")
        if not text:
            return last_dest
        try:
            dest = parse_evm_destination(text, sources)
            break
        except ValueError as e:
            say(f"    ! {e}. Try again.", 0)
    default_rpc = W.EVM_CHAINS[chain]["rpcs"][0]
    url = _ask(f"  Broadcast endpoint, JSON-RPC [Enter = {default_rpc}]: ") or default_rpc
    rpc = EvmRpc(W._session(a.proxy), url)
    verdict, msg = contract_destination_check(chain, _code_by_chain(a, dest, chain, rpc))
    if verdict == "refuse":
        banner([msg, f"Nothing was sent on {chain}."])
        return last_dest
    if verdict == "warn":
        say(f"  ! {msg}.", 0)
    if verdict == "confirm":
        say(f"  ! {msg}.", 0)
        if _ask("  Type 'yes' if you are sure the destination can receive funds on this chain: ").lower() != "yes":
            say(f"  Skipping {chain}.", 0)
            return last_dest
    for acct, d, line in accounts.values():
        try:
            plan = build_evm_sweep(rpc, chain, acct, dest, W.EVM_CHAINS[chain]["tokens"])
        except SweepError as e:
            banner([f"{chain} sweep of {acct.address} not possible: {e}", "Nothing was broadcast for it."])
            continue
        except Exception as e:
            banner([f"{chain} sweep failed while talking to {url}: {type(e).__name__}: {str(e)[:200]}",
                    "Nothing was broadcast."])
            continue
        say(f"\n  PLAN for {acct.address} (signed, not yet broadcast)", 0)
        if plan["stuck_tokens"]:
            say(f"    ! {', '.join(plan['stuck_tokens'])} cannot move: the address needs about "
                f"{W.fmt_amount(plan['gas_needed'] / 1e18)} {sym} for gas but holds "
                f"{W.fmt_amount(plan['balance'] / 1e18)}. Send it a little {sym} first.", 0)
        for sym_f, why in plan["failed_tokens"]:
            say(f"    ! {sym_f} cannot be transferred (frozen, paused or blocked?): {why}", 0)
        if not plan["txs"]:
            say("    nothing worth sending (balance does not cover the fee)", 0)
            continue
        for t in plan["txs"]:
            say(f"    send {W.fmt_amount(t['amount'])} {t['symbol']} -> {dest}  "
                f"(max fee {W.fmt_amount(t['max_cost'] / 1e18)} {sym})", 0)
        say(f"    fee settings: max {plan['max_fee'] / 1e9:g} gwei, tip {plan['tip'] / 1e9:g} gwei "
            f"(normally confirms within minutes); a little {sym} may remain as unused fee headroom", 0)
        if a.dry_run:
            say("    DRY RUN - not broadcast. Signed transactions (anyone who has them can broadcast them):", 0)
            for t in plan["txs"]:
                say(f"    {t['raw']}", 0)
            continue
        max_fees = sum(t["max_cost"] for t in plan["txs"])
        unusual = None
        ref = reference_tip(a, chain, url)
        if plan["balance"] and max_fees > plan["balance"] * HIGH_FEE_SHARE:
            unusual = (f"fees could reach {W.fmt_amount(max_fees / 1e18)} {sym}, "
                       f"{max_fees / plan['balance']:.0%} of the {sym} balance (actual fees are usually lower)")
        elif unusual_tip(plan["tip"], ref):
            unusual = (f"the tip of {plan['tip'] / 1e9:g} gwei is far above the {ref / 1e9:g} gwei an independent "
                       f"endpoint saw being paid recently (check your endpoint)")
        if not _confirm_broadcast("  Broadcast now?", unusual):
            say("  Not broadcast.", 0)
            continue
        try:
            for label, h, status in send_evm(rpc, plan, a.wait):
                say(f"    {label}: {status}  {h}", 0)
        except Exception as e:
            banner([f"Broadcast on {chain} failed: {e}",
                    "Some transactions may have been sent - check the address on an explorer before retrying."])
    return dest


def cmd_sweep(a):
    _deps()
    b = W._bip()
    banner(["walletcheck sweep MOVES FUNDS. Transactions cannot be reversed.",
            "Read every plan. Send to a NEW wallet you control. Test with a small amount first."])
    say("\nStep 1/3 - Reading inputs (secrets stay on this computer)")
    lines = W.read_lines(a)
    seqs, _, rejected = W.parse_inputs(b, lines, a)
    if not seqs:
        W.rejected_banner(rejected)
        banner(["Nothing valid to sweep - stopped."])
        sys.exit(1)

    say("\nStep 2/3 - Finding funds (adaptive scan, public addresses only)")
    rows, sc, fails = W.scan_seqs(a, seqs)
    W.rejected_banner(rejected)
    if fails:
        banner([f"{fails} lookup(s) failed - some funds may not have been found. Re-run later."])
    btc_inputs, evm, notes = collect_funds(b, lines, rows, sc)
    sources = {r[5].lower() for r in rows}

    say("\nStep 3/3 - Sweep, chain by chain")
    for n in notes:
        say(f"  note: {n}", 0)
    if not btc_inputs and not evm:
        say("  Nothing sweepable was found.", 0)
        return
    if btc_inputs:
        _sweep_btc(a, btc_inputs, sources)
    last_dest = None
    for chain in W.EVM_CHAINS:
        if chain in evm:
            last_dest = _sweep_evm_chain(a, chain, evm[chain], sources, last_dest)
    say("\nDone. Keys that were stored in plain text should not be used again.", 0)

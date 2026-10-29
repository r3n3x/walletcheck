"""Transparent Zcash (t1...) and Firo (a...) support: official vectors, derivation,
lookup parsing, failure handling and reporting. No network: lookups use a fake session."""
import pytest

import walletcheck as W
from conftest import derive_lines
from test_privacy import SECRETS  # public test-seed WIF, defined once in test_privacy.py
from bip_utils import Base58Decoder, Base58Encoder, Hash160

ABANDON = "abandon " * 11 + "about"
WIF = SECRETS["wif"]

# Official Zcash vectors (zcash/src/test/data/base58_keys_valid.json): script hash -> t1 address
ZEC_VECTORS = [
    ("t1T8yaLVhNqxA5KJcmiqqFN88e8DNp2PBfF", "65a16059864a2fdbc7c99a4723a8395bc6f188eb"),
    ("t1TpfguJj5zxKUfWcsNTrh6eod2XXsTKtvB", "6d23156cbbdcc82a5a47eee4c2c7c583c18b6bf4"),
    ("t1UxCT4RrCbGH36etfQaPF1svNtZVhsqs5A", "7987ccaa53d02c8873487ef919677cd3db7a6912"),
]
# Transparent Firo address that exists on-chain (explorer.firo.org); version byte 82 = 0x52
FIRO_ADDR = "a15x6k65suS5yUJNQbVomH1bXGzbjkTGtQ"


class Resp:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class Sess:
    def __init__(self, resp):
        self.resp = resp

    def get(self, url, timeout):
        return self.resp


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(W.time, "sleep", lambda *_: None)


@pytest.mark.parametrize("addr,h160", ZEC_VECTORS)
def test_zcash_t1_version_bytes_match_official_vectors(addr, h160):
    assert Base58Encoder.CheckEncode(b"\x1c\xb8" + bytes.fromhex(h160)) == addr


def test_firo_p2pkh_version_byte_matches_on_chain_address():
    raw = Base58Decoder.CheckDecode(FIRO_ADDR)
    assert raw[0] == 0x52 and len(raw) == 21


@pytest.mark.parametrize("fam,coin,ver", [("zec", 133, b"\x1c\xb8"), ("firo", 136, b"\x52")])
def test_seed_derivation_matches_independent_encoding(b, fam, coin, ver):
    root = b.Bip32Secp256k1.FromSeed(b.Bip39SeedGenerator(ABANDON).Generate(""))
    seqs = []
    W.derive_from_root(b, root, 1, None, seqs, "t")
    seq = next(s for s in seqs if s.family == fam and s.kind == "recv")
    row = seq.fn(0)[0]
    assert row[4] == f"m/44'/{coin}'/0'/0/0"
    pub = root.DerivePath(f"m/44'/{coin}'/0'/0/0").PublicKey().KeyObject().RawCompressed().ToBytes()
    assert row[5] == Base58Encoder.CheckEncode(ver + Hash160.QuickDigest(pub))


def test_wif_key_is_checked_on_zcash_and_firo(b):
    rows, rejected = derive_lines(b, [WIF])
    assert not rejected
    fams = {r[2] for r in rows}
    assert {"zec", "firo"} <= fams
    assert [r[5] for r in rows if r[2] == "zec"][0].startswith("t1")
    assert [r[5] for r in rows if r[2] == "firo"][0].startswith("a")


def test_blockchair_parsing_unused_used_and_null_count():
    unused = {"data": {ZEC_VECTORS[0][0]: {"address": {"balance": 0, "transaction_count": None, "received": 0}}}}
    assert W.utxo_lookup(Sess(Resp(200, unused)), "zec", ZEC_VECTORS[0][0]) == {"sats": 0, "txs": 0}
    used = {"data": {ZEC_VECTORS[0][0]: {"address": {"balance": 1234, "transaction_count": 3, "received": 5000}}}}
    assert W.utxo_lookup(Sess(Resp(200, used)), "zec", ZEC_VECTORS[0][0]) == {"sats": 1234, "txs": 3}
    # spent-out address: Blockchair leaves transaction_count null, but received > 0 means history
    spent = {"data": {ZEC_VECTORS[0][0]: {"address": {"balance": 0, "transaction_count": None, "received": 500}}}}
    assert W.utxo_lookup(Sess(Resp(200, spent)), "zec", ZEC_VECTORS[0][0]) == {"sats": 0, "txs": 1}


# Verified unit: Blockchair balance of a funded Zcash address is zatoshi (1 ZEC = 1e8). The
# funding tx output to the address is 100000000000 zatoshi = 1000 ZEC (decoded from the raw tx).
VERIFIED_ZEC_ADDR = "t1MafeF942Pqv3uTJ1SeHTt3rf8kUM9bcmR"


def test_blockchair_balance_is_zatoshi_verified_on_funded_address(tmp_path, capsys):
    payload = {"data": {VERIFIED_ZEC_ADDR: {"address": {
        "balance": 100000000000, "received": 100000000000, "spent": 0,
        "transaction_count": None, "output_count": 1, "unspent_output_count": 1}}}}
    res = W.utxo_lookup(Sess(Resp(200, payload)), "zec", VERIFIED_ZEC_ADDR)
    assert res == {"sats": 100000000000, "txs": 1}  # null count + received > 0 -> one tx
    rows = [{"line": "1", "source": "x", "family": "zec", "type": "p2pkh",
             "path": "m/44'/133'/0'/0/0", "address": VERIFIED_ZEC_ADDR}]
    W.report(rows, {}, {}, str(tmp_path / "b.csv"), {("zec", VERIFIED_ZEC_ADDR): res})
    assert "1000.00000000 ZEC" in capsys.readouterr().out


def test_firo_insight_parsing():
    payload = {"balanceSat": 0, "totalReceivedSat": 1182366, "txApperances": 2}
    assert W.utxo_lookup(Sess(Resp(200, payload)), "firo", FIRO_ADDR) == {"sats": 0, "txs": 2}


def test_failed_lookup_is_none_not_empty():
    assert W.utxo_lookup(Sess(Resp(500, {})), "firo", FIRO_ADDR) is None
    assert W.utxo_lookup(Sess(Resp(430, {})), "zec", ZEC_VECTORS[0][0]) is None  # rate limited, every retry


def test_report_shows_found_zcash_and_marks_failed_firo_unknown(tmp_path, capsys):
    rows = [
        {"line": "1", "source": "x", "family": "zec", "type": "p2pkh",
         "path": "m/44'/133'/0'/0/0", "address": ZEC_VECTORS[0][0]},
        {"line": "2", "source": "x", "family": "firo", "type": "p2pkh",
         "path": "m/44'/136'/0'/0/0", "address": FIRO_ADDR},
    ]
    utxo = {("zec", ZEC_VECTORS[0][0]): {"sats": 250000000, "txs": 2}, ("firo", FIRO_ADDR): None}
    W.report(rows, {}, {}, str(tmp_path / "b.csv"), utxo)
    out = capsys.readouterr().out
    assert "[1] BALANCES FOUND" in out and "2.50000000 ZEC" in out
    assert "line(s): 2" in out.split("[4] UNKNOWN")[1]
    assert "line(s): -" in out.split("[3] NO HISTORY AT ALL")[1].split("[4]")[0]

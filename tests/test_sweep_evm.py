"""EVM sweep end to end on an in-process Ethereum chain (eth-tester / py-evm), using
OpenZeppelin's audited ERC20 (tests/fixtures, MIT). Real signing, real broadcast, real receipts."""
import json
import os

import pytest

pytest.importorskip("eth_account")
eth_tester = pytest.importorskip("eth_tester")
from eth_abi import encode  # noqa: E402
from eth_account import Account  # noqa: E402
from eth_utils import keccak, to_checksum_address  # noqa: E402

import walletcheck_sweep as S  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "ERC20PresetMinterPauser.json")
GWEI = 10 ** 9


class Resp:
    def __init__(self, payload):
        self.payload, self.status_code = payload, 200

    def json(self):
        return self.payload

    def raise_for_status(self):
        pass


class TesterSession:
    __test__ = False
    """Minimal JSON-RPC front end for eth-tester, shaped like requests.Session.post."""

    def __init__(self, t, fail=(), paid_tip=None, node_tip=GWEI, pending_extra=0):
        self.t, self.fail, self.paid_tip = t, set(fail), paid_tip
        self.node_tip, self.pending_extra = node_tip, pending_extra

    def post(self, url, json=None, timeout=None):
        try:
            return self._post(json)
        except Exception as e:      # a real node answers with a JSON-RPC error, not an exception
            return Resp({"jsonrpc": "2.0", "id": json["id"], "error": {"code": -32000, "message": str(e)}})

    def _post(self, json):
        m, p, t = json["method"], json["params"], self.t
        if m in self.fail:
            return Resp({"jsonrpc": "2.0", "id": json["id"], "error": {"code": -32000, "message": "boom"}})
        base = t.get_block_by_number("latest")["base_fee_per_gas"]
        if m == "eth_chainId":
            r = hex(t.backend.chain.chain_id)
        elif m == "eth_getTransactionCount":
            r = hex(t.get_nonce(p[0], "latest") + (self.pending_extra if p[1] == "pending" else 0))
        elif m == "eth_getBalance":
            r = hex(t.get_balance(p[0]))
        elif m == "eth_getBlockByNumber":
            r = {"baseFeePerGas": hex(base)}
        elif m == "eth_gasPrice":
            r = hex(base + GWEI)
        elif m == "eth_maxPriorityFeePerGas":
            r = hex(self.node_tip)
        elif m == "eth_call":
            # eth-tester needs a funded sender even for read-only calls
            r = t.call({"from": p[0].get("from", t.get_accounts()[0]), "to": p[0]["to"], "data": p[0]["data"]})
        elif m == "eth_estimateGas":
            q = {"from": p[0]["from"], "to": p[0]["to"], "data": p[0].get("data", "0x"),
                 "value": int(p[0].get("value", "0x0"), 16)}
            r = hex(t.estimate_gas(q))
        elif m == "eth_sendRawTransaction":
            r = t.send_raw_transaction(p[0])
        elif m == "eth_getTransactionReceipt":
            rec = t.get_transaction_receipt(p[0])
            r = {"status": hex(rec["status"])} if rec else None
        elif m == "eth_feeHistory" and self.paid_tip is not None:
            r = {"reward": [[hex(self.paid_tip)]] * 20}
        elif m == "eth_getCode":
            r = t.get_code(p[0])
        else:
            raise AssertionError(f"unexpected RPC {m}")
        return Resp({"jsonrpc": "2.0", "id": json["id"], "result": r})


def selector(sig):
    return keccak(text=sig)[:4].hex()


@pytest.fixture
def chain():
    t = eth_tester.EthereumTester()
    funder = t.get_accounts()[0]
    with open(FIXTURE) as f:
        art = json.load(f)
    h = t.send_transaction({"from": funder, "gas": 6_000_000,
                            "data": art["bytecode"] + encode(["string", "string"], ["Test USD", "TUSD"]).hex()})
    token = t.get_transaction_receipt(h)["contract_address"]

    def fund(addr, eth_wei=0, tokens=0):
        if eth_wei:
            t.send_transaction({"from": funder, "to": addr, "value": eth_wei, "gas": 21000})
        if tokens:
            data = "0x" + selector("mint(address,uint256)") + encode(["address", "uint256"], [addr, tokens]).hex()
            t.send_transaction({"from": funder, "to": token, "data": data, "gas": 200_000})

    def token_balance(addr):
        out = t.call({"from": funder, "to": token, "data": "0x" + selector("balanceOf(address)") + encode(["address"], [addr]).hex()})
        return int(out, 16) if isinstance(out, str) else int.from_bytes(out, "big")

    return t, token, fund, token_balance


def accounts(n):
    return [Account.from_key(keccak(text=f"walletcheck test key {i}")) for i in range(n)]


def test_tokens_and_native_swept_end_to_end(chain):
    t, token, fund, token_balance = chain
    src, dest = accounts(2)
    fund(src.address, eth_wei=10 ** 17, tokens=1234 * 10 ** 18)
    rpc = S.EvmRpc(TesterSession(t), "http://tester")
    cid = t.backend.chain.chain_id
    plan = S.build_evm_sweep(rpc, "ethereum", src, dest.address, {"TUSD": token}, expected_chain_id=cid)
    assert [x["kind"] for x in plan["txs"]] == ["token", "native"]
    results = S.send_evm(rpc, plan, wait_s=5)
    assert all(r[2] == "confirmed" for r in results), results
    assert token_balance(dest.address) == 1234 * 10 ** 18 and token_balance(src.address) == 0
    native_sent = plan["txs"][1]["tx"]["value"]
    assert t.get_balance(dest.address) == native_sent
    left = t.get_balance(src.address)
    assert 0 <= left < sum(x["max_cost"] for x in plan["txs"])     # only unused fee headroom remains
    assert native_sent + left < 10 ** 17                           # fees were paid, nothing created


def test_native_only(chain):
    t, token, fund, token_balance = chain
    src, dest = accounts(2)
    fund(src.address, eth_wei=5 * 10 ** 16)
    rpc = S.EvmRpc(TesterSession(t), "http://tester")
    plan = S.build_evm_sweep(rpc, "ethereum", src, dest.address, {"TUSD": token},
                             expected_chain_id=t.backend.chain.chain_id)
    assert [x["kind"] for x in plan["txs"]] == ["native"]
    assert S.send_evm(rpc, plan, wait_s=5)[0][2] == "confirmed"
    assert t.get_balance(dest.address) == plan["txs"][0]["tx"]["value"] > 4 * 10 ** 16


def test_tokens_without_gas_are_reported_stuck(chain):
    t, token, fund, token_balance = chain
    src, dest = accounts(2)
    fund(src.address, tokens=10 ** 18)
    rpc = S.EvmRpc(TesterSession(t), "http://tester")
    plan = S.build_evm_sweep(rpc, "ethereum", src, dest.address, {"TUSD": token},
                             expected_chain_id=t.backend.chain.chain_id)
    assert plan["txs"] == [] and plan["stuck_tokens"] == ["TUSD"] and plan["gas_needed"] > 0


def test_wrong_network_is_refused(chain):
    t, token, fund, _ = chain
    src, dest = accounts(2)
    fund(src.address, eth_wei=10 ** 17)
    rpc = S.EvmRpc(TesterSession(t), "http://tester")
    with pytest.raises(S.SweepError, match="wrong network"):
        S.build_evm_sweep(rpc, "ethereum", src, dest.address, {}, expected_chain_id=1)


@pytest.mark.parametrize("failing", ["eth_getBalance", "eth_call", "eth_getTransactionCount"])
def test_rpc_errors_abort_instead_of_reading_zero(chain, failing):
    t, token, fund, _ = chain
    src, dest = accounts(2)
    fund(src.address, eth_wei=10 ** 17, tokens=10 ** 18)
    rpc = S.EvmRpc(TesterSession(t, fail=[failing]), "http://tester")
    with pytest.raises(S.SweepError, match=failing):
        S.build_evm_sweep(rpc, "ethereum", src, dest.address, {"TUSD": token},
                          expected_chain_id=t.backend.chain.chain_id)


def test_op_stack_l1_fee_call_encoding():
    seen = {}

    class Rpc:
        def call(self, method, params):
            seen["data"] = params[0]["data"]
            seen["to"] = params[0]["to"]
            return hex(1000)

    acct = accounts(1)[0]
    tx = {"type": 2, "chainId": 8453, "nonce": 0, "to": to_checksum_address("0x" + "11" * 20), "value": 0,
          "data": "0x", "gas": 21000, "maxFeePerGas": GWEI, "maxPriorityFeePerGas": GWEI}
    assert S._l1_fee(Rpc(), "base", acct, tx) == 1500                       # 50% headroom
    assert S._l1_fee(Rpc(), "ethereum", acct, tx) == 0
    real = bytes(acct.sign_transaction(tx).raw_transaction)
    data = bytes.fromhex(seen["data"][2:])
    assert seen["to"] == S.GAS_PRICE_ORACLE and data[:4].hex() == selector("getL1Fee(bytes)")
    n = int.from_bytes(data[36:68], "big")
    assert int.from_bytes(data[4:36], "big") == 32 and len(data[4:]) % 32 == 0
    sent = data[68:68 + n]
    # Same size (so the fee is right) but NEVER the user's broadcastable transaction:
    assert n == len(real) and sent != real
    assert Account.recover_transaction(sent) != acct.address


def test_tip_follows_recently_paid_tips(chain):
    t, token, fund, _ = chain
    src, dest = accounts(2)
    fund(src.address, eth_wei=10 ** 17)
    cid = t.backend.chain.chain_id
    plan = S.build_evm_sweep(S.EvmRpc(TesterSession(t, paid_tip=3 * GWEI), "x"), "ethereum", src, dest.address,
                             {}, expected_chain_id=cid)
    assert plan["tip"] == 3 * GWEI                                   # above the 1 gwei node suggestion
    plan = S.build_evm_sweep(S.EvmRpc(TesterSession(t), "x"), "ethereum", src, dest.address, {},
                             expected_chain_id=cid)                  # no fee history: falls back
    assert plan["tip"] == 1 * GWEI


# ---- regression tests for the independent review findings ----
def test_one_frozen_token_does_not_block_the_native_sweep(chain):
    t, token, fund, token_balance = chain
    src, dest = accounts(2)
    fund(src.address, eth_wei=10 ** 17, tokens=10 ** 18)
    t.send_transaction({"from": t.get_accounts()[0], "to": token, "data": "0x" + selector("pause()"),
                        "gas": 100_000})                      # token transfers now revert
    rpc = S.EvmRpc(TesterSession(t), "http://tester")
    plan = S.build_evm_sweep(rpc, "ethereum", src, dest.address, {"TUSD": token},
                             expected_chain_id=t.backend.chain.chain_id)
    assert [x["kind"] for x in plan["txs"]] == ["native"]
    assert [f[0] for f in plan["failed_tokens"]] == ["TUSD"]
    assert S.send_evm(rpc, plan, wait_s=5)[0][2] == "confirmed"
    assert t.get_balance(dest.address) > 9 * 10 ** 16


def test_endpoint_cannot_inflate_the_tip(chain):
    t, token, fund, _ = chain
    src, dest = accounts(2)
    fund(src.address, eth_wei=10 ** 17)
    sess = TesterSession(t, paid_tip=GWEI, node_tip=2000 * GWEI)
    plan = S.build_evm_sweep(S.EvmRpc(sess, "x"), "ethereum", src, dest.address, {},
                             expected_chain_id=t.backend.chain.chain_id)
    assert plan["tip"] == 3 * GWEI                            # capped at 3x what blocks paid


def test_pending_transactions_block_the_sweep(chain):
    t, token, fund, _ = chain
    src, dest = accounts(2)
    fund(src.address, eth_wei=10 ** 17)
    with pytest.raises(S.SweepError, match="pending transaction"):
        S.build_evm_sweep(S.EvmRpc(TesterSession(t, pending_extra=1), "x"), "ethereum", src, dest.address,
                          {}, expected_chain_id=t.backend.chain.chain_id)


@pytest.mark.parametrize("chain_name,codes,verdict", [
    ("arbitrum", {"ethereum": True, "arbitrum": False}, "refuse"),   # Safe deployed only on Ethereum
    ("ethereum", {"ethereum": True, "arbitrum": False}, "warn"),
    ("ethereum", {"ethereum": False, "arbitrum": False}, "ok"),
    ("ethereum", {"ethereum": None, "arbitrum": False}, "warn"),     # could not check
])
def test_contract_destination_rule(chain_name, codes, verdict):
    assert S.contract_destination_check(chain_name, codes)[0] == verdict

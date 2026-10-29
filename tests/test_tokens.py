"""Token lists: the built-in CSV, the personal list, validation, and on-chain verification (mocked)."""
import os

import pytest

import walletcheck as W

MOR = {"ethereum": "0xcBB8f1BDA10b9696c57E13BC128Fe674769DCEc0",
       "arbitrum": "0x092bAaDB7DEf4C3981454dD9c0A0D7FF07bCFc86",
       "base": "0x7431aDa8a591C955a994a21710752EF9b882b8e3"}
HEADER = "chain,symbol,address,decimals,onchain_symbol,name,coingecko_id,source\n"
TOKEN_A = "0x1111111111111111111111111111111111111111"
TOKEN_B = "0x2222222222222222222222222222222222222222"


def personal_file(text):
    path = os.path.join(os.environ["XDG_CONFIG_HOME"], "walletcheck", "tokens.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


# ---- built-in list --------------------------------------------------------------------------
def test_builtin_list_loads_and_is_well_formed():
    entries = W._read_builtin_tokens()
    assert W.TOKEN_LOAD_ERROR is None and len(entries) >= 34
    assert {e["chain"] for e in entries} == set(W.EVM_CHAINS)              # every chain has tokens
    pairs_addr = [(e["chain"], e["address"].lower()) for e in entries]
    pairs_sym = [(e["chain"], e["symbol"].lower()) for e in entries]
    assert len(set(pairs_addr)) == len(pairs_addr) and len(set(pairs_sym)) == len(pairs_sym)
    for e in entries:
        assert e["coingecko_id"] or e["source"]
        assert e["decimals"].isdigit()                                      # built-in rows state decimals


def test_builtin_addresses_are_checksummed_in_the_file():
    from importlib import resources
    text = resources.files("walletcheck_tokens").joinpath("tokens.csv").read_text(encoding="utf-8")
    for e in W._read_builtin_tokens():
        assert e["address"] in text                                         # written in EIP-55 form


def test_mor_on_three_chains():
    got = {e["chain"]: e["address"] for e in W._read_builtin_tokens() if e["symbol"] == "MOR"}
    assert got == MOR


def test_eip55_matches_eth_utils():
    eth_utils = pytest.importorskip("eth_utils")
    for e in W._read_builtin_tokens():
        assert W.eip55(e["address"].lower()) == eth_utils.to_checksum_address(e["address"])
    for i in range(50):
        a = "0x" + os.urandom(20).hex()
        assert W.eip55(a) == eth_utils.to_checksum_address(a)


def test_builtin_tokens_are_what_scans_use():
    assert W.EVM_CHAINS["base"]["tokens"]["MOR"] == MOR["base"]


# ---- validation -------------------------------------------------------------------------------
@pytest.mark.parametrize("row,message", [
    ("solana,USDC,0x1111111111111111111111111111111111111111", "unknown chain"),
    ("base,USDC,0x123", "not 0x followed by 40 hex"),
    ("base,USDC,0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02914", "wrong checksum"),
    ("base,MY TOKEN,0x1111111111111111111111111111111111111111", "plain characters"),
    ("base,USDC\u200b,0x1111111111111111111111111111111111111111", "plain characters"),  # invisible char
    ("base,USDС,0x1111111111111111111111111111111111111111", "plain characters"),        # Cyrillic С
    ("base,X\x1b[2K,0x1111111111111111111111111111111111111111", "plain characters"),   # terminal escape
    ("bsc,bnb,0x1111111111111111111111111111111111111111", "native coin"),
    ("base,X,0x1111111111111111111111111111111111111111,6,,Evil\x1b[2K", "control characters"),
    ("base,X,0x1111111111111111111111111111111111111111,³", "decimals"),
    ("base,X,0x0000000000000000000000000000000000000000", "zero address"),
    ("base,X,0x1111111111111111111111111111111111111111,abc", "decimals"),
    ("base,X,0x1111111111111111111111111111111111111111,6,X,n,id,src,extra", "values for"),
])
def test_invalid_rows_are_rejected_with_line_number(row, message):
    with pytest.raises(W.TokenListError, match=message) as e:
        W.parse_token_csv("# comment\n" + HEADER + row + "\n", "my.csv")
    assert "my.csv line 3" in str(e.value)


@pytest.mark.parametrize("header,message", [("chain,symbol,adress\n", "unknown: adress"),
                                            ("chain,symbol\n", "missing: address"),
                                            ("chain,symbol,address,symbol\n", "more than once")])
def test_bad_header(header, message):
    with pytest.raises(W.TokenListError, match=message):
        W.parse_token_csv(header + "base,X," + TOKEN_A + "\n", "my.csv")


def test_minimal_personal_row_and_lowercase_address_are_fine():
    rows = W.parse_token_csv("chain,symbol,address\nbase,FOO," + TOKEN_A.replace("1", "a") + "\n", "my.csv")
    assert rows[0]["address"] == W.eip55(TOKEN_A.replace("1", "a")) and rows[0]["decimals"] == ""


def test_builtin_rows_need_a_source():
    with pytest.raises(W.TokenListError, match="coingecko_id or a source"):
        W.parse_token_csv(HEADER + f"base,X,{TOKEN_A},6,,,,\n", "built-in", builtin=True)


# ---- merging ----------------------------------------------------------------------------------
def test_personal_list_is_loaded_automatically_if_present():
    path = personal_file(f"chain,symbol,address\nbase,FOO,{TOKEN_A}\n")
    entries, used = W.load_token_lists()
    assert used == path and any(e["symbol"] == "FOO" for e in entries)
    assert len(entries) == len(W._read_builtin_tokens()) + 1


def test_no_personal_list_means_builtin_only():
    entries, used = W.load_token_lists()
    assert used is None and len(entries) == len(W._read_builtin_tokens())


def test_explicit_list_must_exist(tmp_path):
    with pytest.raises(W.TokenListError, match="cannot read"):
        W.load_token_lists(personal=str(tmp_path / "nope.csv"))


def test_same_contract_twice_is_kept_once():
    personal_file(f"chain,symbol,address\nbase,MOR2,{MOR['base']}\n")    # MOR again under another name
    entries, _ = W.load_token_lists()
    assert [e["symbol"] for e in entries if e["address"] == MOR["base"]] == ["MOR"]


def test_same_symbol_for_another_contract_is_an_error():
    path = personal_file(f"chain,symbol,address\nbase,usdc,{TOKEN_A}\n")  # case-insensitive clash
    with pytest.raises(W.TokenListError, match="already used") as e:
        W.load_token_lists()
    assert path in str(e.value)


def test_only_personal_tokens():
    personal_file(f"chain,symbol,address\nbase,FOO,{TOKEN_A}\narbitrum,BAR,{TOKEN_B}\n")
    entries, _ = W.load_token_lists(use_builtin=False)
    assert [e["symbol"] for e in entries] == ["FOO", "BAR"]


# ---- CLI --------------------------------------------------------------------------------------
def test_tokens_command_lists_personal_tokens(capsys):
    personal_file(f"chain,symbol,address,name\nbase,FOO,{TOKEN_A},My Token\n")
    W.main(["tokens", "--chains", "base"])
    out = capsys.readouterr().out
    assert "FOO" in out and "(personal)" in out and "MOR" in out


def test_broken_personal_list_stops_before_any_lookup(monkeypatch, capsys):
    personal_file("chain,symbol,address\nbase,FOO,0xnope\n")
    monkeypatch.setattr(W, "_session", lambda *a: (_ for _ in ()).throw(AssertionError("network used")))
    with pytest.raises(SystemExit) as e:
        W.main(["check", "--in", "x.csv"])
    assert e.value.code == 2 and "Token list problem" in capsys.readouterr().out


def test_scan_checks_personal_tokens(monkeypatch, tmp_path):
    personal_file(f"chain,symbol,address\nbase,FOO,{TOKEN_A}\n")
    called = []

    def fake_batch(sess, rpcs, calls):
        called.extend(p[0].get("to") for m, p in calls if m == "eth_call")
        return [None] * len(calls)
    monkeypatch.setattr(W, "rpc_batch", fake_batch)
    monkeypatch.setattr(W.time, "sleep", lambda *_: None)
    csv_path = tmp_path / "a.csv"
    csv_path.write_text("line,source,family,type,path,address\n1,address,evm,address,-,"
                        "0x9858EfFD232B4033E47d90003D41EC34EcaEda94\n")
    W.main(["check", "--in", str(csv_path), "--out", str(tmp_path / "b.csv"), "--chains", "base", "-q"])
    assert W.eip55(TOKEN_A) in called and MOR["base"] in called


def test_unknown_chain_in_tokens_command():
    with pytest.raises(SystemExit):
        W.main(["tokens", "--chains", "solana"])


# ---- on-chain verification (mocked RPC) -----------------------------------------------------
def abi_string(s):
    b = s.encode()
    return "0x" + (32).to_bytes(32, "big").hex() + len(b).to_bytes(32, "big").hex() + b.hex().ljust(64, "0")


def run_verify(monkeypatch, rows, chain_answers):
    entries = W.parse_token_csv(HEADER + "".join(r + "\n" for r in rows), "my.csv")

    def fake_batch(sess, rpcs, calls):
        out = []
        for m, p in calls:
            addr = (p[0] if m == "eth_getCode" else p[0]["to"]).lower()
            code, sym, dec = chain_answers.get(addr, ("0x", None, None))
            out.append(code if m == "eth_getCode" else sym if p[0]["data"] == "0x95d89b41" else dec)
        return out
    monkeypatch.setattr(W, "rpc_batch", fake_batch)
    return {e["symbol"]: (st, d) for e, st, d in W.verify_tokens(None, entries)}


def test_verify_outcomes(monkeypatch):
    a, b_, c, d = ("0x" + h * 40 for h in "abcd")
    answers = {a: ("0x6001", abi_string("FOO"), hex(18)),          # good
               b_: ("0x", None, None),                              # no contract
               c: ("0x6001", abi_string("NOTBAR"), hex(18)),       # wrong symbol
               d: ("0x6001", abi_string("USD₮0"), hex(6))}         # needs onchain_symbol
    rows = [f"base,FOO,{a},18,,,,", f"base,ZED,{b_},18,,,,", f"base,BAR,{c},18,,,,",
            f"base,USDT,{d},6,USD₮0,,,"]
    r = run_verify(monkeypatch, rows, answers)
    assert r["FOO"][0] == "OK" and r["USDT"][0] == "OK"
    assert r["ZED"] == ("FAIL", "no contract at this address on base")
    assert r["BAR"][0] == "FAIL" and "NOTBAR" in r["BAR"][1]


def test_verify_wrong_decimals(monkeypatch):
    a = "0x" + "a" * 40
    r = run_verify(monkeypatch, [f"base,FOO,{a},6,,,,"], {a: ("0x6001", abi_string("FOO"), hex(18))})
    assert r["FOO"][0] == "FAIL" and "18 decimals" in r["FOO"][1]


def test_verify_unreachable(monkeypatch):
    entries = W.parse_token_csv(HEADER + f"base,FOO,{'0x' + 'a' * 40},6,,,,\n", "my.csv")
    monkeypatch.setattr(W, "rpc_batch", lambda *a: None)
    assert W.verify_tokens(None, entries)[0][1] == "UNREACHABLE"


def test_verify_command_exit_code(monkeypatch):
    monkeypatch.setattr(W, "rpc_batch", lambda *a: None)
    with pytest.raises(SystemExit) as e:
        W.main(["tokens", "--verify", "--chains", "base", "-q"])
    assert e.value.code == 1


def test_abi_string_decoding():
    assert W._abi_string(abi_string("MOR")) == "MOR"
    assert W._abi_string("0x" + b"MKR".hex().ljust(64, "0")) == "MKR"    # old bytes32 style
    assert W._abi_string("0x") == ""


def test_missing_package_data_explains_the_reinstall(monkeypatch, capsys):
    from importlib import resources
    monkeypatch.setattr(resources, "files", lambda *_: (_ for _ in ()).throw(ModuleNotFoundError("x")))
    with pytest.raises(SystemExit) as e:
        W.main(["tokens"])
    out = capsys.readouterr().out
    assert e.value.code == 2 and 'pip install -e ".[sweep]"' in out
    personal_file(f"chain,symbol,address\nbase,FOO,{TOKEN_A}\n")
    W.main(["tokens", "--no-builtin-tokens"])                           # personal-only still works


def test_verify_contract_without_decimals_fails(monkeypatch):
    a = "0x" + "a" * 40                                                  # e.g. an NFT or other contract
    r = run_verify(monkeypatch, [f"base,FOO,{a},,,,,"], {a: ("0x6001", abi_string("FOO"), None)})
    assert r["FOO"] == ("FAIL", "decimals() failed - not an ERC20 token?")


def test_verify_partial_answers_are_unreachable_not_fail(monkeypatch):
    entries = W.parse_token_csv(HEADER + f"base,FOO,{'0x' + 'a' * 40},6,,,,\n", "my.csv")
    monkeypatch.setattr(W, "rpc_batch", lambda sess, rpcs, calls: [None] * len(calls))
    assert W.verify_tokens(None, entries)[0][1] == "UNREACHABLE"


def test_excel_bom_and_crlf_are_accepted():
    personal_file("\ufeffchain,symbol,address\r\nbase,FOO," + TOKEN_A + "\r\n")
    entries, _ = W.load_token_lists(use_builtin=False)
    assert [e["symbol"] for e in entries] == ["FOO"]


def test_non_utf8_personal_list_is_explained():
    path = personal_file("")
    with open(path, "wb") as f:
        f.write(b"chain,symbol,address,name\nbase,FOO," + TOKEN_A.encode() + b",Caf\xe9\n")
    with pytest.raises(W.TokenListError, match="not UTF-8"):
        W.load_token_lists()


def test_no_builtin_tokens_without_personal_list_is_an_error(capsys):
    with pytest.raises(SystemExit) as e:
        W.main(["tokens", "--no-builtin-tokens"])
    assert e.value.code == 2 and "needs a personal token list" in capsys.readouterr().out


def test_sweep_module_sees_personal_tokens():
    S = pytest.importorskip("walletcheck_sweep")
    personal_file(f"chain,symbol,address\nbase,FOO,{TOKEN_A}\n")
    W.apply_token_lists(W.load_token_lists()[0])
    assert S.W is W and S.W.EVM_CHAINS["base"]["tokens"]["FOO"] == W.eip55(TOKEN_A)


def test_script_mode_shares_one_module(tmp_path):
    """`python3 walletcheck.py sweep` must not load a second walletcheck module (which would only
    know the built-in tokens): `import walletcheck` inside the run must return the running script."""
    import subprocess
    import sys
    script = os.path.join(os.path.dirname(W.__file__), "walletcheck.py")
    code = ("import runpy, sys\n"
            f"sys.argv = [{script!r}, '--version']\n"
            "try:\n"
            f"    runpy.run_path({script!r}, run_name='__main__')\n"
            "except SystemExit:\n"
            "    pass\n"
            "import walletcheck\n"
            "print(walletcheck.__name__)\n")
    env = dict(os.environ, XDG_CONFIG_HOME=str(tmp_path), PYTHONPATH=os.path.dirname(script))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=tmp_path, env=env)
    assert out.stdout.strip().splitlines()[-1] == "__main__", out.stderr


def test_import_without_bip_utils_does_not_crash(tmp_path):
    import subprocess
    import sys
    blocker = tmp_path / "bip_utils"
    blocker.mkdir()
    (blocker / "__init__.py").write_text("raise ImportError('blocked for test')\n")
    code = "import walletcheck as W; print(W.TOKEN_LOAD_ERROR)"
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(tmp_path), os.path.dirname(W.__file__)]),
               XDG_CONFIG_HOME=str(tmp_path))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=tmp_path, env=env)
    assert out.returncode == 0 and "missing dependency bip-utils" in out.stdout, out.stderr

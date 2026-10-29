# Contributing

Thanks for helping! Bug reports, new chains/tokens, wallet path schemes and documentation fixes are all welcome.

## Ground rules

1. **Never commit or post real secrets.** Use the public test seed
   `abandon ... about`, published test vectors, or freshly generated throwaway keys.
2. **Secrets must never be printed, written or sent.** Any change touching input handling
   must keep `tests/test_privacy.py` passing.
3. **Derivation changes need test vectors.** Add an official vector (BIP, Electrum, wallet
   vendor docs) or extend the independent cross-validation in `tests/test_crossval.py`.
4. **A failed lookup must never look like an empty wallet.**
5. **Sweep changes need end-to-end tests** (`tests/test_sweep_*.py`): independent signature checks for
   Bitcoin, the in-process chain for EVM, and the leak checks in `tests/test_sweep_cli.py`. Nothing may
   be broadcast without the user's confirmation.

## Development setup

```bash
git clone https://github.com/r3n3x/walletcheck.git
cd walletcheck
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
walletcheck selftest
pytest -q
```

The test suite runs fully offline. CI runs it on Linux and macOS for Python 3.10-3.13.

## Adding a token

Tokens live in `walletcheck_tokens/tokens.csv`, not in the code. For a token only you need, use a
personal list instead (see "Token lists" in the README). For the built-in list:

1. Add one row per chain. The `address` must be in EIP-55 checksum form.
2. Fill `coingecko_id` (the coin's API id on CoinGecko) or `source` (a link to the issuer's official
   contract list). Rows without either are rejected.
3. Set `decimals`. If the contract's `symbol()` differs from the label (e.g. `USD₮0`), set
   `onchain_symbol`.
4. Run `walletcheck tokens --verify` (must print 0 FAIL) and `pytest -q`.

A new built-in symbol can clash with a symbol users already have in their personal list for another
contract; walletcheck then stops and asks them to rename theirs. Mention every added symbol in
`CHANGELOG.md` so users can see why.

Prefer tokens issued natively on that chain, and say in `name` when a token is bridged rather than
issued by its original issuer. A pull request that changes `tokens.csv` triggers the on-chain check in
CI.

## Adding an EVM chain

Add the chain to `EVM_CHAINS` at the top of `walletcheck.py` with at least two RPC endpoints from
different providers, add its chain id to `EVM_CHAIN_IDS` in `walletcheck_sweep.py`, then add its tokens
to `tokens.csv` as above.

## License of contributions

This project is public domain ([The Unlicense](LICENSE)). By submitting a contribution you
agree to dedicate it to the public domain under the same terms.

## Releasing

Bump `__version__` in `walletcheck.py`, move the changes into a dated section of `CHANGELOG.md`, and
keep the README's "Current version" line in sync.

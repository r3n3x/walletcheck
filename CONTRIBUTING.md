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

## Adding an EVM chain or token

Edit `EVM_CHAINS` at the top of `walletcheck.py`: add RPC endpoints (at least two, from
different providers) and token contract addresses. Token decimals are read on-chain.
Please link an official source for every contract address in your pull request.

## License of contributions

This project is public domain ([The Unlicense](LICENSE)). By submitting a contribution you
agree to dedicate it to the public domain under the same terms.

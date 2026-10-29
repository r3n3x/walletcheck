# Changelog

## Unreleased

- Zcash (transparent `t1...`, BIP44 coin 133) and Firo (transparent `a...`, BIP44 coin 136) are derived from seeds, xprv master keys, WIF keys, hex keys and compressed public keys. Balances and history are checked via Blockchair (Zcash) and the Firo Insight explorer.
- Shielded Zcash and Firo Spark addresses are not checked (they need viewing keys).

## 1.0.0 - 2026-10-29

First public release.

- Inputs: BIP39 seeds (+ passphrase, 4-letter abbreviations), Electrum v1/v2 seeds
  (+ seed extension), xpub/ypub/zpub/xprv/yprv/zprv, WIF and hex private keys,
  public keys, BTC and EVM addresses.
- Bitcoin: BIP44/49/84/86 (legacy, nested segwit, native segwit, taproot), Electrum paths.
- EVM: MetaMask/Trezor, Ledger Live and Ledger Legacy paths on Ethereum, Arbitrum,
  Polygon, Base, Optimism, BNB Chain and Avalanche, including major stablecoins.
- Adaptive `scan`: gap-limit discovery of addresses, change chains and accounts.
- Invalid seeds are diagnosed by word position without echoing words.
- Failed lookups and rejected inputs are reported loudly, never as "empty".
- Verbose (`-v`) and quiet (`-q`) output modes.
- Offline test suite: published test vectors, independent cross-validation against
  embit and eth-account, gap-limit logic and secret-leak tests.

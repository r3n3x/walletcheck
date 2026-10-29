# Changelog

## 1.0.1 - 2026-10-29

Fixes from the lookup-failure work (PR #1) and the follow-up review.

- Failed EVM and token lookups are reported as unknown, never as empty wallets.
- A failed token decimals call marks that token's balance as unknown instead of skipping it.
- Failed BTC lookups are listed as UNKNOWN, not under "NO HISTORY AT ALL".
- A partial EVM result that contains a real balance is still reported as found.
- An unknown `--chains` name is rejected before any lookup starts.
- A partially failed EVM lookup shows `nonce unknown` instead of `nonce None`.

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

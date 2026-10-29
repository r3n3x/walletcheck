# Changelog


## Unreleased - 1.1.0

- **New: `walletcheck sweep`** (optional, `pip install "walletcheck[sweep]"`) moves found funds to a new
  wallet. Bitcoin: all address types in one transaction, inputs verified against their previous
  transactions, ~1 hour fee (mempool.space hour fee), replace-by-fee. EVM: configured tokens first, then
  the native coin minus all fees; EIP-1559 tip based on what recent blocks paid; Base/Optimism L1 data
  fee included; endpoint chain id verified. Per chain: destination and endpoint prompts, signed plan,
  one y/N; `--dry-run` never broadcasts. Zcash/Firo/Monero and watch-only inputs are not swept. Hardened after an
  independent review: endpoints never see a transaction signed by the user's key before confirmation; tip
  capped at 3x recently paid tips; unusual fees need a typed `yes`; frozen tokens no longer block the
  native sweep; pending transactions, duplicate outputs, oversized transactions, malformed destinations
  and contract wallets missing on the target chain are handled.
- Zcash (transparent `t1...`, BIP44 coin 133) and Firo (transparent `a...`, BIP44 coin 136) are derived from seeds, xprv master keys, WIF keys, hex keys and compressed public keys. Balances and history are checked via Blockchair (Zcash) and the Firo Insight explorer.
- Shielded Zcash and Firo Spark addresses are not checked (they need viewing keys).
- Monero: a 25-word Monero seed (or 24 words without the checksum word) is detected and the
  primary address is derived **offline**. The address is NOT checked online: Monero balances
  can only be found by scanning the chain with the private view key, which must never be sent
  anywhere. The results show the address under section [5] with view-only-wallet instructions
  for checking it against your own node.
- MyMonero-style 13-word seeds are not supported (different derivation).

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

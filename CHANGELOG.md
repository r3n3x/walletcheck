# Changelog

## 1.3.0 - 2026-10-29

- **Token lists in two layers.** The built-in list moved from the code into
  `walletcheck_tokens/tokens.csv` and grew from 17 to 34 tokens: USDS, PYUSD and USDe on Ethereum;
  MOR (Morpheus) on Ethereum, Arbitrum and Base; DAI on Arbitrum, Base and Optimism; USDT on Base and
  Optimism (bridged) plus USDT0 on Optimism; USDC, USDT, USDC.e and USDT.e on Avalanche. Every
  contract was cross-checked against CoinGecko and verified on-chain.
- **Personal token list:** `~/.config/walletcheck/tokens.csv` (or `$XDG_CONFIG_HOME/walletcheck/`) is
  loaded automatically when it exists and adds to the built-in list. `--tokens FILE` uses another file,
  `--no-builtin-tokens` checks only your own. Rows are validated (chain, EIP-55 checksum, symbol)
  before anything goes online; symbols are plain ASCII, and a symbol that would shadow another
  contract on the same chain is refused. `sweep` sweeps personal tokens too, also when run as
  `python3 walletcheck.py sweep`.
- **New: `walletcheck tokens`** lists the tokens that are checked; `--verify` checks every contract
  on-chain (code present, `symbol()` and `decimals()` as expected). A scheduled CI job re-verifies the
  built-in list on the 1st and 15th of every month.
- Tokens are still only checked from an allowlist matched by contract address, so spam and look-alike
  tokens never show up as balances.
- **Editable installs (`pip install -e`) must be re-run once after updating**, because the token list
  is a new data package.

## 1.2.0 - 2026-10-29

- **New: `walletcheck sweep`** (optional, `pip install "walletcheck[sweep]"`) moves found funds to a new
  wallet. Bitcoin: all address types in one transaction, inputs verified against their previous
  transactions, ~1 hour fee (mempool.space hour fee), replace-by-fee. EVM: configured tokens first, then
  the native coin minus all fees; EIP-1559 tip based on what recent blocks paid; Base/Optimism L1 data
  fee included; endpoint chain id verified. Per chain: destination and endpoint prompts, signed plan,
  one y/N; `--dry-run` never broadcasts. Zcash/Firo/Monero and watch-only inputs are not swept.
- Sweep was hardened after an independent review: endpoints never see a transaction signed by the
  user's key before confirmation; the tip is capped at 3x recently paid tips and cross-checked against
  an independent endpoint; unusual fees need a typed `yes`; frozen tokens no longer block the native
  sweep; pending transactions, duplicate outputs, oversized transactions, malformed destinations and
  contract wallets missing on the target chain are handled.
- Monero output now states correctly that `--restore-deterministic-wallet` restores the full wallet
  (view-only needs `--generate-from-view-key` with the address and private view key).
- Every command option shows its default in `--help`; the README documents all commands and options.

## 1.1.0 - 2026-10-29

- Zcash (transparent `t1...`, BIP44 coin 133) and Firo (transparent `a...`, BIP44 coin 136) are derived
  from seeds, xprv master keys, WIF keys, hex keys and compressed public keys. Balances and history are
  checked via Blockchair (Zcash) and the Firo Insight explorer.
- Shielded Zcash and Firo Spark addresses are not checked (they need viewing keys).
- Monero: a 25-word Monero seed (or 24 words without the checksum word) is detected and the
  primary address is derived **offline**. The address is NOT checked online: Monero balances
  can only be found by scanning the chain with the private view key, which must never be sent
  anywhere. The results show the address under section [5] with instructions for checking it
  against your own node.
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

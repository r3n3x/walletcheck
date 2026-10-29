# walletcheck

[![tests](https://github.com/r3n3x/walletcheck/actions/workflows/tests.yml/badge.svg)](https://github.com/r3n3x/walletcheck/actions/workflows/tests.yml)
[![License: Unlicense](https://img.shields.io/badge/license-Unlicense-blue.svg)](LICENSE)

**Find out whether old seed phrases, private keys or xpubs still hold funds, without your secrets ever leaving your computer.**

You are tidying up old notes and find a seed phrase, a WIF key or an xpub. Does it still hold anything? Pasting it into a website or an AI chat would expose it. `walletcheck` derives the public addresses **locally** and only sends those public addresses to public block explorers.

```
 your secrets ──► walletcheck (local, in memory) ──► public addresses ──► block explorers
   never leave                                         the only thing      mempool.space,
   this computer                                       that goes online    public EVM RPCs
```

## Features

- **Many input formats**: BIP39 seeds (with passphrase), Electrum v1 and v2 seeds (with seed extension), Monero seeds (address derived offline), xpub/ypub/zpub/xprv/yprv/zprv, WIF and hex private keys, public keys, plain addresses.
- **Bitcoin**: legacy, nested segwit, native segwit and taproot (BIP44/49/84/86), Electrum paths.
- **EVM**: MetaMask/Trezor, Ledger Live and Ledger Legacy paths on Ethereum, Arbitrum, Polygon, Base, Optimism, BNB Chain and Avalanche, including major stablecoins.
- **Zcash and Firo (transparent addresses)**: Zcash `t1...` (BIP44 coin 133) and Firo `a...` (BIP44 coin 136) from the same seed, WIF and hex keys, and checked against Blockchair (Zcash) and the Firo Insight explorer. Shielded addresses are not checked (see Limitations).
- **Adaptive scanning**: checks the first few addresses and only goes deeper where it finds activity, the same way real wallets discover addresses. Change addresses and extra accounts are only checked when used.
- **Honest results**: rejected inputs and failed lookups are flagged loudly, never shown as "empty". Typos in seed phrases are diagnosed by word *position*, without printing your words.
- **Optional sweep**: `walletcheck sweep` moves found BTC and EVM funds (native coins and tokens) to a new wallet you choose. Signing happens locally; only signed transactions are sent. See [Sweeping funds](#sweeping-funds-optional).
- **Verified**: published test vectors (BIP, Electrum) and cross-validation against independent libraries run automatically on every change.

## Install

Requires **Python 3.10-3.13**.

> **Python 3.14 note:** Python 3.14 is still capped in `pyproject.toml` (`requires-python = ">=3.10,<3.14"`). The reason: the `coincurve` dependency does not publish wheels for 3.14 yet, so installing on 3.14 fails. The cap will be removed once those wheels are published. Use Python 3.10 to 3.13 until then.

**macOS (Homebrew)**

```bash
brew install python@3.13
python3.13 -m venv ~/walletcheck-venv
source ~/walletcheck-venv/bin/activate
pip install git+https://github.com/r3n3x/walletcheck.git
walletcheck selftest          # should end with SELFTEST PASSED
```

**Linux**: same steps with your distribution's Python 3.10-3.13.

**Windows**: should work in the same way (`py -3.13 -m venv ...`), but is untested. Feedback welcome.

To use it later without activating the venv, add an alias, e.g. to `~/.zshrc`:

```bash
alias walletcheck="$HOME/walletcheck-venv/bin/walletcheck"
```

## Usage

```bash
walletcheck scan                     # hidden prompt: paste one item per prompt
walletcheck scan --in secrets.txt    # or read from a file, one item per line
walletcheck scan -v                  # verbose: show every address and result
walletcheck scan -q                  # quiet: results only
```

With the hidden prompt nothing you paste is shown on screen or stored in your shell history. After a seed phrase you are asked for an optional passphrase / seed extension.

**Input file format** (`#` lines are ignored; all examples below belong to the public test seed):

```
# BIP39 or Electrum seed, optionally with a passphrase after " | "
abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about
abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about | my passphrase
zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtfSdVCToUG868RvUUkgDKf31mGDtKsAYz2oz2AGutZYs
KyZpNDKnfs94vbrwhJneDi77V6jF64PWPF8x5cdJb8ifgg2DUc9d
bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu
```

**Try it safely first** with the public test seed `abandon abandon ... about` (11 × `abandon`, then `about`). It is a well-known test seed with lots of history, so you should see results in section [2].

### Example output

Real output for the public test seed plus `bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh` (a well-known example address), checking Ethereum only (shortened):

```
Step 1/3 - Reading inputs (secrets stay on this computer)
  line   1: seed12 -> BIP39
  line   2: BTC address
  2 input(s) read, 2 usable, 0 rejected.

Step 2/3 - Checking public addresses online (adaptive: first 10 BTC / 5 EVM per chain, ...)
  line   1 m/44'/0'/0'/0/* p2pkh                  checked  28  USED (last used #24)
  line   1 m/44'/0'/0'/1/* p2pkh                  checked  15  USED (last used #11)
  line   1 m/49'/0'/1'/0/* p2sh-p2wpkh            checked  10  unused
  line   1 m/84'/0'/0'/0/* p2wpkh                 checked  31  USED (last used #27)
  ...
  321 unique addresses checked with 321 online lookups in 84s.

========================================================================
RESULTS
========================================================================

[1] BALANCES FOUND (funds you can still move)
    line 1 [seed12-BIP39] ethereum m/44'/60'/0'/0/0
      0x9858EfFD232B4033E47d90003D41EC34EcaEda94
      -> 2.00e-18 (dust) ETH (nonce 1775)
    line 2 [address] bitcoin -
      bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh
      -> 3.92755668 BTC (1149 txs)

[2] USED BEFORE, NOW EMPTY (the wallet was real, funds moved out)
    line 1 [seed12-BIP39]: 180 address/chain combination(s) with history

[3] NO HISTORY AT ALL on the checked addresses
    line(s): -
```

The result sections mean:

| Section | Meaning |
|---|---|
| `[1] BALANCES FOUND` | Funds on a checked address, chain or token. Move them to a fresh wallet. |
| `[2] USED BEFORE, NOW EMPTY` | Transactions exist but nothing is left. |
| `[3] NO HISTORY AT ALL` | Lookups succeeded and the address has never been used. |
| `[4] UNKNOWN` | A lookup failed, so these lines were **not** fully checked. Re-run them. |

If a lookup fails, the run ends with a warning box. Failed lookups are never shown as empty.

Results are also saved as CSV: `addresses.csv` (every address checked) and `balances.csv` (per address and chain). Both contain public data only.

## How the adaptive scan works

Wallets hand out addresses in order, so once several unused addresses follow the last used one, there is nothing further to find. `scan` uses this to keep lookups low:

| Level | Rule |
|---|---|
| Receive addresses | Always check the first 10 (BTC) or 5 (EVM, per path scheme). Then continue while a used address is within `--gap` (default 3) of the end. |
| Change addresses | Only if the account's receive addresses were used |
| Accounts 1, 2, ... | Only if the previous account was used (up to 20) |

An unused seed costs about 55 lookups instead of several hundred. A used wallet is followed as deep as its activity goes.

**Trade-off:** the default gap of 3 is tighter than the wallet standard of 20. Wallets that generated many unused addresses before receiving funds (merchant or donation setups) can be missed. For a thorough check use `--gap 20`, which also raises the minimum to 20 addresses per chain.

| Option | Default | Meaning |
|---|---|---|
| `--gap` | 3 | Unused addresses after the last used one before stopping |
| `--initial` | 10 | BTC addresses always checked per chain |
| `--eth-initial` | 5 | EVM addresses always checked per path scheme |
| `--chains` | all | Limit EVM chains, e.g. `--chains ethereum arbitrum` |
| `--proxy` | none | Route lookups through a proxy, e.g. Tor: `socks5h://127.0.0.1:9050` |
| `-v` / `-q` | | Verbose / quiet output |

## Sweeping funds (optional)

`walletcheck sweep` moves what `scan` found into a **new wallet you control**. It is the only command that moves funds, so it is opt-in and needs two extra libraries:

```bash
pip install "walletcheck[sweep] @ git+https://github.com/r3n3x/walletcheck.git"
walletcheck sweep                  # hidden prompt for your secrets, like scan
walletcheck sweep --dry-run        # build and sign, show everything, never broadcast
```

What happens:

1. The same adaptive scan finds funded addresses.
2. Private keys are re-derived **in memory** for those addresses only. Each key must reproduce its exact address, checked with a second independent library, or the sweep refuses to sign.
3. For each chain with funds, you are asked whether to sweep it, the destination address and the broadcast endpoint (Enter = public default, or your own node).
4. The signed plan is shown: inputs, amount, fee and destination. **One `y` broadcasts it.** If the fee is unusual (over 10% of the amount, or over 100 sat/vB), you must type `yes` instead.

| | Bitcoin | EVM chains |
|---|---|---|
| What is moved | All confirmed outputs, all address types (legacy incl. uncompressed, nested and native segwit, taproot), one transaction | Configured tokens first, then the native coin minus all fees |
| Fee target | mempool.space "hour fee" rate (~1 hour), replace-by-fee enabled | EIP-1559: max fee = 2 x base fee + tip, the tip is taken from what recent blocks actually paid (normally minutes) |
| Safety checks | Every input is verified against its full previous transaction (hash, script, amount), so an endpoint cannot misreport amounts; duplicate outputs are ignored | The endpoint's chain id must match; a failed call aborts instead of counting as zero; the tip is capped at 3x what recent blocks paid and cross-checked against a second, independent endpoint; the endpoint never receives a signed transaction before you confirm |
| Skipped and reported | Unconfirmed outputs; outputs worth less than their own fee; results below the dust limit; anything beyond one standard-size transaction (sweep again afterwards) | Tokens when there is no native coin for gas (shows how much is needed); tokens that cannot be transferred (frozen or paused); addresses with pending transactions |

Destination addresses are checked (checksum, mainnet, not one of the swept addresses). An EVM destination that is a smart contract (e.g. a Safe) on some chain but not on the chain being swept is refused, because funds sent there could be lost. If that can't be checked on every chain, you must type `yes` to continue. A small amount of native coin may remain on EVM addresses as unused fee headroom.

Good to know:

- **Privacy:** all Bitcoin inputs go into one transaction, which links the swept wallets on-chain. To keep wallets separate, sweep one secret per run.
- **Thoroughness:** sweep uses the same adaptive scan as `scan`. Use `--gap 20` to sweep everything a wallet could have used.
- **Dry run:** `--dry-run` prints fully signed transactions. Anyone who gets them can broadcast them, so don't paste them anywhere unless you intend to send them.
- **Lookups that fail** are listed by address; sweep again later to cover them.

**Not swept:** Zcash and Firo (reported; use their own wallets), Monero, watch-only inputs (xpub, public keys, addresses), multisig.

> ⚠️ **Transactions cannot be reversed.** Double-check the destination, and do a first sweep with a small amount. Mature wallets also offer sweeping: for large amounts, consider Electrum or Sparrow (Bitcoin) or importing the key into Rabby/MetaMask (EVM).

**Fixed-count mode:** `walletcheck derive` writes a fixed list of addresses to `addresses.csv` without any network access. `walletcheck check` then looks that list up. This is useful if you want to inspect or edit the address list first.

## Security model

**What it guarantees**

- Secrets are only used in memory to derive public addresses.
- Secrets are never printed, written to disk or sent anywhere (enforced by `tests/test_privacy.py` and `tests/test_sweep_cli.py`).
- `scan`, `derive` and `check` only read public data. Only `sweep` moves funds, and only after you confirm a signed plan; it broadcasts signed transactions, never keys.
- Only public addresses are sent to [mempool.space](https://mempool.space) / [blockstream.info](https://blockstream.info) and public EVM RPC endpoints (publicnode, dRPC and official chain RPCs).

**What it cannot protect against**

- **Privacy:** explorers see your IP and all addresses you query, so they can link them to each other. Use `--proxy` with Tor or a VPN if that matters.
- **Your computer:** malware or a compromised Python environment can read anything you paste. Read the code: `walletcheck.py` (scanning) and `walletcheck_sweep.py` (sweeping).
- **Past exposure:** keys that sat in plain-text notes should be treated as exposed. **If you find funds, move them to a fresh wallet.**

## Limitations

- Only standard derivation paths are checked. Exotic custom paths are not.
- Token coverage is limited to major stablecoins and a few chain tokens. For complete token and NFT coverage, paste the *addresses* (never keys) into a portfolio viewer such as DeBank.
- Not supported: Electrum 2FA seeds (need TrustedCoin's cosigner), multisig wallets, Litecoin and other non-EVM altcoins.
- **Zcash shielded (`z…`, `u…`) and Firo Spark addresses are not checked.** Seeing their balances needs a viewing key and a light-client scan. A public explorer would receive the viewing key, which breaks the privacy promise, so this tool does not do it.
- Zcash and Firo lookups show the confirmed balance only. Firo unconfirmed amounts are not included.
- **Monero is derived but not checked.** Seeing a Monero balance requires scanning the blockchain with the private view key; no website can do that without learning the key, so walletcheck only derives the address offline and shows how to check it in a view-only wallet on your own node.
- **Monero: only the first (primary) address is derived** (account 0, index 0). Subaddresses and other accounts are not derived, so funds sent to them are not covered by the Monero check.
- **Monero Polyseed (the newer 16-word format) is not yet supported.** MyMonero-style 13-word seeds are not supported either. Only standard 25-word Monero seeds (and 24 words without the checksum word) are derived.
- Public RPC endpoints can be rate-limited or change. Failed lookups are reported; re-run to retry.

## Verification

```bash
walletcheck selftest                 # published BIP and Electrum test vectors
pip install -e ".[test]" && pytest   # full offline test suite
```

The test suite covers:

- published test vectors;
- cross-validation of every input format against independent libraries ([embit](https://github.com/diybitcoinhardware/embit) for Bitcoin, [eth-account](https://github.com/ethereum/eth-account) for Ethereum);
- the gap-limit logic;
- secret-leak tests;
- sweep: every Bitcoin signature re-checked with a second library ([bitcoin-utils](https://github.com/karask/python-bitcoin-utils) sighash + coincurve), endpoints that lie about amounts, and EVM sweeps of native coins and OpenZeppelin ERC20 tokens end to end on an in-process Ethereum chain.

It runs on Linux and macOS for Python 3.10-3.13 on every push.

## Contributing

Issues and pull requests are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).

**Never post real seeds or keys in issues.** Report security problems privately as described in [SECURITY.md](SECURITY.md).

## License

Public domain via [The Unlicense](LICENSE): free for any personal or commercial use, no conditions.

**No warranty.** `scan`, `derive` and `check` only read public blockchain data. `sweep` moves funds, irreversibly, after your confirmation. You use this tool at your own risk. Not financial advice.

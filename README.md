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

- **Many input formats**: BIP39 seeds (with passphrase), Electrum v1 and v2 seeds (with seed extension), xpub/ypub/zpub/xprv/yprv/zprv, WIF and hex private keys, public keys, plain addresses.
- **Bitcoin**: legacy, nested segwit, native segwit and taproot (BIP44/49/84/86), Electrum paths.
- **EVM**: MetaMask/Trezor, Ledger Live and Ledger Legacy paths on Ethereum, Arbitrum, Polygon, Base, Optimism, BNB Chain and Avalanche, including major stablecoins.
- **Adaptive scanning**: checks the first few addresses and only goes deeper where it finds activity, the same way real wallets discover addresses. Change addresses and extra accounts are only checked when used.
- **Honest results**: rejected inputs and failed lookups are flagged loudly, never shown as "empty". Typos in seed phrases are diagnosed by word *position*, without printing your words.
- **Verified**: published test vectors (BIP, Electrum) and cross-validation against independent libraries run automatically on every change.

## Install

Requires **Python 3.10-3.13**.

> **Python 3.14 note:** the `coincurve` dependency does not ship ready-made packages for 3.14 yet, so installing on 3.14 fails. Use 3.13.

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

**Fixed-count mode:** `walletcheck derive` writes a fixed list of addresses to `addresses.csv` without any network access. `walletcheck check` then looks that list up. This is useful if you want to inspect or edit the address list first.

## Security model

**What it guarantees**

- Secrets are only used in memory to derive public addresses.
- Secrets are never printed, written to disk or sent anywhere (enforced by `tests/test_privacy.py`).
- Only public addresses are sent to [mempool.space](https://mempool.space) / [blockstream.info](https://blockstream.info) and public EVM RPC endpoints (publicnode, dRPC and official chain RPCs).

**What it cannot protect against**

- **Privacy:** explorers see your IP and all addresses you query, so they can link them to each other. Use `--proxy` with Tor or a VPN if that matters.
- **Your computer:** malware or a compromised Python environment can read anything you paste. Read the code; it is a single file.
- **Past exposure:** keys that sat in plain-text notes should be treated as exposed. **If you find funds, move them to a fresh wallet.**

## Limitations

- Only standard derivation paths are checked. Exotic custom paths are not.
- Token coverage is limited to major stablecoins and a few chain tokens. For complete token and NFT coverage, paste the *addresses* (never keys) into a portfolio viewer such as DeBank.
- Not supported: Electrum 2FA seeds (need TrustedCoin's cosigner), multisig wallets, Litecoin and other non-EVM altcoins.
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
- secret-leak tests.

It runs on Linux and macOS for Python 3.10-3.13 on every push.

## Contributing

Issues and pull requests are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).

**Never post real seeds or keys in issues.** Report security problems privately as described in [SECURITY.md](SECURITY.md).

## License

Public domain via [The Unlicense](LICENSE): free for any personal or commercial use, no conditions.

**No warranty.** This tool only reads public blockchain data and never moves funds, but you use it at your own risk. Not financial advice.

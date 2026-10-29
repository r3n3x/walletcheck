# walletcheck

[![tests](https://github.com/r3n3x/walletcheck/actions/workflows/tests.yml/badge.svg)](https://github.com/r3n3x/walletcheck/actions/workflows/tests.yml)
[![License: Unlicense](https://img.shields.io/badge/license-Unlicense-blue.svg)](LICENSE)

**Find out whether old seed phrases, private keys or xpubs still hold funds, without your secrets ever leaving your computer. Optionally, move what you find to a new wallet.**

You are tidying up old notes and find a seed phrase, a WIF key or an xpub. Does it still hold anything? Pasting it into a website or an AI chat would expose it. `walletcheck` derives the public addresses **locally** and only sends those public addresses to public block explorers.

```
 your secrets ──► walletcheck (local, in memory) ──► public addresses ──► block explorers / RPC nodes
   never leave                                         the only thing      mempool.space, Blockchair,
   this computer                                       that goes online    public EVM RPCs, ...
```

Current version: **1.2.0** ([changelog](CHANGELOG.md)). Check yours with `walletcheck --version`.

**Contents:** [Features](#features) · [What is checked](#what-is-checked) · [Install](#install) · [Quick start](#quick-start) · [Commands](#commands) · [Input formats](#input-formats) · [Reading the results](#reading-the-results) · [Adaptive scan](#how-the-adaptive-scan-works) · [Sweeping funds](#sweeping-funds-optional) · [Security model](#security-model) · [Limitations](#limitations) · [Verification](#verification)

## Features

- **Many input formats:** BIP39 seeds (with passphrase, 4-letter abbreviations), Electrum v1/v2 seeds (with seed extension), Monero seeds, xpub/ypub/zpub/xprv/yprv/zprv, WIF and hex private keys, public keys, plain BTC and EVM addresses.
- **Many chains:**
  - **Bitcoin:** all common address types.
  - **EVM:** 7 chains, native coins plus major tokens.
  - **Zcash and Firo:** transparent addresses.
  - **Monero:** address derived offline.
- **Adaptive scanning:** checks the first few addresses of each wallet chain and only goes deeper where it finds activity, the way real wallets discover addresses.
- **Honest results:** rejected inputs and failed lookups are flagged loudly, never shown as "empty". Typos in seed phrases are diagnosed by word *position*, without printing your words.
- **Optional sweep:** `walletcheck sweep` moves found BTC and EVM funds to a new wallet you choose. Signing is local; only signed transactions leave your computer.
- **Verified:** published test vectors, cross-validation against independent libraries, and end-to-end sweep tests run on every change.

## What is checked

| Chain | Addresses derived from a seed | Data source | Balance check | Sweep |
|---|---|---|---|---|
| **Bitcoin** | Legacy `1…` (BIP44), nested segwit `3…` (BIP49), native segwit `bc1q…` (BIP84), taproot `bc1p…` (BIP86); Electrum paths | mempool.space, fallback blockstream.info | ✅ | ✅ |
| **Ethereum, Arbitrum, Polygon, Base, Optimism, BNB Chain, Avalanche** | MetaMask/Trezor, Ledger Live and Ledger Legacy path schemes | Public RPCs (publicnode, dRPC, official endpoints) | ✅ native coin + tokens below | ✅ |
| **Zcash** (transparent `t1…`) | BIP44 coin 133 | Blockchair | ✅ confirmed balance | – |
| **Firo** (transparent `a…`) | BIP44 coin 136 | Firo Insight explorer | ✅ confirmed balance | – |
| **Monero** | Primary address only | none (see [Limitations](#limitations)) | – derived offline only | – |

**Tokens checked:**

| Chain | Tokens |
|---|---|
| Ethereum | USDT, USDC, DAI, WETH, WBTC |
| Arbitrum | USDC, USDC.e, USDT, ARB |
| Polygon | USDC, USDC.e, USDT |
| Base | USDC |
| Optimism | USDC, OP |
| BNB Chain | USDT, USDC |

Avalanche has no tokens configured. To add chains or tokens, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Install

Requires **Python 3.10-3.13**.

> **Python 3.14:** not supported yet. The `coincurve` dependency has no ready-made packages for 3.14, so `pyproject.toml` caps Python at `<3.14`. The cap will be removed once those packages exist.

**macOS (Homebrew)**

```bash
brew install python@3.13
python3.13 -m venv ~/walletcheck-venv
source ~/walletcheck-venv/bin/activate
pip install "walletcheck[sweep] @ git+https://github.com/r3n3x/walletcheck.git"
walletcheck selftest          # should end with SELFTEST PASSED
```

Leave out `[sweep]` if you only want to check balances. `[sweep]` adds the two signing libraries that `walletcheck sweep` needs: embit and eth-account.

**Linux:** the same steps with your distribution's Python 3.10-3.13.

**Windows:** should work the same way (`py -3.13 -m venv ...`), but is untested. Feedback welcome.

**Use it without activating the venv:** add an alias, e.g. to `~/.zshrc`:

```bash
alias walletcheck="$HOME/walletcheck-venv/bin/walletcheck"
```

**Update to the latest version:**

```bash
~/walletcheck-venv/bin/pip install --upgrade "walletcheck[sweep] @ git+https://github.com/r3n3x/walletcheck.git"
# or, if you cloned the repository and installed it with `pip install -e`:
cd walletcheck && git pull && pip install -e ".[sweep]"
```

If pip answers "already satisfied" without updating, add `--force-reinstall`. Then run `walletcheck --version` and `walletcheck selftest`.

## Quick start

```bash
walletcheck selftest       # verify the derivation code on your machine
walletcheck scan           # paste your seeds/keys one by one (hidden), press Enter on an empty prompt to start
```

**Try it safely first** with the public test seed `abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about`. It is publicly known and heavily used by testers, so results appear in sections [1] and [2].

## Commands

| Command | What it does | Network | Moves funds |
|---|---|---|---|
| `walletcheck scan` | Derives addresses and checks them, adaptively (**recommended**) | yes, public addresses only | no |
| `walletcheck derive` | Derives a fixed number of addresses into `addresses.csv` | **no** | no |
| `walletcheck check` | Checks the addresses in `addresses.csv` | yes, public addresses only | no |
| `walletcheck sweep` | Scans, then moves found BTC/EVM funds to a new wallet after your confirmation | yes | **yes** |
| `walletcheck selftest` | Checks the derivation code against published BIP and Electrum test vectors | no | no |

All commands accept `-v` (verbose: every address and its result) or `-q` (quiet: results only). `walletcheck <command> --help` lists everything.

### scan

```bash
walletcheck scan                          # hidden prompt
walletcheck scan --in secrets.txt         # read inputs from a file
walletcheck scan --gap 20                 # thorough: wallet-standard gap limit
walletcheck scan --chains ethereum base   # only these EVM chains
```

| Option | Default | Meaning |
|---|---|---|
| `--in FILE` | hidden prompt | Read inputs from a file, one per line |
| `--gap N` | 3 | Stop after N unused addresses follow the last used one (wallet standard: 20) |
| `--initial N` | 10 | Bitcoin, Zcash and Firo addresses always checked per chain |
| `--eth-initial N` | 5 | EVM addresses always checked per path scheme |
| `--max-index N` | 1000 | Hard cap per chain |
| `--chains CHAIN …` | all | Limit the **EVM** chains. Bitcoin, Zcash and Firo are always checked |
| `--proxy URL` | none | Route lookups through a proxy, e.g. Tor: `socks5h://127.0.0.1:9050` |
| `--delay SEC` | 0.3 | Pause between Bitcoin/Zcash/Firo lookups |
| `--addresses FILE` | `addresses.csv` | Where to save the list of checked addresses |
| `--out FILE` | `balances.csv` | Where to save the per-address results |

**The hidden prompt:**
- Paste **one item per prompt**. Nothing is shown on screen or stored in your shell history.
- After a seed phrase you are asked for an optional passphrase / seed extension.
- Press Enter on an empty prompt to start.

### derive and check (fixed-count mode)

```bash
walletcheck derive --in secrets.txt       # no network: writes addresses.csv
walletcheck check                         # looks up addresses.csv, writes balances.csv
```

Useful when you want to inspect or edit the address list before anything goes online, or derive on an offline machine and check elsewhere. `derive` uses fixed counts instead of the adaptive scan:

| Option (`derive`) | Default | Meaning |
|---|---|---|
| `--btc-receive N` | 20 | Receive addresses per Bitcoin/Zcash/Firo chain |
| `--btc-change N` | 10 | Change addresses per Bitcoin/Zcash/Firo chain |
| `--eth-count N` | 5 | Addresses per EVM path scheme |
| `--out FILE` | `addresses.csv` | Output file |

`check` takes `--in` (default `addresses.csv`), `--out` (default `balances.csv`), `--chains`, `--proxy` and `--delay` as in `scan`.

### sweep

See [Sweeping funds](#sweeping-funds-optional).

### selftest

```bash
walletcheck selftest
```

Re-derives published test vectors (BIP44/49/84/86, Ethereum, and Electrum's own test seeds) and must end with `SELFTEST PASSED`. Run it after installing or updating.

## Input formats

One item per prompt, or one per line in a file (lines starting with `#` are ignored). The examples belong to public test vectors; never put real funds on them.

| Input | Example | Addresses checked |
|---|---|---|
| BIP39 seed, 12-24 words | `abandon abandon … about` | Bitcoin (4 types), EVM (3 path schemes), Zcash, Firo |
| …with passphrase | `abandon abandon … about \| my passphrase` | as above, for the passphrase wallet |
| …abbreviated to 4 letters (steel plates) | `aban aban … abou` | as above (expanded automatically) |
| Electrum v2 seed (standard / segwit) | `cycle rocket west magnet …` | Bitcoin, Electrum's own paths; `\| extension` for a seed extension |
| Electrum v1 (old) seed, 12 words | `powerful random nobody notice …` | Bitcoin legacy |
| Monero seed, 25 words (or 24 without checksum word) | `fawns bowling arsenic …` | Monero primary address, **offline only** |
| xprv / yprv / zprv, master key | `xprv9s21ZrQH143K…` | like a BIP39 seed |
| xpub / xprv, account level | `xpub6BosfCnifzxc…` | Bitcoin (all 4 types) + EVM |
| ypub / yprv, zpub / zprv, account level | `zpub6rFR7y4Q2Aij…` | Bitcoin nested / native segwit |
| WIF private key, compressed (`K…`/`L…`) | `KyZpNDKnfs94vbrw…` | Bitcoin (4 types), EVM, Zcash, Firo |
| WIF private key, uncompressed (`5…`) | `5KY3dHRWNnFkBJaT…` | Bitcoin legacy, EVM |
| Hex private key, 64 characters (`0x` optional) | `1ab42cc412b618bd…` | Bitcoin (all types incl. uncompressed legacy), EVM, Zcash, Firo |
| Hex public key, compressed or uncompressed | `0330d54fd0dd420a…` | Bitcoin, EVM; compressed also Zcash, Firo |
| Bitcoin address | `bc1qcr8te4kr609g…` | that address |
| EVM address | `0x9858EfFD232B40…` | that address on all EVM chains |

Seed phrases that fail validation are rejected with a reason:
- a word position that isn't a valid word;
- a checksum failure with all words valid, meaning a wrong word or wrong order;
- an Electrum 2FA seed, which can't be derived because it needs TrustedCoin's co-signer.

Your words are never printed.

## Reading the results

Real output for the public test seed plus a well-known example address, Ethereum only (shortened):

```
Step 1/3 - Reading inputs (secrets stay on this computer)
  line   1: seed12 -> BIP39
  line   2: BTC address
  2 input(s) read, 2 usable, 0 rejected.

Step 2/3 - Checking public addresses online (adaptive: first 10 BTC / 5 EVM per chain,
           continuing while a used address is within 3 of the end; change/next account only if used)
  line   1 m/44'/0'/0'/0/* p2pkh                  checked  28  USED (last used #24)
  line   1 m/84'/0'/0'/0/* p2wpkh                 checked  31  USED (last used #27)
  line   1 m/86'/0'/1'/0/* p2tr                   checked  10  unused
  line   1 metamask/trezor m/44'/60'/0'/0/*       checked 104  USED (last used #100)
  line   1 m/44'/133'/0'/0/*                      checked  10  USED (last used #0)
  line   1 m/44'/136'/0'/0/*                      checked  10  USED (last used #1)
  ...
  381 unique addresses checked with 381 online lookups in 131s.

========================================================================
RESULTS
========================================================================

[1] BALANCES FOUND (funds you can still move)
    line 1 [seed12-BIP39] ethereum m/44'/60'/0'/0/0
      0x9858EfFD232B4033E47d90003D41EC34EcaEda94
      -> 2.00e-18 (dust) ETH (nonce 1777)
    line 1 [seed12-BIP39] Zcash m/44'/133'/0'/0/0
      t1XVXWCvpMgBvUaed4XDqWtgQgJSu1Ghz7F
      -> 0.00001000 ZEC (1 txs)
    line 2 [address] bitcoin -
      bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh
      -> 3.92755668 BTC (1149 txs)

[2] USED BEFORE, NOW EMPTY (the wallet was real, funds moved out)
    line 1 [seed12-BIP39]: 182 address/chain combination(s) with history

[3] NO HISTORY AT ALL on the checked addresses
    line(s): -
```

| Section | Meaning |
|---|---|
| `[1] BALANCES FOUND` | Funds on a checked address, chain or token. Tiny amounts are marked `(dust)`. |
| `[2] USED BEFORE, NOW EMPTY` | Transactions exist but nothing is left. |
| `[3] NO HISTORY AT ALL` | Lookups succeeded and the checked addresses were never used. |
| `[4] UNKNOWN` | A lookup failed, so these lines were **not** fully checked. Re-run them. Failed lookups are never shown as empty. |
| `[5] MONERO` | Monero address derived offline, with instructions to check it on your own node. |

Section [5] looks like this (public Monero test vector):

```
[5] MONERO - primary address derived offline, NOT checked online
    (only the first address, account 0 index 0; subaddresses are not derived)
    line 1 [monero-seed] 49WpyDh52VKh1PWTR82nAqPSu33EcjtT8X5ga67WcsuoLK63wpk7ThZAX2z3KVHMZyCt2rRffcxYnZddJivn5bXTHiWcLc3
    Monero balances cannot be checked here privately: the chain must be scanned
    with the private view key, and no explorer can do that without learning it.
    Check it with monero-wallet-cli connected to your own node:
      --restore-deterministic-wallet   restores the FULL wallet from the seed ('balance')
      --generate-from-view-key         view-only: needs the address and private view key
```

`scan` and `check` also save two CSV files, both containing **public data only**:
- `addresses.csv`: every address checked;
- `balances.csv`: the result per address and chain.

`sweep` writes no files.

## How the adaptive scan works

Wallets hand out addresses in order, so once several unused addresses follow the last used one, there is nothing further to find. `scan` (and `sweep`) use this to keep lookups low:

| Level | Rule |
|---|---|
| Receive addresses | Always check the first 10 (Bitcoin, Zcash, Firo) or 5 (EVM, per path scheme). Then continue while a used address is within `--gap` (default 3) of the end. |
| Change addresses | Only if the account's receive addresses were used |
| Accounts 1, 2, … | Only if the previous account was used (up to 20) |

**Lookup cost:**
- **Unused seed:** 74 lookups (measured), versus about 200 with `derive`'s fixed counts.
- **Used wallet:** followed as deep as its activity goes. In the example above, Bitcoin to address #27, Ethereum to #100, and the second accounts.

**Trade-off:** the default gap of 3 is tighter than the wallet standard of 20. Wallets that generated many unused addresses before receiving funds (merchant or donation setups) can be missed. For a thorough check use `--gap 20`, which also raises the minimum to 20 addresses per chain.

## Sweeping funds (optional)

`walletcheck sweep` moves what the scan found into a **new wallet you control**. It is the only command that moves funds. It needs the `[sweep]` extra (see [Install](#install)).

```bash
walletcheck sweep                  # hidden prompt for your secrets, like scan
walletcheck sweep --dry-run        # build and sign, show everything, never broadcast
```

What happens:

1. **Find:** the same adaptive scan finds funded addresses. `sweep` accepts the same scan options: `--gap`, `--chains`, `--proxy`, …
2. **Keys:** private keys are re-derived **in memory** for those addresses only. Each key must reproduce its exact address, checked with a second, independent library, or the sweep refuses to sign.
3. **Per chain:** for each chain with funds you're asked whether to sweep it, the **destination address** (typed in) and the **broadcast endpoint** (Enter = public default, or your own node).
4. **Confirm:** the signed plan is shown (inputs, amount, fee, destination, transaction id). **One `y` broadcasts it.** If the fee looks unusual, you must type `yes` instead. That means:
   - over 10% of the amount;
   - over 100 sat/vB;
   - or an EVM tip far above what a second, independent endpoint reports.
5. **Track:** EVM sweeps wait up to `--wait` seconds (default 600) for confirmations. Bitcoin shows a mempool.space link.

| | Bitcoin | EVM chains |
|---|---|---|
| **What is moved** | All confirmed outputs, all address types (legacy incl. uncompressed, nested and native segwit, taproot), in one transaction | Configured tokens first, then the native coin minus all fees |
| **Fee target** | mempool.space "hour fee" rate (about 1 hour), replace-by-fee enabled | EIP-1559: max fee = 2 × base fee + tip, the tip taken from what recent blocks actually paid (normally minutes); Base/Optimism L1 data fee included |
| **Safety checks** | Every input is verified against its full previous transaction (hash, script, amount), so an endpoint can't misreport amounts; duplicate outputs are ignored | The endpoint's chain id must match; a failed call aborts instead of counting as zero; the tip is capped at 3× what recent blocks paid; the endpoint never receives a transaction signed by your key before you confirm |
| **Skipped and reported** | Unconfirmed outputs; outputs worth less than their own fee; results below the dust limit; anything beyond one standard-size transaction (sweep again afterwards) | Tokens without native coin for gas (shows how much is needed); tokens that can't be transferred (frozen or paused); addresses with pending transactions |

**Destination checks:**
- Checksum, mainnet and well-formedness are verified.
- None of the swept addresses is allowed as the destination.
- An EVM destination that is a smart-contract wallet (e.g. a Safe) on another chain but not on the target chain is refused, because funds sent there could be lost. If that can't be checked on every chain, you must type `yes`.

**Good to know:**
- **Leftover:** a small amount of native coin may remain on EVM addresses as unused fee headroom.
- **Privacy:** all Bitcoin inputs go into one transaction, which links the swept wallets on-chain. To keep wallets separate, sweep one secret per run.
- **Thoroughness:** use `--gap 20` to sweep everything a wallet could have used.
- **Dry run:** `--dry-run` prints fully signed transactions. Anyone who gets them can broadcast them.
- **Failed lookups** are listed by address. Sweep again later to cover them.

**Not swept:**
- Zcash and Firo: reported; use their own wallets.
- Monero.
- Watch-only inputs: xpub, public keys, addresses.
- Multisig.

> ⚠️ **Transactions can't be reversed.** Double-check the destination, and sweep a small amount first. Mature wallets also offer sweeping: for large amounts, consider Electrum or Sparrow (Bitcoin) or importing the key into Rabby or MetaMask (EVM).

## Security model

**What it guarantees**

- Secrets are only used in memory: to derive public addresses and, in `sweep`, to sign.
- Secrets are never printed, written to disk or sent anywhere. This is enforced by `tests/test_privacy.py` and `tests/test_sweep_cli.py`.
- Only public addresses are sent online:
  - Bitcoin: [mempool.space](https://mempool.space) / [blockstream.info](https://blockstream.info);
  - Zcash: [Blockchair](https://blockchair.com);
  - Firo: the Firo Insight explorer;
  - EVM: public RPC endpoints.
- `scan`, `derive` and `check` only read public data.
- `sweep` broadcasts signed transactions, never keys, and only after you confirm.

**What it can't protect against**

- **Privacy:** explorers see your IP and all addresses you query, so they can link them to each other. Use `--proxy` with Tor or a VPN if that matters.
- **Your computer:** malware or a compromised Python environment can read anything you paste. Read the code: `walletcheck.py` (scanning) and `walletcheck_sweep.py` (sweeping).
- **Past exposure:** keys that sat in plain-text notes should be treated as exposed. **If you find funds, move them to a fresh wallet.**

Details and how to report vulnerabilities: [SECURITY.md](SECURITY.md).

## Limitations

**Derivation and coverage**
- Only standard derivation paths are checked; exotic custom paths are not.
- Token coverage is limited to the tokens listed above. For complete token and NFT coverage, paste the *addresses* (never keys) into a portfolio viewer such as DeBank.
- **BIP39 seeds in languages with accented words (e.g. Spanish, French) may be rejected as unrecognised.** English seeds and 4-letter English abbreviations work.
- Not supported: Electrum 2FA seeds (need TrustedCoin's co-signer), multisig wallets, and other coins such as Litecoin.

**Zcash and Firo**
- Plain Zcash or Firo addresses can't be entered as input; they are derived from seeds and keys only.
- **Shielded Zcash (`z…`, `u…`) and Firo Spark addresses are not checked.** Seeing their balances needs a viewing key and a light-client scan; a public explorer would receive the viewing key, which breaks the privacy promise.
- Zcash and Firo lookups show the confirmed balance only.

**Monero**
- **Derived but not checked.** Seeing a Monero balance requires scanning the blockchain with the private view key, and no website can do that without learning the key.
- Only the first (primary) address is derived (account 0, index 0). Subaddresses and other accounts are not covered.
- **Polyseed (16-word) and MyMonero-style 13-word seeds are not supported.** Only standard 25-word seeds (and 24 words without the checksum word) are.

**Network**
- Public RPC endpoints can be rate-limited or change. Failed lookups are reported; re-run to retry.

## Verification

```bash
walletcheck selftest                 # published BIP and Electrum test vectors
pip install -e ".[test]" && pytest   # full offline test suite (from a clone of this repository)
```

The test suite covers:

- published test vectors (BIP44/49/84/86, BIP173, Electrum, Monero);
- cross-validation of every input format against independent libraries ([embit](https://github.com/diybitcoinhardware/embit) for Bitcoin, [eth-account](https://github.com/ethereum/eth-account) for Ethereum);
- the gap-limit logic and failed-lookup handling;
- secret-leak tests: no seed, passphrase or private key appears in output or files;
- sweep:
  - every Bitcoin signature re-checked with a second library ([bitcoin-utils](https://github.com/karask/python-bitcoin-utils) sighash + coincurve);
  - endpoints that lie about amounts;
  - EVM sweeps of native coins and OpenZeppelin ERC20 tokens, end to end on an in-process Ethereum chain;
  - the interactive flow.

It runs on Linux and macOS for Python 3.10-3.13 on every push.

## Contributing

Issues and pull requests are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).

**Never post real seeds or keys in issues.** Report security problems privately as described in [SECURITY.md](SECURITY.md).

## License

Public domain via [The Unlicense](LICENSE): free for any personal or commercial use, no conditions.

**No warranty.** `scan`, `derive` and `check` only read public blockchain data. `sweep` moves funds, irreversibly, after your confirmation. You use this tool at your own risk. Not financial advice.

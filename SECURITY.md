# Security policy

walletcheck handles the most sensitive data a crypto user owns. Security reports are welcome and taken seriously.

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Report privately via GitHub:
**Security** tab → **Report a vulnerability** on this repository.

Include what you found, how to reproduce it, and the impact. **Never include real secrets**; use test vectors or throwaway keys.

## In scope

- Any path by which a seed, private key, passphrase or xprv could be printed, written to disk, logged, or sent over the network.
- Incorrect address derivation that could make a funded wallet look empty.
- Results shown as "empty" when a lookup actually failed.
- `sweep`: anything that could send funds somewhere other than the destination you typed, sign for the
  wrong key, pay an unintended fee, or broadcast without your confirmation.
- Dependency or supply-chain concerns.

## Design guarantees

- Secrets are only used in memory to derive public addresses.
- Only public addresses are sent to block explorers / RPC nodes.
- Terminal output never echoes secrets; invalid seeds are diagnosed by word *position* only.
- These guarantees are enforced by `tests/test_privacy.py`.
- `scan`, `derive` and `check` never move funds.
- `sweep` (optional, `walletcheck_sweep.py`) signs locally and sends only signed transactions:
  - keys are re-derived in memory only for funded addresses, and each must reproduce its scanned address
    (checked with a second, independent library) or the sweep refuses to sign;
  - Bitcoin inputs are verified against their full previous transactions, so an endpoint cannot misreport amounts;
  - EVM endpoints must report the expected chain id; failed calls abort instead of counting as zero;
  - no endpoint receives a transaction signed by the user's key before the user confirms (L1 data fees
    on Base/Optimism are priced with a size-identical copy signed by a throwaway key);
  - nothing is broadcast without a `y` after the signed plan is shown (a typed `yes` for unusual fees);
    `--dry-run` never broadcasts;
  - enforced by `tests/test_sweep_*.py`, including leak checks for seeds and derived private keys.

## What it cannot protect against

- Malware on your computer, a compromised Python installation or compromised dependencies.
- Explorers learning which addresses you query (and your IP). Use `--proxy` with Tor or a VPN.
- Keys that were already exposed by being stored in plain text: move any funds you find to a fresh wallet.
- A wrong destination you typed and confirmed: transactions cannot be reversed. Test with a small amount first.
- A malicious broadcast endpoint can see and delay your signed transactions (it cannot change them).

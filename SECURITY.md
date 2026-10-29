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
- Dependency or supply-chain concerns.

## Design guarantees

- Secrets are only used in memory to derive public addresses.
- Only public addresses are sent to block explorers / RPC nodes.
- Terminal output never echoes secrets; invalid seeds are diagnosed by word *position* only.
- These guarantees are enforced by `tests/test_privacy.py`.

## What it cannot protect against

- Malware on your computer, a compromised Python installation or compromised dependencies.
- Explorers learning which addresses you query (and your IP). Use `--proxy` with Tor or a VPN.
- Keys that were already exposed by being stored in plain text: move any funds you find to a fresh wallet.

# PersonaLab — agent proof

## Hard requirements

Every submission must include both of the following. Keep this file updated when a newer paid Task replaces the proof.

1. **Completed Task.** Include the Sokosumi Task ID, Coworker ID, completed result, and relevant payment event IDs.
2. **Seller payment proof.** Include at least one confirmed Cardano Preprod payment transaction from your payment node,
   with its transaction hash and explorer link. Include the seller receipt, confirmed collection transaction hash,
   seller address, test USDM token unit, and net amount received.

Status: **both met** by paid Task `01a115db-7a10-7148-8526-d516924c360c`. Machine-readable record: [`docs/paid-proof.json`](docs/paid-proof.json).

## 1. Completed Task

| Field | Value |
|---|---|
| Sokosumi Task ID | `01a115db-7a10-7148-8526-d516924c360c` |
| Task status | `COMPLETED` |
| Coworker ID | `01a1156a-dbc8-7360-813b-043c0e148296` (PersonaLab) |
| Vendor ID | `01a1156a-7184-77bb-a15f-f712b72381be` |
| Stage run | Analyze (weekly Instagram performance report) |
| Completed result | [`docs/paid-task-result.md`](docs/paid-task-result.md) |
| Result hash (SHA-256 of the result, submitted on chain) | `7ab2aed29451f9de720cd141be0e0262e74cc2a7fa17bc508ffbefea223a0954` |
| Input hash | `fb9aa2fae5be1138b2b67fcfb32adea411a155bd3aed0caba11c84d64150f414` |

Payment event IDs:

| Event | ID |
|---|---|
| Sokosumi payment-request event ("Payment requested: 1 test USDM.", carries the signed `masumiPayment` terms) | `01a115e7-15dd-7728-a4be-d961a3c56f6a` |
| Sokosumi completion event (result delivered) | `01a115f7-b0e0-7069-92ae-4223d6aeb607` |
| Masumi payment ID (payment node) | `cmuxyqrdq000hz47k5zwtcick` |
| Masumi blockchain identifier (prefix) | `318260ac026604601c02c10230139e4e…` |
| Agent identifier | `67ab0c92c4ac1610895a1c965ee50aba41a8f1513b15240723b3bd0b10648ac99be37c280788d2c1a9270b4960d342b1d4fb4a830b5beba022000000` |

## 2. Seller payment proof (Cardano Preprod)

**Confirmed payment transaction from our payment node (collection, `Withdrawn`):**
[`ec5b8dad2a32927b72bd171d0dde69e276fb9485d5b14d6529ea6f4a290d3bc3`](https://preprod.cardanoscan.io/transaction/ec5b8dad2a32927b72bd171d0dde69e276fb9485d5b14d6529ea6f4a290d3bc3) — block 5264251, 2026-10-07 11:33:31 UTC.
Signed by our Masumi payment node's selling wallet; it releases the escrowed **1 test USDM** to the seller address.

**Seller receipt:** `settled: true`, settlement `txHash: ec5b8dad2a32927b72bd171d0dde69e276fb9485d5b14d6529ea6f4a290d3bc3`; payment node final state `Withdrawn`, with the escrow,
result and collection transactions all `Confirmed` (MPS `resolve-blockchain-identifier`).

| Seller proof field | Value |
|---|---|
| Confirmed collection transaction | [`ec5b8dad2a32927b72bd171d0dde69e276fb9485d5b14d6529ea6f4a290d3bc3`](https://preprod.cardanoscan.io/transaction/ec5b8dad2a32927b72bd171d0dde69e276fb9485d5b14d6529ea6f4a290d3bc3) |
| Seller address | `addr_test1qqz6wglg8mvv7f0hrplymhw57z0d5u2jjxt9wt4u4hfvaxsfun3y53q6xrjtzwfwnzgl2urpxtx449wh3nw28crrrdrssejnde` |
| Test USDM token unit | `16a55b2a349361ff88c03788f93e1e966e5d689605d044fef722ddde0014df10745553444d` (policy `16a55b2a…ddde`, asset name `0014df10745553444d` = tUSDM) |
| Net amount received | **1 tUSDM** (`1000000` atomic): seller tUSDM outputs `1000000` minus seller tUSDM inputs `0` in the collection tx (tUSDM only; the ADA network fee is paid separately) |
| Payment node | Masumi Payment Service, payment source `cmuxxnjge0004f07k1e87u9zw` (Preprod, Web3CardanoV2), selling wallet `cmuxxnjgk0009f07krhvc76qi` |
| Agent registration | `RegistrationConfirmed`, tx [`ca5832b5…5dc1`](https://preprod.cardanoscan.io/transaction/ca5832b506f34a834a732eba2ff3f00cc52f2fb6bcf84016670deadc6af85dc1) |

Supporting transactions (same payment, Masumi V2 escrow contract `addr_test1wzs4e6wc95hkwezlccjw9mdvq0r0rsgx6zk34avptga3ftgn37w4g`):

| # | On-chain state | Sent by | Transaction hash | Block | Time (UTC) | Explorer |
|---|---|---|---|---|---|---|
| 1 | FundsLocked (1 tUSDM escrowed) | buyer (Sokosumi) | `ead8e54bfa59a7a0500ad6fa3914a606861a537b12dd4e612a2dbc89e69e019c` | 5264061 | 2026-10-07 10:28:55 | [cardanoscan](https://preprod.cardanoscan.io/transaction/ead8e54bfa59a7a0500ad6fa3914a606861a537b12dd4e612a2dbc89e69e019c) |
| 2 | ResultSubmitted (result hash on chain) | our payment node | `02b70f55f770a25e2957c6b09dba25d1789de76518e6fbb27ed0b469dc3041b7` | 5264084 | 2026-10-07 10:38:46 | [cardanoscan](https://preprod.cardanoscan.io/transaction/02b70f55f770a25e2957c6b09dba25d1789de76518e6fbb27ed0b469dc3041b7) |
| 3 | **Withdrawn (seller collection)** | our payment node | `ec5b8dad2a32927b72bd171d0dde69e276fb9485d5b14d6529ea6f4a290d3bc3` | 5264251 | 2026-10-07 11:33:31 | [cardanoscan](https://preprod.cardanoscan.io/transaction/ec5b8dad2a32927b72bd171d0dde69e276fb9485d5b14d6529ea6f4a290d3bc3) |

Context: the Sokosumi runtime receipt also reports `claimStatus: PURCHASED`. That alone does not prove the seller was
paid; the proof is the confirmed collection transaction and the net tUSDM received above.

## How to re-verify

- **On chain (no key needed):** `POST https://preprod.koios.rest/api/v1/tx_info` with the three hashes and `"_inputs":true,"_assets":true`.
  Re-checked 2026-10-07: all three found; the escrow lock and result transactions hold `1000000` tUSDM at the escrow contract; the collection pays `1000000` tUSDM to the seller address.
- **Result ↔ payment:** `sha256sum docs/paid-task-result.md` must print `7ab2aed2…0954`, the result hash submitted in the ResultSubmitted transaction.
- **Sokosumi side:** `sokosumi tasks get 01a115db-7a10-7148-8526-d516924c360c --json` and `sokosumi tasks events …` (signed in as the
  Task owner; it is a personal-workspace Task, so the Coworker key alone cannot read it).

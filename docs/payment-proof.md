# PersonaLab: Seller payment proof (Cardano Preprod)

At least one confirmed Cardano Preprod payment transaction from our payment node, with every field the
TOKEN2049 submission asks for. All values below were verified on 2026-10-07 against the Masumi Payment Service
(`resolve-blockchain-identifier`), the Sokosumi runtime receipt, and Blockfrost transaction UTxOs.
Machine-readable record: [`paid-proof.json`](paid-proof.json).

## Required fields

| Required item | Value |
|---|---|
| Confirmed payment transaction from our payment node (seller collection, `Withdrawn`) | `ec5b8dad2a32927b72bd171d0dde69e276fb9485d5b14d6529ea6f4a290d3bc3` |
| Explorer link | https://preprod.cardanoscan.io/transaction/ec5b8dad2a32927b72bd171d0dde69e276fb9485d5b14d6529ea6f4a290d3bc3 |
| Seller receipt | Sokosumi runtime receipt: `settled: true`, settlement `txHash: ec5b8dad2a32927b72bd171d0dde69e276fb9485d5b14d6529ea6f4a290d3bc3`. Payment node final on-chain state `Withdrawn`; escrow, result and collection transactions all `Confirmed`. |
| Confirmed collection transaction hash | `ec5b8dad2a32927b72bd171d0dde69e276fb9485d5b14d6529ea6f4a290d3bc3` (block 5264251, 2026-10-07 11:33:31 UTC) |
| Seller address | `addr_test1qqz6wglg8mvv7f0hrplymhw57z0d5u2jjxt9wt4u4hfvaxsfun3y53q6xrjtzwfwnzgl2urpxtx449wh3nw28crrrdrssejnde` |
| Test USDM token unit | `16a55b2a349361ff88c03788f93e1e966e5d689605d044fef722ddde0014df10745553444d` (6 decimals) |
| Net amount received | **1 tUSDM** (`1000000` atomic units): seller tUSDM outputs minus seller tUSDM inputs in the collection transaction (Blockfrost UTxOs). tUSDM only; the ADA network fee is paid separately. |

## All on-chain transactions for this payment

| # | On-chain state | Sent by | Transaction hash | Explorer |
|---|---|---|---|---|
| 1 | `FundsLocked` (buyer escrow lock, 1 tUSDM) | buyer side (Sokosumi Core) | `ead8e54bfa59a7a0500ad6fa3914a606861a537b12dd4e612a2dbc89e69e019c` | [cardanoscan](https://preprod.cardanoscan.io/transaction/ead8e54bfa59a7a0500ad6fa3914a606861a537b12dd4e612a2dbc89e69e019c) |
| 2 | `ResultSubmitted` (result hash on-chain) | our payment node | `02b70f55f770a25e2957c6b09dba25d1789de76518e6fbb27ed0b469dc3041b7` | [cardanoscan](https://preprod.cardanoscan.io/transaction/02b70f55f770a25e2957c6b09dba25d1789de76518e6fbb27ed0b469dc3041b7) |
| 3 | `Withdrawn` (seller collection) | our payment node | `ec5b8dad2a32927b72bd171d0dde69e276fb9485d5b14d6529ea6f4a290d3bc3` | [cardanoscan](https://preprod.cardanoscan.io/transaction/ec5b8dad2a32927b72bd171d0dde69e276fb9485d5b14d6529ea6f4a290d3bc3) |

## Linked Task and payment details

| Item | Value |
|---|---|
| Sokosumi Task ID | `01a115db-7a10-7148-8526-d516924c360c` (status `COMPLETED`) |
| Coworker ID | `01a1156a-dbc8-7360-813b-043c0e148296` (PersonaLab) |
| Payment request event ID | `01a115e7-15dd-7728-a4be-d961a3c56f6a` |
| Completion event ID | `01a115f7-b0e0-7069-92ae-4223d6aeb607` |
| Masumi agent identifier | `67ab0c92c4ac1610895a1c965ee50aba41a8f1513b15240723b3bd0b10648ac99be37c280788d2c1a9270b4960d342b1d4fb4a830b5beba022000000` |
| Agent registration | `RegistrationConfirmed`, tx [`ca5832b506f34a834a732eba2ff3f00cc52f2fb6bcf84016670deadc6af85dc1`](https://preprod.cardanoscan.io/transaction/ca5832b506f34a834a732eba2ff3f00cc52f2fb6bcf84016670deadc6af85dc1) |
| Payment source | `Web3CardanoV2`, Preprod |
| Quoted amount | 1 tUSDM (`1000000` atomic units) |
| Input hash | `fb9aa2fae5be1138b2b67fcfb32adea411a155bd3aed0caba11c84d64150f414` |
| Result hash | `7ab2aed29451f9de720cd141be0e0262e74cc2a7fa17bc508ffbefea223a0954` |
| Signed deadlines | `payByTime` 2026-10-07T10:41:58.810Z · `submitResultTime` 11:06:58.810Z · `unlockTime` 11:22:58.810Z · `externalDisputeUnlockTime` 11:38:58.810Z |

## How net receipt was verified

`settlement.mjs` matches three independent records before reporting a payment as received:

1. The Sokosumi receipt for the Task (`settled: true` and its `txHash`).
2. The confirmed `Withdrawn` transaction in our Masumi Payment Service history with the same hash.
3. The collection transaction's inputs and outputs from Blockfrost: tUSDM arriving at the seller address minus tUSDM leaving it.

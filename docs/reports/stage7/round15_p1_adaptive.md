# Round 15 P1: adaptive retrieval depth, on vs off

30 questions of the Round 9 retrieval eval set (answer-key phrases).

| metric | off | on |
|---|---|---|
| hit@5 | 22/30 | 20/30 |
| answer rate (ok or fallback) | 29/30 | 30/30 |
| second pass ran | 0 | 6/30 (deeper, scope) |
| latency p50 / p95 (ms) | 3549 / 3804 | 2405 / 3720 |

| id | hit off | hit on | status off | status on | second pass | ms off | ms on |
|---|---|---|---|---|---|---|---|
| R01 | y | y | ok | ok | - | 3736 | 3305 |
| R02 | y | y | ok | ok | deeper | 3418 | 3720 |
| R03 | y | y | ok | ok | - | 3411 | 1342 |
| R04 | - | - | ok | ok | - | 3271 | 2986 |
| R05 | y | - | ok | ok | - | 2355 | 3802 |
| R06 | - | - | ok | ok | - | 3802 | 2949 |
| R07 | y | y | ok | ok | - | 3549 | 2405 |
| R08 | y | y | ok | ok | - | 3339 | 2424 |
| R09 | - | - | fallback | ok | deeper | 4286 | 2149 |
| R10 | y | y | ok | ok | - | 3802 | 1964 |
| R11 | y | - | ok | ok | - | 3803 | 3314 |
| R12 | y | y | ok | ok | - | 3690 | 2408 |
| R13 | y | y | ok | ok | - | 3804 | 2264 |
| R14 | y | y | ok | ok | - | 3803 | 2239 |
| R15 | - | y | not_found | ok | scope | 3430 | 3482 |
| R16 | y | y | ok | ok | - | 3803 | 3147 |
| R17 | y | y | ok | ok | - | 3802 | 2351 |
| R18 | - | - | ok | ok | - | 3803 | 3294 |
| R19 | y | y | ok | ok | - | 3804 | 2505 |
| R20 | - | - | ok | ok | - | 2577 | 2346 |
| R21 | - | - | ok | ok | - | 3605 | 3215 |
| R22 | y | y | ok | ok | - | 2086 | 2135 |
| R23 | y | y | ok | ok | - | 2757 | 2379 |
| R24 | y | y | ok | ok | - | 3597 | 1827 |
| R25 | y | y | ok | ok | - | 2135 | 1958 |
| R26 | y | y | ok | ok | - | 3651 | 2420 |
| R27 | y | - | ok | ok | - | 2024 | 2186 |
| R28 | y | y | ok | ok | - | 3439 | 3353 |
| R29 | - | - | ok | ok | deeper | 2325 | 1639 |
| R30 | y | y | ok | ok | deeper | 1989 | 1963 |

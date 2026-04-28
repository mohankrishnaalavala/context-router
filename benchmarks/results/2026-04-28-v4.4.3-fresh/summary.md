# context-router holdout benchmark

## Aggregate

| Scope | Tasks | Avg precision | Avg recall | Avg F1 | Avg tokens | Rank-1 hits |
|---|---:|---:|---:|---:|---:|---:|
| **overall** | 9 | 0.537 | 1.000 | 0.685 | 132.2 | 9/9 |
| gson | 3 | 0.611 | 1.000 | 0.722 | 137.7 | 3/3 |
| requests | 3 | 0.500 | 1.000 | 0.667 | 143.7 | 3/3 |
| zod | 3 | 0.500 | 1.000 | 0.667 | 115.3 | 3/3 |

## Per task

| Task | Mode | Items | Tokens | Precision | Recall | F1 | Rank-1 | GT |
|---|---|---:|---:|---:|---:|---:|---:|---|
| gson-t1 | debug | 2 | 117 | 0.500 | 1.000 | 0.667 | 1 | `gson/src/main/java/com/google/gson/stream/JsonReader.java` |
| gson-t2 | debug | 3 | 227 | 0.333 | 1.000 | 0.500 | 1 | `gson/src/main/java/com/google/gson/internal/bind/MapTypeAdapterFactory.java` |
| gson-t3 | debug | 1 | 69 | 1.000 | 1.000 | 1.000 | 1 | `gson/src/main/java/com/google/gson/internal/$Gson$Types.java` |
| requests-t1 | debug | 2 | 149 | 0.500 | 1.000 | 0.667 | 1 | `src/requests/utils.py` |
| requests-t2 | debug | 2 | 146 | 0.500 | 1.000 | 0.667 | 1 | `src/requests/utils.py` |
| requests-t3 | debug | 2 | 136 | 0.500 | 1.000 | 0.667 | 1 | `src/requests/exceptions.py` |
| zod-t1 | debug | 2 | 118 | 0.500 | 1.000 | 0.667 | 1 | `packages/zod/src/v4/core/schemas.ts` |
| zod-t2 | debug | 2 | 106 | 0.500 | 1.000 | 0.667 | 1 | `packages/zod/src/v4/classic/schemas.ts` |
| zod-t3 | debug | 2 | 122 | 0.500 | 1.000 | 0.667 | 1 | `packages/zod/src/v4/core/util.ts` |

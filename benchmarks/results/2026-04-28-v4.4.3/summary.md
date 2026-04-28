# context-router holdout benchmark

## Aggregate

| Scope | Tasks | Avg precision | Avg recall | Avg F1 | Avg tokens | Rank-1 hits |
|---|---:|---:|---:|---:|---:|---:|
| **overall** | 9 | 0.500 | 0.889 | 0.630 | 185.6 | 8/9 |
| gin | 3 | 0.500 | 1.000 | 0.667 | 114.3 | 3/3 |
| actix | 3 | 0.667 | 1.000 | 0.778 | 91.7 | 3/3 |
| django | 3 | 0.333 | 0.667 | 0.444 | 350.7 | 2/3 |

## Per task

| Task | Mode | Items | Tokens | Precision | Recall | F1 | Rank-1 | GT |
|---|---|---:|---:|---:|---:|---:|---:|---|
| gin-t1 | debug | 2 | 120 | 0.500 | 1.000 | 0.667 | 1 | `tree.go` |
| gin-t2 | debug | 2 | 118 | 0.500 | 1.000 | 0.667 | 1 | `context.go` |
| gin-t3 | debug | 2 | 105 | 0.500 | 1.000 | 0.667 | 1 | `binding/form_mapping.go` |
| actix-t1 | debug | 2 | 109 | 0.500 | 1.000 | 0.667 | 1 | `actix-files/src/named.rs` |
| actix-t2 | debug | 1 | 48 | 1.000 | 1.000 | 1.000 | 1 | `actix-web/src/route.rs` |
| actix-t3 | debug | 2 | 118 | 0.500 | 1.000 | 0.667 | 1 | `awc/src/client/h1proto.rs` |
| django-t1 | debug | 2 | 120 | 0.500 | 1.000 | 0.667 | 1 | `django/db/models/sql/query.py` |
| django-t2 | debug | 2 | 161 | 0.500 | 1.000 | 0.667 | 1 | `django/core/handlers/asgi.py` |
| django-t3 | implement | 11 | 771 | 0.000 | 0.000 | 0.000 | 0 | `django/db/models/fields/__init__.py` |

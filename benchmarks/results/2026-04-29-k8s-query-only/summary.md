# context-router holdout benchmark

**Anchor:** `query-only`

## Aggregate

| Scope | Tasks | Avg precision | Avg recall | Avg F1 | Avg tokens | Rank-1 hits |
|---|---:|---:|---:|---:|---:|---:|
| **overall** | 3 | 0.000 | 0.000 | 0.000 | 2388.0 | 0/3 |
| kubernetes | 3 | 0.000 | 0.000 | 0.000 | 2388.0 | 0/3 |

## Per task

| Task | Mode | Items | Tokens | Precision | Recall | F1 | Rank-1 | GT |
|---|---|---:|---:|---:|---:|---:|---:|---|
| k8s-t1 | review | 49 | 2756 | 0.000 | 0.000 | 0.000 | 0 | `pkg/kubelet/status/status_manager.go` |
| k8s-t2 | review | 20 | 1074 | 0.000 | 0.000 | 0.000 | 0 | `staging/src/k8s.io/client-go/tools/clientcmd/loader.go` |
| k8s-t3 | review | 59 | 3334 | 0.000 | 0.000 | 0.000 | 0 | `pkg/proxy/winkernel/proxier.go` |

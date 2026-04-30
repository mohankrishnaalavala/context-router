# context-router holdout benchmark

**Anchor:** `fix-sha`

## Aggregate

| Scope | Tasks | Avg precision | Avg recall | Avg F1 | Avg tokens | Rank-1 hits |
|---|---:|---:|---:|---:|---:|---:|
| **overall** | 3 | 0.467 | 1.000 | 0.556 | 210.0 | 3/3 |
| kubernetes | 3 | 0.467 | 1.000 | 0.556 | 210.0 | 3/3 |

## Per task

| Task | Mode | Items | Tokens | Precision | Recall | F1 | Rank-1 | GT |
|---|---|---:|---:|---:|---:|---:|---:|---|
| k8s-t1 | review | 5 | 279 | 0.200 | 1.000 | 0.333 | 1 | `pkg/kubelet/status/status_manager.go` |
| k8s-t2 | review | 5 | 286 | 0.200 | 1.000 | 0.333 | 1 | `staging/src/k8s.io/client-go/tools/clientcmd/loader.go` |
| k8s-t3 | review | 1 | 65 | 1.000 | 1.000 | 1.000 | 1 | `pkg/proxy/winkernel/proxier.go` |

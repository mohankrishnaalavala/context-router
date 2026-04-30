# context-router holdout benchmark

**Anchor:** `parent-sha-with-diff`

## Aggregate

| Scope | Tasks | Avg precision | Avg recall | Avg F1 | Avg tokens | Rank-1 hits |
|---|---:|---:|---:|---:|---:|---:|
| **overall** | 3 | 0.556 | 1.000 | 0.667 | 135.3 | 2/3 |
| kubernetes | 3 | 0.556 | 1.000 | 0.667 | 135.3 | 2/3 |

## Per task

| Task | Mode | Items | Tokens | Precision | Recall | F1 | Rank-1 | GT |
|---|---|---:|---:|---:|---:|---:|---:|---|
| k8s-t1 | review | 3 | 169 | 0.333 | 1.000 | 0.500 | 1 | `pkg/kubelet/status/status_manager.go` |
| k8s-t2 | review | 3 | 172 | 0.333 | 1.000 | 0.500 | 0 | `staging/src/k8s.io/client-go/tools/clientcmd/loader.go` |
| k8s-t3 | review | 1 | 65 | 1.000 | 1.000 | 1.000 | 1 | `pkg/proxy/winkernel/proxier.go` |

# 01_ARCHITECTURE_CONTRACT.md — Architecture Contract

## 1. Component model

```text
+-------------------+      +-------------------+      +--------------------+
| Declarative Config| ---> | Planner           | ---> | Runtime            |
| hosts/az/cluster  |      | placement/ports   |      | Docker containers  |
+-------------------+      +-------------------+      +--------------------+
          |                         |                           |
          v                         v                           v
+-------------------+      +-------------------+      +--------------------+
| Workload Model    | ---> | Experiment Engine | ---> | Valkey Cluster     |
+-------------------+      +-------------------+      +--------------------+
                                    |
                                    v
+-------------------+      +-------------------+      +--------------------+
| Fault Engine      | ---> | Metrics Collector | ---> | Artifact Writer    |
+-------------------+      +-------------------+      +--------------------+
                                    |
                                    v
                           +-------------------+
                           | Analysis/Reports  |
                           +-------------------+
```

## 2. Required package boundaries

Use clear modules. The exact internal design may vary, but these responsibilities must remain separate.

```text
valkey_scale_lab.config       parse, validate, normalize config
valkey_scale_lab.planner      capacity model, AZ placement, ports, directories
valkey_scale_lab.runtime      Docker/container lifecycle and cleanup
valkey_scale_lab.valkey       cluster creation, cluster command helpers
valkey_scale_lab.workload     QPS, pipeline, read/write, hotspot generation
valkey_scale_lab.metrics      INFO/CLUSTER/docker/process/log collectors
valkey_scale_lab.fault        sandboxed process/network/AZ fault injection
valkey_scale_lab.analysis     quantitative analysis and regression comparison
valkey_scale_lab.report       tables/charts/static HTML from artifacts
valkey_scale_lab.orchestrator multi-host execution and artifact collection
valkey_scale_lab.artifacts    schemas, writers, validation helpers
```

## 3. Runtime isolation contract

Default runtime is Docker. Every Valkey node must have an independent network identity. Acceptable strategies:

1. one container per Valkey node;
2. one owned sandbox proxy per Valkey node or per link when `NET_ADMIN` is unavailable;
3. container-scoped network namespace controls when available.

Forbidden strategies:

1. host-level `pfctl`, `iptables`, `nft`, host route edits, host interface edits;
2. global firewall mutation;
3. killing physical interfaces;
4. changing machine-wide DNS or network services;
5. `sudo` as a default network path.

## 4. Virtual AZ model

A virtual AZ is a logical failure and placement domain. It may span multiple physical hosts. Example: with two physical hosts and three virtual AZs, each physical host may contain nodes for all three AZs, and node placement should be balanced across AZs.

For every shard, primary and replica nodes must not be placed in the same AZ. With one primary and one replica in a three-AZ region, each shard uses exactly two of the three AZs.

```text
+----------------------+       +----------------------+
| host-mac-1           |       | host-mac-2           |
|  +------+ +------+   |       |  +------+ +------+   |
|  | az-a | | az-b |   |       |  | az-a | | az-c |   |
|  +------+ +------+   |       |  +------+ +------+   |
+----------------------+       +----------------------+
           \                         /
            \                       /
             v                     v
          +----------------------------+
          | shard-0007                 |
          | primary in az-a            |
          | replica in az-c            |
          +----------------------------+
```

## 5. Multi-host orchestration contract

The machine running the project is the controller. It may connect to other configured hosts using SSH or an explicit remote agent, but it must not require root by default. Remote actions must be idempotent and labeled by run ID.

Required remote operations:

- prepare runtime directory;
- check Docker availability;
- start node containers;
- collect logs and artifacts;
- inject sandboxed faults in owned containers/proxies only;
- stop and cleanup owned resources;
- report leftovers instead of hiding them.


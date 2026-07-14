# 06_FAULT_ISOLATION.md — Fault Injection Isolation Design

## 1. Isolation goal

Fault injection must affect only Valkey nodes owned by the current run. It must not affect the physical host, other applications, other containers, or the user's normal network use.

## 2. Default safe architecture

```text
+---------------- physical host ----------------+
|                                                |
|  +----------- Docker / container runtime ----+ |
|  |                                           | |
|  | +------------+      +------------+        | |
|  | | Valkey N1  |<---->| Valkey N2  |        | |
|  | | netns/id   |      | netns/id   |        | |
|  | +------------+      +------------+        | |
|  |       ^                   ^               | |
|  |       | fault scoped here |               | |
|  +-------------------------------------------+ |
|                                                |
|  host network, firewall, routes untouched       |
+------------------------------------------------+
```

## 3. Allowed fault implementations

1. Container stop/kill/restart of owned Valkey containers by container ID/label.
2. Container-scoped network delay/loss/partition/flap inside the owned network namespace.
3. Docker-network-scoped disconnect/connect for owned containers.
4. Owned sandbox proxy/toxiproxy-style process where all affected traffic is explicitly routed through the proxy by project config.
5. Multi-container virtual AZ down by targeting owned containers/proxies tagged with an AZ label.

## 4. Forbidden fault implementations

1. Host PF rules.
2. Host iptables/nftables rules.
3. Host route table mutation.
4. Host interface down/up.
5. Global DNS/network service changes.
6. `sudo` as default behavior.
7. Process-killing by broad patterns.

## 5. Required evidence per fault

```json
{
  "fault_id": "fault-...",
  "fault_type": "az_partition",
  "scope": "container_namespace",
  "targets": ["shard-0001-primary"],
  "start_time": "...",
  "end_time": "...",
  "apply_status": "PASS",
  "clear_status": "PASS",
  "safety_checks": {
    "host_network_mutated": false,
    "global_firewall_mutated": false,
    "sandbox_only": true
  }
}
```

## 6. Split-brain measurement

Split-brain analysis must distinguish evidence from inference:

- evidence: conflicting primary claims observed in `CLUSTER NODES` samples;
- evidence: write success/failure by partition side;
- inference: likely minority/majority role based on topology;
- missing: no sample during the conflict window.

If no direct evidence exists, the artifact must mark split-brain duration as `MISSING`.


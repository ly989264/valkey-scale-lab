# P23_FAULT_NETWORK_DELAY_LOSS_FLAP — Network Delay, Loss, and Flap Faults

## Stage objective

Implement sandboxed network impairment faults and quantify workload impact.

## Required fault rows

```text
network_delay
network_loss
network_flap
```

## Worker implementation requirements

Implement:

- safe implementation path detection: container namespace `tc/netem` or sandbox proxy;
- network delay with recorded delay/jitter/direction/target/duration;
- network loss with recorded percent/correlation/direction/target/duration;
- network flap with recorded cadence/iterations/target;
- fault apply/clear lifecycle;
- workload windows and metrics;
- cleanup verification.

Host-level firewall/routing/interface changes are forbidden.

## Required artifacts

```text
network_fault_report.json
fault_results.jsonl
workload_impact_report.json
network_fault_command_log.jsonl
events.jsonl
metrics_timeseries.jsonl
quant_summary.json
```

## Required assertions

- at least one safe implementation path is exercised;
- no host-level network mutation appears in command log/source path;
- delay/loss/flap rows have parameters and observed effects;
- workload impact exists;
- cleanup clears fault state.

## Review focus

Review safety carefully. Reject any use of host `iptables`, `nft`, `pfctl`, global route mutation, or `sudo` network manipulation.

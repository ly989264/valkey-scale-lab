# P20_FAILOVER_LATENCY_CURVE_30_50_100 — Failover Latency Curve: 30/50/100 Nodes

## Stage objective

Produce real primary-stop failover latency curve samples for 30, 50, and 100 nodes.

## Required rungs

```text
30 nodes: minimum 3 samples
50 nodes: minimum 3 samples
100 nodes: minimum 3 samples
```

## Worker implementation requirements

Implement or strengthen:

- resource preflight for each rung;
- real cluster creation for each rung;
- target primary selection;
- primary stop through project fault API or owned runtime control;
- promotion detection from live cluster views;
- slot coverage recovery detection;
- workload QPS/latency/error windows;
- raw sample collection;
- curve derivation artifact;
- cleanup after each sample/rung.

## Required artifacts

```text
failover_latency_samples.jsonl
failover_latency_curve.json
fault_matrix_report.json
workload_impact_report.json
events.jsonl
metrics_timeseries.jsonl
quant_summary.json
```

## Required assertions

- all three rungs exist;
- each rung has at least three real samples;
- each sample includes promotion and recovery timestamps or FAIL;
- curve values derive from raw samples;
- workload impact reference exists for each sample;
- cleanup passes for every sample.

## Review focus

Reject fake sample reuse. Reject downshifting 100 to a smaller node count. Reject curve artifacts without raw sample backing.

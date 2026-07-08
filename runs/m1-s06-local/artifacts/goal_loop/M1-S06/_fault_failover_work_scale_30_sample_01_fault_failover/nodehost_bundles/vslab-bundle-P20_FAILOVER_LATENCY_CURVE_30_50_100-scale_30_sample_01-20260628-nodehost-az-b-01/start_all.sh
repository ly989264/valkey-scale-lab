#!/bin/sh
set -eu
valkey-server "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_30_sample_01-20260628/shard-0003-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_30_sample_01-20260628/shard-0007-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_30_sample_01-20260628/shard-0011-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_30_sample_01-20260628/shard-0000-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_30_sample_01-20260628/shard-0004-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_30_sample_01-20260628/shard-0008-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_30_sample_01-20260628/shard-0012-replica-00/valkey.conf"

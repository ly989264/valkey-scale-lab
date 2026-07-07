#!/bin/sh
set -eu
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_10_timeline_sample_01-20260628/shard-0000-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_10_timeline_sample_01-20260628/shard-0004-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_10_timeline_sample_01-20260628/shard-0003-replica-00/valkey.conf"

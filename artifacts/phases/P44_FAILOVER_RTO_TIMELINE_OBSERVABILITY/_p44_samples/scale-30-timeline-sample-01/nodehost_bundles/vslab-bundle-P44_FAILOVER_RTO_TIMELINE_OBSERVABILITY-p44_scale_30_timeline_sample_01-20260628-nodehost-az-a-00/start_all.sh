#!/bin/sh
set -eu
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_30_timeline_sample_01-20260628/shard-0000-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_30_timeline_sample_01-20260628/shard-0004-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_30_timeline_sample_01-20260628/shard-0008-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_30_timeline_sample_01-20260628/shard-0012-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_30_timeline_sample_01-20260628/shard-0001-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_30_timeline_sample_01-20260628/shard-0005-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_30_timeline_sample_01-20260628/shard-0009-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_30_timeline_sample_01-20260628/shard-0013-replica-00/valkey.conf"

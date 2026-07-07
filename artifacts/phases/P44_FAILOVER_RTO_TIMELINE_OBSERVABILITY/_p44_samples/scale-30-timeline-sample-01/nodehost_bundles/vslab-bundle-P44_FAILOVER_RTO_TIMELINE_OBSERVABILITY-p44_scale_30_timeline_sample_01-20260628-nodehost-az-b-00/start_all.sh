#!/bin/sh
set -eu
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_30_timeline_sample_01-20260628/shard-0001-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_30_timeline_sample_01-20260628/shard-0005-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_30_timeline_sample_01-20260628/shard-0009-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_30_timeline_sample_01-20260628/shard-0013-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_30_timeline_sample_01-20260628/shard-0002-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_30_timeline_sample_01-20260628/shard-0006-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_30_timeline_sample_01-20260628/shard-0010-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_30_timeline_sample_01-20260628/shard-0014-replica-00/valkey.conf"

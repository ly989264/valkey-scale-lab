#!/bin/sh
set -eu
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_50_timeline_sample_01-20260628/shard-0002-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_50_timeline_sample_01-20260628/shard-0006-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_50_timeline_sample_01-20260628/shard-0010-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_50_timeline_sample_01-20260628/shard-0014-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_50_timeline_sample_01-20260628/shard-0018-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_50_timeline_sample_01-20260628/shard-0022-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_50_timeline_sample_01-20260628/shard-0001-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_50_timeline_sample_01-20260628/shard-0005-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_50_timeline_sample_01-20260628/shard-0009-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_50_timeline_sample_01-20260628/shard-0013-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_50_timeline_sample_01-20260628/shard-0017-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_50_timeline_sample_01-20260628/shard-0021-replica-00/valkey.conf"

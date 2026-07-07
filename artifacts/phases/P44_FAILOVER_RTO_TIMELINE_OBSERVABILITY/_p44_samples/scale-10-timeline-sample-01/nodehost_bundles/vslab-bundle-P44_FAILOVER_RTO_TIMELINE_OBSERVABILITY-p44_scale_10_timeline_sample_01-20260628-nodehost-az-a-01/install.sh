#!/bin/sh
set -eu
BUNDLE_DIR="/tmp/vslab-bundle-P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_10_timeline_sample_01-20260628-nodehost-az-a-01"
mkdir -p "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_10_timeline_sample_01-20260628/shard-0002-primary"
cp "$BUNDLE_DIR/node_configs/shard-0002-primary.conf" "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_10_timeline_sample_01-20260628/shard-0002-primary/valkey.conf"
mkdir -p "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_10_timeline_sample_01-20260628/shard-0001-replica-00"
cp "$BUNDLE_DIR/node_configs/shard-0001-replica-00.conf" "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_10_timeline_sample_01-20260628/shard-0001-replica-00/valkey.conf"

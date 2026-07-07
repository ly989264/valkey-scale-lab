#!/bin/sh
set -eu
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_10_timeline_sample_01-20260628/shard-0002-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_10_timeline_sample_01-20260628/shard-0002-primary/valkey.pid" ]; then
  echo "shard-0002-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_10_timeline_sample_01-20260628/shard-0002-primary/valkey.pid")
printf "%s\t%s\n" "shard-0002-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_10_timeline_sample_01-20260628/shard-0001-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_10_timeline_sample_01-20260628/shard-0001-replica-00/valkey.pid" ]; then
  echo "shard-0001-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_10_timeline_sample_01-20260628/shard-0001-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0001-replica-00" "$pid_value"

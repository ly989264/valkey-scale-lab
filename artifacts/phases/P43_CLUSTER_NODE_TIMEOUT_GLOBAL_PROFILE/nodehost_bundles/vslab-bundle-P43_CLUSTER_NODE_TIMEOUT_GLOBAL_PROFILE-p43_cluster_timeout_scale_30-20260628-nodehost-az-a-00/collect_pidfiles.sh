#!/bin/sh
set -eu
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0000-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0000-primary/valkey.pid" ]; then
  echo "shard-0000-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0000-primary/valkey.pid")
printf "%s\t%s\n" "shard-0000-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0004-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0004-primary/valkey.pid" ]; then
  echo "shard-0004-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0004-primary/valkey.pid")
printf "%s\t%s\n" "shard-0004-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0008-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0008-primary/valkey.pid" ]; then
  echo "shard-0008-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0008-primary/valkey.pid")
printf "%s\t%s\n" "shard-0008-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0012-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0012-primary/valkey.pid" ]; then
  echo "shard-0012-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0012-primary/valkey.pid")
printf "%s\t%s\n" "shard-0012-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0001-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0001-replica-00/valkey.pid" ]; then
  echo "shard-0001-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0001-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0001-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0005-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0005-replica-00/valkey.pid" ]; then
  echo "shard-0005-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0005-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0005-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0009-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0009-replica-00/valkey.pid" ]; then
  echo "shard-0009-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0009-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0009-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0013-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0013-replica-00/valkey.pid" ]; then
  echo "shard-0013-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0013-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0013-replica-00" "$pid_value"

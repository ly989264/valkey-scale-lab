#!/bin/sh
set -eu
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_10-20260628/shard-0000-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_10-20260628/shard-0000-primary/valkey.pid" ]; then
  echo "shard-0000-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_10-20260628/shard-0000-primary/valkey.pid")
printf "%s\t%s\n" "shard-0000-primary" "$pid_value"

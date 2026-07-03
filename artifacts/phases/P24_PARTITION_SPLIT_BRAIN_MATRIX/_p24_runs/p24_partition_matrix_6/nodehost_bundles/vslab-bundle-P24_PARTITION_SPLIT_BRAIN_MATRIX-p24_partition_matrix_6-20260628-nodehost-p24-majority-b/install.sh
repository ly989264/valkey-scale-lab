#!/bin/sh
set -eu
BUNDLE_DIR="/tmp/vslab-bundle-P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_6-20260628-nodehost-p24-majority-b"
mkdir -p "/tmp/valkey-scale-lab/P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_6-20260628/shard-0002-primary"
cp "$BUNDLE_DIR/node_configs/shard-0002-primary.conf" "/tmp/valkey-scale-lab/P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_6-20260628/shard-0002-primary/valkey.conf"
mkdir -p "/tmp/valkey-scale-lab/P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_6-20260628/shard-0001-replica-00"
cp "$BUNDLE_DIR/node_configs/shard-0001-replica-00.conf" "/tmp/valkey-scale-lab/P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_6-20260628/shard-0001-replica-00/valkey.conf"

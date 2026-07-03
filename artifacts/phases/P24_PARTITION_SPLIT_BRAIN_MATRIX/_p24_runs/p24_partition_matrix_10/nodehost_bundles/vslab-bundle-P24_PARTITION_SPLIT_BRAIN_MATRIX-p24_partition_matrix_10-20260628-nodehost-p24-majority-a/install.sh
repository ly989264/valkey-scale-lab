#!/bin/sh
set -eu
BUNDLE_DIR="/tmp/vslab-bundle-P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_10-20260628-nodehost-p24-majority-a"
mkdir -p "/tmp/valkey-scale-lab/P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_10-20260628/shard-0001-primary"
cp "$BUNDLE_DIR/node_configs/shard-0001-primary.conf" "/tmp/valkey-scale-lab/P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_10-20260628/shard-0001-primary/valkey.conf"
mkdir -p "/tmp/valkey-scale-lab/P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_10-20260628/shard-0003-primary"
cp "$BUNDLE_DIR/node_configs/shard-0003-primary.conf" "/tmp/valkey-scale-lab/P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_10-20260628/shard-0003-primary/valkey.conf"
mkdir -p "/tmp/valkey-scale-lab/P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_10-20260628/shard-0000-replica-00"
cp "$BUNDLE_DIR/node_configs/shard-0000-replica-00.conf" "/tmp/valkey-scale-lab/P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_10-20260628/shard-0000-replica-00/valkey.conf"
mkdir -p "/tmp/valkey-scale-lab/P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_10-20260628/shard-0002-replica-00"
cp "$BUNDLE_DIR/node_configs/shard-0002-replica-00.conf" "/tmp/valkey-scale-lab/P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_10-20260628/shard-0002-replica-00/valkey.conf"
mkdir -p "/tmp/valkey-scale-lab/P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_10-20260628/shard-0004-replica-00"
cp "$BUNDLE_DIR/node_configs/shard-0004-replica-00.conf" "/tmp/valkey-scale-lab/P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_10-20260628/shard-0004-replica-00/valkey.conf"

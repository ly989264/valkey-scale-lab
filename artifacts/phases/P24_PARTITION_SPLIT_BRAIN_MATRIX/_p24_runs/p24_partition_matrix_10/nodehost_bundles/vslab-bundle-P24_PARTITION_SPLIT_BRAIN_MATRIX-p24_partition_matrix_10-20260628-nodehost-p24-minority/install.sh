#!/bin/sh
set -eu
BUNDLE_DIR="/tmp/vslab-bundle-P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_10-20260628-nodehost-p24-minority"
mkdir -p "/tmp/valkey-scale-lab/P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_10-20260628/shard-0000-primary"
cp "$BUNDLE_DIR/node_configs/shard-0000-primary.conf" "/tmp/valkey-scale-lab/P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_10-20260628/shard-0000-primary/valkey.conf"

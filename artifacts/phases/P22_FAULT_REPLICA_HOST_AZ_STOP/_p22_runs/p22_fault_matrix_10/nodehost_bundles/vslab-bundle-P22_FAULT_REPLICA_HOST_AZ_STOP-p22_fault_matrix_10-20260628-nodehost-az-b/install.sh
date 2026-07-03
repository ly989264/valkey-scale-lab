#!/bin/sh
set -eu
BUNDLE_DIR="/tmp/vslab-bundle-P22_FAULT_REPLICA_HOST_AZ_STOP-p22_fault_matrix_10-20260628-nodehost-az-b"
mkdir -p "/tmp/valkey-scale-lab/P22_FAULT_REPLICA_HOST_AZ_STOP-p22_fault_matrix_10-20260628/shard-0001-primary"
cp "$BUNDLE_DIR/node_configs/shard-0001-primary.conf" "/tmp/valkey-scale-lab/P22_FAULT_REPLICA_HOST_AZ_STOP-p22_fault_matrix_10-20260628/shard-0001-primary/valkey.conf"
mkdir -p "/tmp/valkey-scale-lab/P22_FAULT_REPLICA_HOST_AZ_STOP-p22_fault_matrix_10-20260628/shard-0003-primary"
cp "$BUNDLE_DIR/node_configs/shard-0003-primary.conf" "/tmp/valkey-scale-lab/P22_FAULT_REPLICA_HOST_AZ_STOP-p22_fault_matrix_10-20260628/shard-0003-primary/valkey.conf"
mkdir -p "/tmp/valkey-scale-lab/P22_FAULT_REPLICA_HOST_AZ_STOP-p22_fault_matrix_10-20260628/shard-0000-replica-00"
cp "$BUNDLE_DIR/node_configs/shard-0000-replica-00.conf" "/tmp/valkey-scale-lab/P22_FAULT_REPLICA_HOST_AZ_STOP-p22_fault_matrix_10-20260628/shard-0000-replica-00/valkey.conf"
mkdir -p "/tmp/valkey-scale-lab/P22_FAULT_REPLICA_HOST_AZ_STOP-p22_fault_matrix_10-20260628/shard-0002-replica-00"
cp "$BUNDLE_DIR/node_configs/shard-0002-replica-00.conf" "/tmp/valkey-scale-lab/P22_FAULT_REPLICA_HOST_AZ_STOP-p22_fault_matrix_10-20260628/shard-0002-replica-00/valkey.conf"
mkdir -p "/tmp/valkey-scale-lab/P22_FAULT_REPLICA_HOST_AZ_STOP-p22_fault_matrix_10-20260628/shard-0004-replica-00"
cp "$BUNDLE_DIR/node_configs/shard-0004-replica-00.conf" "/tmp/valkey-scale-lab/P22_FAULT_REPLICA_HOST_AZ_STOP-p22_fault_matrix_10-20260628/shard-0004-replica-00/valkey.conf"

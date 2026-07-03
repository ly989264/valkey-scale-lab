#!/bin/sh
set -eu
BUNDLE_DIR="/tmp/vslab-bundle-P23_FAULT_NETWORK_DELAY_LOSS_FLAP-p23_fault_matrix_10-20260628-nodehost-az-a"
mkdir -p "/tmp/valkey-scale-lab/P23_FAULT_NETWORK_DELAY_LOSS_FLAP-p23_fault_matrix_10-20260628/shard-0000-primary"
cp "$BUNDLE_DIR/node_configs/shard-0000-primary.conf" "/tmp/valkey-scale-lab/P23_FAULT_NETWORK_DELAY_LOSS_FLAP-p23_fault_matrix_10-20260628/shard-0000-primary/valkey.conf"
mkdir -p "/tmp/valkey-scale-lab/P23_FAULT_NETWORK_DELAY_LOSS_FLAP-p23_fault_matrix_10-20260628/shard-0002-primary"
cp "$BUNDLE_DIR/node_configs/shard-0002-primary.conf" "/tmp/valkey-scale-lab/P23_FAULT_NETWORK_DELAY_LOSS_FLAP-p23_fault_matrix_10-20260628/shard-0002-primary/valkey.conf"
mkdir -p "/tmp/valkey-scale-lab/P23_FAULT_NETWORK_DELAY_LOSS_FLAP-p23_fault_matrix_10-20260628/shard-0004-primary"
cp "$BUNDLE_DIR/node_configs/shard-0004-primary.conf" "/tmp/valkey-scale-lab/P23_FAULT_NETWORK_DELAY_LOSS_FLAP-p23_fault_matrix_10-20260628/shard-0004-primary/valkey.conf"
mkdir -p "/tmp/valkey-scale-lab/P23_FAULT_NETWORK_DELAY_LOSS_FLAP-p23_fault_matrix_10-20260628/shard-0001-replica-00"
cp "$BUNDLE_DIR/node_configs/shard-0001-replica-00.conf" "/tmp/valkey-scale-lab/P23_FAULT_NETWORK_DELAY_LOSS_FLAP-p23_fault_matrix_10-20260628/shard-0001-replica-00/valkey.conf"
mkdir -p "/tmp/valkey-scale-lab/P23_FAULT_NETWORK_DELAY_LOSS_FLAP-p23_fault_matrix_10-20260628/shard-0003-replica-00"
cp "$BUNDLE_DIR/node_configs/shard-0003-replica-00.conf" "/tmp/valkey-scale-lab/P23_FAULT_NETWORK_DELAY_LOSS_FLAP-p23_fault_matrix_10-20260628/shard-0003-replica-00/valkey.conf"

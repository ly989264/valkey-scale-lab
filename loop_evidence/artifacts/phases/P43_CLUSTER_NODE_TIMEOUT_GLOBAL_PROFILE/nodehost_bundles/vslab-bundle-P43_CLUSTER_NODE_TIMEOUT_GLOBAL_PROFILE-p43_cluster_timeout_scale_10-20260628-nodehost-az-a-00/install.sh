#!/bin/sh
set -eu
BUNDLE_DIR="/tmp/vslab-bundle-P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_10-20260628-nodehost-az-a-00"
mkdir -p "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_10-20260628/shard-0000-primary"
cp "$BUNDLE_DIR/node_configs/shard-0000-primary.conf" "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_10-20260628/shard-0000-primary/valkey.conf"
mkdir -p "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_10-20260628/shard-0004-primary"
cp "$BUNDLE_DIR/node_configs/shard-0004-primary.conf" "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_10-20260628/shard-0004-primary/valkey.conf"
mkdir -p "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_10-20260628/shard-0003-replica-00"
cp "$BUNDLE_DIR/node_configs/shard-0003-replica-00.conf" "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_10-20260628/shard-0003-replica-00/valkey.conf"

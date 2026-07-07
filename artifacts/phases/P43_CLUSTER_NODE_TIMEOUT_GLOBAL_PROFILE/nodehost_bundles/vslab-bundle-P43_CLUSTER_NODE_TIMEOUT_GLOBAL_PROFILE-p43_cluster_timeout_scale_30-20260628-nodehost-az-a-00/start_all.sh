#!/bin/sh
set -eu
valkey-server "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0000-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0004-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0008-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0012-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0001-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0005-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0009-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_30-20260628/shard-0013-replica-00/valkey.conf"

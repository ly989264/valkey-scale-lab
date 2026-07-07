#!/bin/sh
set -eu
valkey-server "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_10-20260628/shard-0003-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-p43_cluster_timeout_scale_10-20260628/shard-0002-replica-00/valkey.conf"

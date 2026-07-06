#!/bin/sh
set -eu
BUNDLE_DIR="/tmp/vslab-bundle-P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_10-20260628-nodehost-az-a-00"
mkdir -p "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_10-20260628/shard-0000-primary"
cp "$BUNDLE_DIR/node_configs/shard-0000-primary.conf" "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_10-20260628/shard-0000-primary/valkey.conf"
mkdir -p "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_10-20260628/shard-0004-primary"
cp "$BUNDLE_DIR/node_configs/shard-0004-primary.conf" "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_10-20260628/shard-0004-primary/valkey.conf"
mkdir -p "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_10-20260628/shard-0003-replica-00"
cp "$BUNDLE_DIR/node_configs/shard-0003-replica-00.conf" "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_10-20260628/shard-0003-replica-00/valkey.conf"

#!/bin/sh
set -eu
valkey-server "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_30-20260628/shard-0001-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_30-20260628/shard-0005-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_30-20260628/shard-0009-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_30-20260628/shard-0013-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_30-20260628/shard-0002-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_30-20260628/shard-0006-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_30-20260628/shard-0010-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_30-20260628/shard-0014-replica-00/valkey.conf"

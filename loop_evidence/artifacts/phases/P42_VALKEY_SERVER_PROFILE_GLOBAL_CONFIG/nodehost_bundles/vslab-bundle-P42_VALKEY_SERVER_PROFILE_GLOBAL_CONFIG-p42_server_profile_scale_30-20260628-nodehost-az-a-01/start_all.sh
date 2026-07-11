#!/bin/sh
set -eu
valkey-server "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_30-20260628/shard-0002-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_30-20260628/shard-0006-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_30-20260628/shard-0010-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_30-20260628/shard-0014-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_30-20260628/shard-0003-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_30-20260628/shard-0007-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_30-20260628/shard-0011-replica-00/valkey.conf"

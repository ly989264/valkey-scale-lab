#!/bin/sh
set -eu
valkey-server "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_10-20260628/shard-0003-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_10-20260628/shard-0002-replica-00/valkey.conf"

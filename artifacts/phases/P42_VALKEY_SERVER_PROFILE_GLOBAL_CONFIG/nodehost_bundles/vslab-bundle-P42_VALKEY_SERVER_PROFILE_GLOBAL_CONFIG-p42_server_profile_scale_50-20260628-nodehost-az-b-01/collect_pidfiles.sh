#!/bin/sh
set -eu
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0003-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0003-primary/valkey.pid" ]; then
  echo "shard-0003-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0003-primary/valkey.pid")
printf "%s\t%s\n" "shard-0003-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0007-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0007-primary/valkey.pid" ]; then
  echo "shard-0007-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0007-primary/valkey.pid")
printf "%s\t%s\n" "shard-0007-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0011-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0011-primary/valkey.pid" ]; then
  echo "shard-0011-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0011-primary/valkey.pid")
printf "%s\t%s\n" "shard-0011-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0015-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0015-primary/valkey.pid" ]; then
  echo "shard-0015-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0015-primary/valkey.pid")
printf "%s\t%s\n" "shard-0015-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0019-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0019-primary/valkey.pid" ]; then
  echo "shard-0019-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0019-primary/valkey.pid")
printf "%s\t%s\n" "shard-0019-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0023-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0023-primary/valkey.pid" ]; then
  echo "shard-0023-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0023-primary/valkey.pid")
printf "%s\t%s\n" "shard-0023-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0002-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0002-replica-00/valkey.pid" ]; then
  echo "shard-0002-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0002-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0002-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0006-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0006-replica-00/valkey.pid" ]; then
  echo "shard-0006-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0006-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0006-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0010-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0010-replica-00/valkey.pid" ]; then
  echo "shard-0010-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0010-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0010-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0014-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0014-replica-00/valkey.pid" ]; then
  echo "shard-0014-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0014-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0014-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0018-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0018-replica-00/valkey.pid" ]; then
  echo "shard-0018-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0018-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0018-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0022-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0022-replica-00/valkey.pid" ]; then
  echo "shard-0022-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_50-20260628/shard-0022-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0022-replica-00" "$pid_value"

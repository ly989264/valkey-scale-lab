#!/bin/sh
set -eu
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0000-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0000-primary/valkey.pid" ]; then
  echo "shard-0000-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0000-primary/valkey.pid")
printf "%s\t%s\n" "shard-0000-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0008-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0008-primary/valkey.pid" ]; then
  echo "shard-0008-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0008-primary/valkey.pid")
printf "%s\t%s\n" "shard-0008-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0016-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0016-primary/valkey.pid" ]; then
  echo "shard-0016-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0016-primary/valkey.pid")
printf "%s\t%s\n" "shard-0016-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0024-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0024-primary/valkey.pid" ]; then
  echo "shard-0024-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0024-primary/valkey.pid")
printf "%s\t%s\n" "shard-0024-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0032-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0032-primary/valkey.pid" ]; then
  echo "shard-0032-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0032-primary/valkey.pid")
printf "%s\t%s\n" "shard-0032-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0040-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0040-primary/valkey.pid" ]; then
  echo "shard-0040-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0040-primary/valkey.pid")
printf "%s\t%s\n" "shard-0040-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0048-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0048-primary/valkey.pid" ]; then
  echo "shard-0048-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0048-primary/valkey.pid")
printf "%s\t%s\n" "shard-0048-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0056-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0056-primary/valkey.pid" ]; then
  echo "shard-0056-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0056-primary/valkey.pid")
printf "%s\t%s\n" "shard-0056-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0064-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0064-primary/valkey.pid" ]; then
  echo "shard-0064-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0064-primary/valkey.pid")
printf "%s\t%s\n" "shard-0064-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0072-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0072-primary/valkey.pid" ]; then
  echo "shard-0072-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0072-primary/valkey.pid")
printf "%s\t%s\n" "shard-0072-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0080-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0080-primary/valkey.pid" ]; then
  echo "shard-0080-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0080-primary/valkey.pid")
printf "%s\t%s\n" "shard-0080-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0088-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0088-primary/valkey.pid" ]; then
  echo "shard-0088-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0088-primary/valkey.pid")
printf "%s\t%s\n" "shard-0088-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0096-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0096-primary/valkey.pid" ]; then
  echo "shard-0096-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0096-primary/valkey.pid")
printf "%s\t%s\n" "shard-0096-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0005-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0005-replica-00/valkey.pid" ]; then
  echo "shard-0005-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0005-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0005-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0013-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0013-replica-00/valkey.pid" ]; then
  echo "shard-0013-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0013-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0013-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0021-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0021-replica-00/valkey.pid" ]; then
  echo "shard-0021-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0021-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0021-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0029-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0029-replica-00/valkey.pid" ]; then
  echo "shard-0029-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0029-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0029-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0037-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0037-replica-00/valkey.pid" ]; then
  echo "shard-0037-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0037-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0037-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0045-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0045-replica-00/valkey.pid" ]; then
  echo "shard-0045-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0045-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0045-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0053-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0053-replica-00/valkey.pid" ]; then
  echo "shard-0053-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0053-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0053-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0061-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0061-replica-00/valkey.pid" ]; then
  echo "shard-0061-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0061-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0061-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0069-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0069-replica-00/valkey.pid" ]; then
  echo "shard-0069-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0069-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0069-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0077-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0077-replica-00/valkey.pid" ]; then
  echo "shard-0077-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0077-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0077-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0085-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0085-replica-00/valkey.pid" ]; then
  echo "shard-0085-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0085-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0085-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0093-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0093-replica-00/valkey.pid" ]; then
  echo "shard-0093-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-p42_server_profile_scale_200-20260628/shard-0093-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0093-replica-00" "$pid_value"

#!/bin/sh
set -eu
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0000-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0000-primary/valkey.pid" ]; then
  echo "shard-0000-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0000-primary/valkey.pid")
printf "%s\t%s\n" "shard-0000-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0002-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0002-primary/valkey.pid" ]; then
  echo "shard-0002-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0002-primary/valkey.pid")
printf "%s\t%s\n" "shard-0002-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0004-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0004-primary/valkey.pid" ]; then
  echo "shard-0004-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0004-primary/valkey.pid")
printf "%s\t%s\n" "shard-0004-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0006-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0006-primary/valkey.pid" ]; then
  echo "shard-0006-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0006-primary/valkey.pid")
printf "%s\t%s\n" "shard-0006-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0008-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0008-primary/valkey.pid" ]; then
  echo "shard-0008-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0008-primary/valkey.pid")
printf "%s\t%s\n" "shard-0008-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0010-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0010-primary/valkey.pid" ]; then
  echo "shard-0010-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0010-primary/valkey.pid")
printf "%s\t%s\n" "shard-0010-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0012-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0012-primary/valkey.pid" ]; then
  echo "shard-0012-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0012-primary/valkey.pid")
printf "%s\t%s\n" "shard-0012-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0014-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0014-primary/valkey.pid" ]; then
  echo "shard-0014-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0014-primary/valkey.pid")
printf "%s\t%s\n" "shard-0014-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0016-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0016-primary/valkey.pid" ]; then
  echo "shard-0016-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0016-primary/valkey.pid")
printf "%s\t%s\n" "shard-0016-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0018-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0018-primary/valkey.pid" ]; then
  echo "shard-0018-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0018-primary/valkey.pid")
printf "%s\t%s\n" "shard-0018-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0020-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0020-primary/valkey.pid" ]; then
  echo "shard-0020-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0020-primary/valkey.pid")
printf "%s\t%s\n" "shard-0020-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0022-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0022-primary/valkey.pid" ]; then
  echo "shard-0022-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0022-primary/valkey.pid")
printf "%s\t%s\n" "shard-0022-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0024-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0024-primary/valkey.pid" ]; then
  echo "shard-0024-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0024-primary/valkey.pid")
printf "%s\t%s\n" "shard-0024-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0026-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0026-primary/valkey.pid" ]; then
  echo "shard-0026-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0026-primary/valkey.pid")
printf "%s\t%s\n" "shard-0026-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0028-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0028-primary/valkey.pid" ]; then
  echo "shard-0028-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0028-primary/valkey.pid")
printf "%s\t%s\n" "shard-0028-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0030-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0030-primary/valkey.pid" ]; then
  echo "shard-0030-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0030-primary/valkey.pid")
printf "%s\t%s\n" "shard-0030-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0032-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0032-primary/valkey.pid" ]; then
  echo "shard-0032-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0032-primary/valkey.pid")
printf "%s\t%s\n" "shard-0032-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0034-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0034-primary/valkey.pid" ]; then
  echo "shard-0034-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0034-primary/valkey.pid")
printf "%s\t%s\n" "shard-0034-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0036-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0036-primary/valkey.pid" ]; then
  echo "shard-0036-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0036-primary/valkey.pid")
printf "%s\t%s\n" "shard-0036-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0038-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0038-primary/valkey.pid" ]; then
  echo "shard-0038-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0038-primary/valkey.pid")
printf "%s\t%s\n" "shard-0038-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0040-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0040-primary/valkey.pid" ]; then
  echo "shard-0040-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0040-primary/valkey.pid")
printf "%s\t%s\n" "shard-0040-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0042-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0042-primary/valkey.pid" ]; then
  echo "shard-0042-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0042-primary/valkey.pid")
printf "%s\t%s\n" "shard-0042-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0044-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0044-primary/valkey.pid" ]; then
  echo "shard-0044-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0044-primary/valkey.pid")
printf "%s\t%s\n" "shard-0044-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0046-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0046-primary/valkey.pid" ]; then
  echo "shard-0046-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0046-primary/valkey.pid")
printf "%s\t%s\n" "shard-0046-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0048-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0048-primary/valkey.pid" ]; then
  echo "shard-0048-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0048-primary/valkey.pid")
printf "%s\t%s\n" "shard-0048-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0050-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0050-primary/valkey.pid" ]; then
  echo "shard-0050-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0050-primary/valkey.pid")
printf "%s\t%s\n" "shard-0050-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0052-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0052-primary/valkey.pid" ]; then
  echo "shard-0052-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0052-primary/valkey.pid")
printf "%s\t%s\n" "shard-0052-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0054-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0054-primary/valkey.pid" ]; then
  echo "shard-0054-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0054-primary/valkey.pid")
printf "%s\t%s\n" "shard-0054-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0056-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0056-primary/valkey.pid" ]; then
  echo "shard-0056-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0056-primary/valkey.pid")
printf "%s\t%s\n" "shard-0056-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0058-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0058-primary/valkey.pid" ]; then
  echo "shard-0058-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0058-primary/valkey.pid")
printf "%s\t%s\n" "shard-0058-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0060-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0060-primary/valkey.pid" ]; then
  echo "shard-0060-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0060-primary/valkey.pid")
printf "%s\t%s\n" "shard-0060-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0062-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0062-primary/valkey.pid" ]; then
  echo "shard-0062-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0062-primary/valkey.pid")
printf "%s\t%s\n" "shard-0062-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0064-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0064-primary/valkey.pid" ]; then
  echo "shard-0064-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0064-primary/valkey.pid")
printf "%s\t%s\n" "shard-0064-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0066-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0066-primary/valkey.pid" ]; then
  echo "shard-0066-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0066-primary/valkey.pid")
printf "%s\t%s\n" "shard-0066-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0068-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0068-primary/valkey.pid" ]; then
  echo "shard-0068-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0068-primary/valkey.pid")
printf "%s\t%s\n" "shard-0068-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0070-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0070-primary/valkey.pid" ]; then
  echo "shard-0070-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0070-primary/valkey.pid")
printf "%s\t%s\n" "shard-0070-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0072-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0072-primary/valkey.pid" ]; then
  echo "shard-0072-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0072-primary/valkey.pid")
printf "%s\t%s\n" "shard-0072-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0074-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0074-primary/valkey.pid" ]; then
  echo "shard-0074-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0074-primary/valkey.pid")
printf "%s\t%s\n" "shard-0074-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0076-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0076-primary/valkey.pid" ]; then
  echo "shard-0076-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0076-primary/valkey.pid")
printf "%s\t%s\n" "shard-0076-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0078-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0078-primary/valkey.pid" ]; then
  echo "shard-0078-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0078-primary/valkey.pid")
printf "%s\t%s\n" "shard-0078-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0080-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0080-primary/valkey.pid" ]; then
  echo "shard-0080-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0080-primary/valkey.pid")
printf "%s\t%s\n" "shard-0080-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0082-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0082-primary/valkey.pid" ]; then
  echo "shard-0082-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0082-primary/valkey.pid")
printf "%s\t%s\n" "shard-0082-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0084-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0084-primary/valkey.pid" ]; then
  echo "shard-0084-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0084-primary/valkey.pid")
printf "%s\t%s\n" "shard-0084-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0086-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0086-primary/valkey.pid" ]; then
  echo "shard-0086-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0086-primary/valkey.pid")
printf "%s\t%s\n" "shard-0086-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0088-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0088-primary/valkey.pid" ]; then
  echo "shard-0088-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0088-primary/valkey.pid")
printf "%s\t%s\n" "shard-0088-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0090-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0090-primary/valkey.pid" ]; then
  echo "shard-0090-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0090-primary/valkey.pid")
printf "%s\t%s\n" "shard-0090-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0092-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0092-primary/valkey.pid" ]; then
  echo "shard-0092-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0092-primary/valkey.pid")
printf "%s\t%s\n" "shard-0092-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0094-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0094-primary/valkey.pid" ]; then
  echo "shard-0094-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0094-primary/valkey.pid")
printf "%s\t%s\n" "shard-0094-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0096-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0096-primary/valkey.pid" ]; then
  echo "shard-0096-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0096-primary/valkey.pid")
printf "%s\t%s\n" "shard-0096-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0098-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0098-primary/valkey.pid" ]; then
  echo "shard-0098-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0098-primary/valkey.pid")
printf "%s\t%s\n" "shard-0098-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0001-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0001-replica-00/valkey.pid" ]; then
  echo "shard-0001-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0001-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0001-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0003-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0003-replica-00/valkey.pid" ]; then
  echo "shard-0003-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0003-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0003-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0005-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0005-replica-00/valkey.pid" ]; then
  echo "shard-0005-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0005-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0005-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0007-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0007-replica-00/valkey.pid" ]; then
  echo "shard-0007-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0007-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0007-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0009-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0009-replica-00/valkey.pid" ]; then
  echo "shard-0009-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0009-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0009-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0011-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0011-replica-00/valkey.pid" ]; then
  echo "shard-0011-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0011-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0011-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0013-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0013-replica-00/valkey.pid" ]; then
  echo "shard-0013-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0013-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0013-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0015-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0015-replica-00/valkey.pid" ]; then
  echo "shard-0015-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0015-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0015-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0017-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0017-replica-00/valkey.pid" ]; then
  echo "shard-0017-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0017-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0017-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0019-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0019-replica-00/valkey.pid" ]; then
  echo "shard-0019-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0019-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0019-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0021-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0021-replica-00/valkey.pid" ]; then
  echo "shard-0021-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0021-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0021-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0023-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0023-replica-00/valkey.pid" ]; then
  echo "shard-0023-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0023-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0023-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0025-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0025-replica-00/valkey.pid" ]; then
  echo "shard-0025-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0025-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0025-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0027-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0027-replica-00/valkey.pid" ]; then
  echo "shard-0027-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0027-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0027-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0029-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0029-replica-00/valkey.pid" ]; then
  echo "shard-0029-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0029-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0029-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0031-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0031-replica-00/valkey.pid" ]; then
  echo "shard-0031-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0031-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0031-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0033-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0033-replica-00/valkey.pid" ]; then
  echo "shard-0033-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0033-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0033-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0035-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0035-replica-00/valkey.pid" ]; then
  echo "shard-0035-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0035-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0035-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0037-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0037-replica-00/valkey.pid" ]; then
  echo "shard-0037-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0037-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0037-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0039-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0039-replica-00/valkey.pid" ]; then
  echo "shard-0039-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0039-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0039-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0041-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0041-replica-00/valkey.pid" ]; then
  echo "shard-0041-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0041-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0041-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0043-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0043-replica-00/valkey.pid" ]; then
  echo "shard-0043-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0043-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0043-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0045-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0045-replica-00/valkey.pid" ]; then
  echo "shard-0045-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0045-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0045-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0047-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0047-replica-00/valkey.pid" ]; then
  echo "shard-0047-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0047-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0047-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0049-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0049-replica-00/valkey.pid" ]; then
  echo "shard-0049-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0049-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0049-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0051-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0051-replica-00/valkey.pid" ]; then
  echo "shard-0051-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0051-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0051-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0053-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0053-replica-00/valkey.pid" ]; then
  echo "shard-0053-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0053-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0053-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0055-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0055-replica-00/valkey.pid" ]; then
  echo "shard-0055-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0055-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0055-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0057-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0057-replica-00/valkey.pid" ]; then
  echo "shard-0057-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0057-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0057-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0059-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0059-replica-00/valkey.pid" ]; then
  echo "shard-0059-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0059-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0059-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0061-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0061-replica-00/valkey.pid" ]; then
  echo "shard-0061-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0061-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0061-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0063-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0063-replica-00/valkey.pid" ]; then
  echo "shard-0063-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0063-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0063-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0065-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0065-replica-00/valkey.pid" ]; then
  echo "shard-0065-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0065-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0065-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0067-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0067-replica-00/valkey.pid" ]; then
  echo "shard-0067-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0067-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0067-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0069-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0069-replica-00/valkey.pid" ]; then
  echo "shard-0069-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0069-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0069-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0071-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0071-replica-00/valkey.pid" ]; then
  echo "shard-0071-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0071-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0071-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0073-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0073-replica-00/valkey.pid" ]; then
  echo "shard-0073-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0073-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0073-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0075-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0075-replica-00/valkey.pid" ]; then
  echo "shard-0075-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0075-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0075-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0077-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0077-replica-00/valkey.pid" ]; then
  echo "shard-0077-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0077-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0077-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0079-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0079-replica-00/valkey.pid" ]; then
  echo "shard-0079-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0079-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0079-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0081-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0081-replica-00/valkey.pid" ]; then
  echo "shard-0081-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0081-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0081-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0083-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0083-replica-00/valkey.pid" ]; then
  echo "shard-0083-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0083-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0083-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0085-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0085-replica-00/valkey.pid" ]; then
  echo "shard-0085-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0085-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0085-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0087-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0087-replica-00/valkey.pid" ]; then
  echo "shard-0087-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0087-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0087-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0089-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0089-replica-00/valkey.pid" ]; then
  echo "shard-0089-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0089-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0089-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0091-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0091-replica-00/valkey.pid" ]; then
  echo "shard-0091-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0091-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0091-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0093-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0093-replica-00/valkey.pid" ]; then
  echo "shard-0093-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0093-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0093-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0095-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0095-replica-00/valkey.pid" ]; then
  echo "shard-0095-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0095-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0095-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0097-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0097-replica-00/valkey.pid" ]; then
  echo "shard-0097-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0097-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0097-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0099-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0099-replica-00/valkey.pid" ]; then
  echo "shard-0099-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P36_FULL_FLOW_E2E_50_100_200_REAL-strict_full_flow_200-20260628/shard-0099-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0099-replica-00" "$pid_value"

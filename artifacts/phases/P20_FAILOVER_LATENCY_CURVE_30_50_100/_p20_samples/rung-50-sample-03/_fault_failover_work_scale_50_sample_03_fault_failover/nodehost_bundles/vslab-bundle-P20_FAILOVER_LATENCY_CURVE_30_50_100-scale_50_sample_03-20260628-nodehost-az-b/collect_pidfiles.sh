#!/bin/sh
set -eu
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0001-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0001-primary/valkey.pid" ]; then
  echo "shard-0001-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0001-primary/valkey.pid")
printf "%s\t%s\n" "shard-0001-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0003-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0003-primary/valkey.pid" ]; then
  echo "shard-0003-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0003-primary/valkey.pid")
printf "%s\t%s\n" "shard-0003-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0005-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0005-primary/valkey.pid" ]; then
  echo "shard-0005-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0005-primary/valkey.pid")
printf "%s\t%s\n" "shard-0005-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0007-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0007-primary/valkey.pid" ]; then
  echo "shard-0007-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0007-primary/valkey.pid")
printf "%s\t%s\n" "shard-0007-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0009-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0009-primary/valkey.pid" ]; then
  echo "shard-0009-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0009-primary/valkey.pid")
printf "%s\t%s\n" "shard-0009-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0011-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0011-primary/valkey.pid" ]; then
  echo "shard-0011-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0011-primary/valkey.pid")
printf "%s\t%s\n" "shard-0011-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0013-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0013-primary/valkey.pid" ]; then
  echo "shard-0013-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0013-primary/valkey.pid")
printf "%s\t%s\n" "shard-0013-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0015-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0015-primary/valkey.pid" ]; then
  echo "shard-0015-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0015-primary/valkey.pid")
printf "%s\t%s\n" "shard-0015-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0017-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0017-primary/valkey.pid" ]; then
  echo "shard-0017-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0017-primary/valkey.pid")
printf "%s\t%s\n" "shard-0017-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0019-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0019-primary/valkey.pid" ]; then
  echo "shard-0019-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0019-primary/valkey.pid")
printf "%s\t%s\n" "shard-0019-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0021-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0021-primary/valkey.pid" ]; then
  echo "shard-0021-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0021-primary/valkey.pid")
printf "%s\t%s\n" "shard-0021-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0023-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0023-primary/valkey.pid" ]; then
  echo "shard-0023-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0023-primary/valkey.pid")
printf "%s\t%s\n" "shard-0023-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0000-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0000-replica-00/valkey.pid" ]; then
  echo "shard-0000-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0000-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0000-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0002-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0002-replica-00/valkey.pid" ]; then
  echo "shard-0002-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0002-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0002-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0004-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0004-replica-00/valkey.pid" ]; then
  echo "shard-0004-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0004-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0004-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0006-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0006-replica-00/valkey.pid" ]; then
  echo "shard-0006-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0006-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0006-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0008-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0008-replica-00/valkey.pid" ]; then
  echo "shard-0008-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0008-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0008-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0010-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0010-replica-00/valkey.pid" ]; then
  echo "shard-0010-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0010-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0010-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0012-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0012-replica-00/valkey.pid" ]; then
  echo "shard-0012-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0012-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0012-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0014-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0014-replica-00/valkey.pid" ]; then
  echo "shard-0014-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0014-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0014-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0016-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0016-replica-00/valkey.pid" ]; then
  echo "shard-0016-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0016-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0016-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0018-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0018-replica-00/valkey.pid" ]; then
  echo "shard-0018-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0018-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0018-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0020-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0020-replica-00/valkey.pid" ]; then
  echo "shard-0020-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0020-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0020-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0022-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0022-replica-00/valkey.pid" ]; then
  echo "shard-0022-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0022-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0022-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0024-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0024-replica-00/valkey.pid" ]; then
  echo "shard-0024-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P20_FAILOVER_LATENCY_CURVE_30_50_100-scale_50_sample_03-20260628/shard-0024-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0024-replica-00" "$pid_value"

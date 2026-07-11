#!/bin/sh
set -eu
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0000-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0000-primary/valkey.pid" ]; then
  echo "shard-0000-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0000-primary/valkey.pid")
printf "%s\t%s\n" "shard-0000-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0004-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0004-primary/valkey.pid" ]; then
  echo "shard-0004-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0004-primary/valkey.pid")
printf "%s\t%s\n" "shard-0004-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0008-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0008-primary/valkey.pid" ]; then
  echo "shard-0008-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0008-primary/valkey.pid")
printf "%s\t%s\n" "shard-0008-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0012-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0012-primary/valkey.pid" ]; then
  echo "shard-0012-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0012-primary/valkey.pid")
printf "%s\t%s\n" "shard-0012-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0016-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0016-primary/valkey.pid" ]; then
  echo "shard-0016-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0016-primary/valkey.pid")
printf "%s\t%s\n" "shard-0016-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0020-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0020-primary/valkey.pid" ]; then
  echo "shard-0020-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0020-primary/valkey.pid")
printf "%s\t%s\n" "shard-0020-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0024-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0024-primary/valkey.pid" ]; then
  echo "shard-0024-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0024-primary/valkey.pid")
printf "%s\t%s\n" "shard-0024-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0028-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0028-primary/valkey.pid" ]; then
  echo "shard-0028-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0028-primary/valkey.pid")
printf "%s\t%s\n" "shard-0028-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0032-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0032-primary/valkey.pid" ]; then
  echo "shard-0032-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0032-primary/valkey.pid")
printf "%s\t%s\n" "shard-0032-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0036-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0036-primary/valkey.pid" ]; then
  echo "shard-0036-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0036-primary/valkey.pid")
printf "%s\t%s\n" "shard-0036-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0040-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0040-primary/valkey.pid" ]; then
  echo "shard-0040-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0040-primary/valkey.pid")
printf "%s\t%s\n" "shard-0040-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0044-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0044-primary/valkey.pid" ]; then
  echo "shard-0044-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0044-primary/valkey.pid")
printf "%s\t%s\n" "shard-0044-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0048-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0048-primary/valkey.pid" ]; then
  echo "shard-0048-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0048-primary/valkey.pid")
printf "%s\t%s\n" "shard-0048-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0003-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0003-replica-00/valkey.pid" ]; then
  echo "shard-0003-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0003-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0003-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0007-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0007-replica-00/valkey.pid" ]; then
  echo "shard-0007-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0007-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0007-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0011-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0011-replica-00/valkey.pid" ]; then
  echo "shard-0011-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0011-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0011-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0015-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0015-replica-00/valkey.pid" ]; then
  echo "shard-0015-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0015-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0015-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0019-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0019-replica-00/valkey.pid" ]; then
  echo "shard-0019-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0019-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0019-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0023-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0023-replica-00/valkey.pid" ]; then
  echo "shard-0023-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0023-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0023-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0027-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0027-replica-00/valkey.pid" ]; then
  echo "shard-0027-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0027-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0027-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0031-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0031-replica-00/valkey.pid" ]; then
  echo "shard-0031-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0031-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0031-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0035-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0035-replica-00/valkey.pid" ]; then
  echo "shard-0035-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0035-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0035-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0039-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0039-replica-00/valkey.pid" ]; then
  echo "shard-0039-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0039-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0039-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0043-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0043-replica-00/valkey.pid" ]; then
  echo "shard-0043-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0043-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0043-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0047-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0047-replica-00/valkey.pid" ]; then
  echo "shard-0047-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_100_timeline_sample_01-20260628/shard-0047-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0047-replica-00" "$pid_value"

#!/bin/sh
set -eu
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0005-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0005-primary/valkey.pid" ]; then
  echo "shard-0005-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0005-primary/valkey.pid")
printf "%s\t%s\n" "shard-0005-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0013-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0013-primary/valkey.pid" ]; then
  echo "shard-0013-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0013-primary/valkey.pid")
printf "%s\t%s\n" "shard-0013-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0021-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0021-primary/valkey.pid" ]; then
  echo "shard-0021-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0021-primary/valkey.pid")
printf "%s\t%s\n" "shard-0021-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0029-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0029-primary/valkey.pid" ]; then
  echo "shard-0029-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0029-primary/valkey.pid")
printf "%s\t%s\n" "shard-0029-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0037-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0037-primary/valkey.pid" ]; then
  echo "shard-0037-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0037-primary/valkey.pid")
printf "%s\t%s\n" "shard-0037-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0045-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0045-primary/valkey.pid" ]; then
  echo "shard-0045-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0045-primary/valkey.pid")
printf "%s\t%s\n" "shard-0045-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0053-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0053-primary/valkey.pid" ]; then
  echo "shard-0053-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0053-primary/valkey.pid")
printf "%s\t%s\n" "shard-0053-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0061-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0061-primary/valkey.pid" ]; then
  echo "shard-0061-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0061-primary/valkey.pid")
printf "%s\t%s\n" "shard-0061-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0069-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0069-primary/valkey.pid" ]; then
  echo "shard-0069-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0069-primary/valkey.pid")
printf "%s\t%s\n" "shard-0069-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0077-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0077-primary/valkey.pid" ]; then
  echo "shard-0077-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0077-primary/valkey.pid")
printf "%s\t%s\n" "shard-0077-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0085-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0085-primary/valkey.pid" ]; then
  echo "shard-0085-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0085-primary/valkey.pid")
printf "%s\t%s\n" "shard-0085-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0093-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0093-primary/valkey.pid" ]; then
  echo "shard-0093-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0093-primary/valkey.pid")
printf "%s\t%s\n" "shard-0093-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0000-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0000-replica-00/valkey.pid" ]; then
  echo "shard-0000-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0000-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0000-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0008-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0008-replica-00/valkey.pid" ]; then
  echo "shard-0008-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0008-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0008-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0016-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0016-replica-00/valkey.pid" ]; then
  echo "shard-0016-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0016-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0016-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0024-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0024-replica-00/valkey.pid" ]; then
  echo "shard-0024-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0024-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0024-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0032-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0032-replica-00/valkey.pid" ]; then
  echo "shard-0032-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0032-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0032-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0040-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0040-replica-00/valkey.pid" ]; then
  echo "shard-0040-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0040-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0040-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0048-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0048-replica-00/valkey.pid" ]; then
  echo "shard-0048-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0048-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0048-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0056-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0056-replica-00/valkey.pid" ]; then
  echo "shard-0056-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0056-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0056-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0064-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0064-replica-00/valkey.pid" ]; then
  echo "shard-0064-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0064-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0064-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0072-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0072-replica-00/valkey.pid" ]; then
  echo "shard-0072-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0072-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0072-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0080-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0080-replica-00/valkey.pid" ]; then
  echo "shard-0080-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0080-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0080-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0088-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0088-replica-00/valkey.pid" ]; then
  echo "shard-0088-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0088-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0088-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0096-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0096-replica-00/valkey.pid" ]; then
  echo "shard-0096-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY-p44_scale_200_timeline_sample_01-20260628/shard-0096-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0096-replica-00" "$pid_value"

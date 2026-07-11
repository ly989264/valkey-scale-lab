#!/bin/sh
set -eu
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0001-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0001-primary/valkey.pid" ]; then
  echo "shard-0001-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0001-primary/valkey.pid")
printf "%s\t%s\n" "shard-0001-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0003-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0003-primary/valkey.pid" ]; then
  echo "shard-0003-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0003-primary/valkey.pid")
printf "%s\t%s\n" "shard-0003-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0005-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0005-primary/valkey.pid" ]; then
  echo "shard-0005-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0005-primary/valkey.pid")
printf "%s\t%s\n" "shard-0005-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0007-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0007-primary/valkey.pid" ]; then
  echo "shard-0007-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0007-primary/valkey.pid")
printf "%s\t%s\n" "shard-0007-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0009-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0009-primary/valkey.pid" ]; then
  echo "shard-0009-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0009-primary/valkey.pid")
printf "%s\t%s\n" "shard-0009-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0011-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0011-primary/valkey.pid" ]; then
  echo "shard-0011-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0011-primary/valkey.pid")
printf "%s\t%s\n" "shard-0011-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0013-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0013-primary/valkey.pid" ]; then
  echo "shard-0013-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0013-primary/valkey.pid")
printf "%s\t%s\n" "shard-0013-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0015-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0015-primary/valkey.pid" ]; then
  echo "shard-0015-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0015-primary/valkey.pid")
printf "%s\t%s\n" "shard-0015-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0017-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0017-primary/valkey.pid" ]; then
  echo "shard-0017-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0017-primary/valkey.pid")
printf "%s\t%s\n" "shard-0017-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0019-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0019-primary/valkey.pid" ]; then
  echo "shard-0019-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0019-primary/valkey.pid")
printf "%s\t%s\n" "shard-0019-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0021-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0021-primary/valkey.pid" ]; then
  echo "shard-0021-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0021-primary/valkey.pid")
printf "%s\t%s\n" "shard-0021-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0023-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0023-primary/valkey.pid" ]; then
  echo "shard-0023-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0023-primary/valkey.pid")
printf "%s\t%s\n" "shard-0023-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0025-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0025-primary/valkey.pid" ]; then
  echo "shard-0025-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0025-primary/valkey.pid")
printf "%s\t%s\n" "shard-0025-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0027-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0027-primary/valkey.pid" ]; then
  echo "shard-0027-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0027-primary/valkey.pid")
printf "%s\t%s\n" "shard-0027-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0029-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0029-primary/valkey.pid" ]; then
  echo "shard-0029-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0029-primary/valkey.pid")
printf "%s\t%s\n" "shard-0029-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0031-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0031-primary/valkey.pid" ]; then
  echo "shard-0031-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0031-primary/valkey.pid")
printf "%s\t%s\n" "shard-0031-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0033-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0033-primary/valkey.pid" ]; then
  echo "shard-0033-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0033-primary/valkey.pid")
printf "%s\t%s\n" "shard-0033-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0035-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0035-primary/valkey.pid" ]; then
  echo "shard-0035-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0035-primary/valkey.pid")
printf "%s\t%s\n" "shard-0035-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0037-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0037-primary/valkey.pid" ]; then
  echo "shard-0037-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0037-primary/valkey.pid")
printf "%s\t%s\n" "shard-0037-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0039-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0039-primary/valkey.pid" ]; then
  echo "shard-0039-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0039-primary/valkey.pid")
printf "%s\t%s\n" "shard-0039-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0041-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0041-primary/valkey.pid" ]; then
  echo "shard-0041-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0041-primary/valkey.pid")
printf "%s\t%s\n" "shard-0041-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0043-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0043-primary/valkey.pid" ]; then
  echo "shard-0043-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0043-primary/valkey.pid")
printf "%s\t%s\n" "shard-0043-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0045-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0045-primary/valkey.pid" ]; then
  echo "shard-0045-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0045-primary/valkey.pid")
printf "%s\t%s\n" "shard-0045-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0047-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0047-primary/valkey.pid" ]; then
  echo "shard-0047-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0047-primary/valkey.pid")
printf "%s\t%s\n" "shard-0047-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0049-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0049-primary/valkey.pid" ]; then
  echo "shard-0049-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0049-primary/valkey.pid")
printf "%s\t%s\n" "shard-0049-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0051-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0051-primary/valkey.pid" ]; then
  echo "shard-0051-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0051-primary/valkey.pid")
printf "%s\t%s\n" "shard-0051-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0053-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0053-primary/valkey.pid" ]; then
  echo "shard-0053-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0053-primary/valkey.pid")
printf "%s\t%s\n" "shard-0053-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0055-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0055-primary/valkey.pid" ]; then
  echo "shard-0055-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0055-primary/valkey.pid")
printf "%s\t%s\n" "shard-0055-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0057-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0057-primary/valkey.pid" ]; then
  echo "shard-0057-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0057-primary/valkey.pid")
printf "%s\t%s\n" "shard-0057-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0059-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0059-primary/valkey.pid" ]; then
  echo "shard-0059-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0059-primary/valkey.pid")
printf "%s\t%s\n" "shard-0059-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0061-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0061-primary/valkey.pid" ]; then
  echo "shard-0061-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0061-primary/valkey.pid")
printf "%s\t%s\n" "shard-0061-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0063-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0063-primary/valkey.pid" ]; then
  echo "shard-0063-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0063-primary/valkey.pid")
printf "%s\t%s\n" "shard-0063-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0065-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0065-primary/valkey.pid" ]; then
  echo "shard-0065-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0065-primary/valkey.pid")
printf "%s\t%s\n" "shard-0065-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0067-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0067-primary/valkey.pid" ]; then
  echo "shard-0067-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0067-primary/valkey.pid")
printf "%s\t%s\n" "shard-0067-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0069-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0069-primary/valkey.pid" ]; then
  echo "shard-0069-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0069-primary/valkey.pid")
printf "%s\t%s\n" "shard-0069-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0071-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0071-primary/valkey.pid" ]; then
  echo "shard-0071-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0071-primary/valkey.pid")
printf "%s\t%s\n" "shard-0071-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0073-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0073-primary/valkey.pid" ]; then
  echo "shard-0073-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0073-primary/valkey.pid")
printf "%s\t%s\n" "shard-0073-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0075-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0075-primary/valkey.pid" ]; then
  echo "shard-0075-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0075-primary/valkey.pid")
printf "%s\t%s\n" "shard-0075-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0077-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0077-primary/valkey.pid" ]; then
  echo "shard-0077-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0077-primary/valkey.pid")
printf "%s\t%s\n" "shard-0077-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0079-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0079-primary/valkey.pid" ]; then
  echo "shard-0079-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0079-primary/valkey.pid")
printf "%s\t%s\n" "shard-0079-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0081-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0081-primary/valkey.pid" ]; then
  echo "shard-0081-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0081-primary/valkey.pid")
printf "%s\t%s\n" "shard-0081-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0083-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0083-primary/valkey.pid" ]; then
  echo "shard-0083-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0083-primary/valkey.pid")
printf "%s\t%s\n" "shard-0083-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0085-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0085-primary/valkey.pid" ]; then
  echo "shard-0085-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0085-primary/valkey.pid")
printf "%s\t%s\n" "shard-0085-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0087-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0087-primary/valkey.pid" ]; then
  echo "shard-0087-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0087-primary/valkey.pid")
printf "%s\t%s\n" "shard-0087-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0089-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0089-primary/valkey.pid" ]; then
  echo "shard-0089-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0089-primary/valkey.pid")
printf "%s\t%s\n" "shard-0089-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0091-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0091-primary/valkey.pid" ]; then
  echo "shard-0091-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0091-primary/valkey.pid")
printf "%s\t%s\n" "shard-0091-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0093-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0093-primary/valkey.pid" ]; then
  echo "shard-0093-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0093-primary/valkey.pid")
printf "%s\t%s\n" "shard-0093-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0095-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0095-primary/valkey.pid" ]; then
  echo "shard-0095-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0095-primary/valkey.pid")
printf "%s\t%s\n" "shard-0095-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0097-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0097-primary/valkey.pid" ]; then
  echo "shard-0097-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0097-primary/valkey.pid")
printf "%s\t%s\n" "shard-0097-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0099-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0099-primary/valkey.pid" ]; then
  echo "shard-0099-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0099-primary/valkey.pid")
printf "%s\t%s\n" "shard-0099-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0000-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0000-replica-00/valkey.pid" ]; then
  echo "shard-0000-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0000-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0000-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0002-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0002-replica-00/valkey.pid" ]; then
  echo "shard-0002-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0002-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0002-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0004-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0004-replica-00/valkey.pid" ]; then
  echo "shard-0004-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0004-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0004-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0006-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0006-replica-00/valkey.pid" ]; then
  echo "shard-0006-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0006-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0006-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0008-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0008-replica-00/valkey.pid" ]; then
  echo "shard-0008-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0008-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0008-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0010-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0010-replica-00/valkey.pid" ]; then
  echo "shard-0010-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0010-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0010-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0012-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0012-replica-00/valkey.pid" ]; then
  echo "shard-0012-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0012-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0012-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0014-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0014-replica-00/valkey.pid" ]; then
  echo "shard-0014-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0014-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0014-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0016-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0016-replica-00/valkey.pid" ]; then
  echo "shard-0016-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0016-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0016-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0018-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0018-replica-00/valkey.pid" ]; then
  echo "shard-0018-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0018-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0018-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0020-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0020-replica-00/valkey.pid" ]; then
  echo "shard-0020-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0020-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0020-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0022-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0022-replica-00/valkey.pid" ]; then
  echo "shard-0022-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0022-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0022-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0024-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0024-replica-00/valkey.pid" ]; then
  echo "shard-0024-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0024-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0024-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0026-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0026-replica-00/valkey.pid" ]; then
  echo "shard-0026-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0026-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0026-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0028-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0028-replica-00/valkey.pid" ]; then
  echo "shard-0028-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0028-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0028-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0030-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0030-replica-00/valkey.pid" ]; then
  echo "shard-0030-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0030-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0030-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0032-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0032-replica-00/valkey.pid" ]; then
  echo "shard-0032-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0032-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0032-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0034-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0034-replica-00/valkey.pid" ]; then
  echo "shard-0034-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0034-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0034-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0036-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0036-replica-00/valkey.pid" ]; then
  echo "shard-0036-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0036-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0036-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0038-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0038-replica-00/valkey.pid" ]; then
  echo "shard-0038-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0038-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0038-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0040-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0040-replica-00/valkey.pid" ]; then
  echo "shard-0040-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0040-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0040-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0042-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0042-replica-00/valkey.pid" ]; then
  echo "shard-0042-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0042-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0042-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0044-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0044-replica-00/valkey.pid" ]; then
  echo "shard-0044-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0044-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0044-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0046-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0046-replica-00/valkey.pid" ]; then
  echo "shard-0046-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0046-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0046-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0048-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0048-replica-00/valkey.pid" ]; then
  echo "shard-0048-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0048-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0048-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0050-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0050-replica-00/valkey.pid" ]; then
  echo "shard-0050-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0050-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0050-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0052-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0052-replica-00/valkey.pid" ]; then
  echo "shard-0052-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0052-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0052-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0054-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0054-replica-00/valkey.pid" ]; then
  echo "shard-0054-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0054-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0054-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0056-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0056-replica-00/valkey.pid" ]; then
  echo "shard-0056-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0056-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0056-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0058-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0058-replica-00/valkey.pid" ]; then
  echo "shard-0058-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0058-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0058-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0060-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0060-replica-00/valkey.pid" ]; then
  echo "shard-0060-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0060-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0060-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0062-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0062-replica-00/valkey.pid" ]; then
  echo "shard-0062-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0062-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0062-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0064-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0064-replica-00/valkey.pid" ]; then
  echo "shard-0064-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0064-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0064-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0066-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0066-replica-00/valkey.pid" ]; then
  echo "shard-0066-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0066-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0066-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0068-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0068-replica-00/valkey.pid" ]; then
  echo "shard-0068-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0068-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0068-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0070-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0070-replica-00/valkey.pid" ]; then
  echo "shard-0070-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0070-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0070-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0072-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0072-replica-00/valkey.pid" ]; then
  echo "shard-0072-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0072-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0072-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0074-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0074-replica-00/valkey.pid" ]; then
  echo "shard-0074-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0074-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0074-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0076-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0076-replica-00/valkey.pid" ]; then
  echo "shard-0076-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0076-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0076-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0078-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0078-replica-00/valkey.pid" ]; then
  echo "shard-0078-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0078-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0078-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0080-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0080-replica-00/valkey.pid" ]; then
  echo "shard-0080-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0080-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0080-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0082-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0082-replica-00/valkey.pid" ]; then
  echo "shard-0082-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0082-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0082-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0084-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0084-replica-00/valkey.pid" ]; then
  echo "shard-0084-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0084-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0084-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0086-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0086-replica-00/valkey.pid" ]; then
  echo "shard-0086-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0086-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0086-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0088-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0088-replica-00/valkey.pid" ]; then
  echo "shard-0088-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0088-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0088-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0090-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0090-replica-00/valkey.pid" ]; then
  echo "shard-0090-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0090-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0090-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0092-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0092-replica-00/valkey.pid" ]; then
  echo "shard-0092-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0092-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0092-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0094-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0094-replica-00/valkey.pid" ]; then
  echo "shard-0094-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0094-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0094-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0096-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0096-replica-00/valkey.pid" ]; then
  echo "shard-0096-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0096-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0096-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0098-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0098-replica-00/valkey.pid" ]; then
  echo "shard-0098-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P21_FAILOVER_LATENCY_CURVE_200-scale_200_sample_02-20260628/shard-0098-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0098-replica-00" "$pid_value"

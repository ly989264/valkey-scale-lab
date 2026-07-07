#!/bin/sh
set -eu
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0003-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0003-primary/valkey.pid" ]; then
  echo "shard-0003-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0003-primary/valkey.pid")
printf "%s\t%s\n" "shard-0003-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0011-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0011-primary/valkey.pid" ]; then
  echo "shard-0011-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0011-primary/valkey.pid")
printf "%s\t%s\n" "shard-0011-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0019-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0019-primary/valkey.pid" ]; then
  echo "shard-0019-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0019-primary/valkey.pid")
printf "%s\t%s\n" "shard-0019-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0027-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0027-primary/valkey.pid" ]; then
  echo "shard-0027-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0027-primary/valkey.pid")
printf "%s\t%s\n" "shard-0027-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0035-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0035-primary/valkey.pid" ]; then
  echo "shard-0035-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0035-primary/valkey.pid")
printf "%s\t%s\n" "shard-0035-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0043-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0043-primary/valkey.pid" ]; then
  echo "shard-0043-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0043-primary/valkey.pid")
printf "%s\t%s\n" "shard-0043-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0051-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0051-primary/valkey.pid" ]; then
  echo "shard-0051-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0051-primary/valkey.pid")
printf "%s\t%s\n" "shard-0051-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0059-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0059-primary/valkey.pid" ]; then
  echo "shard-0059-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0059-primary/valkey.pid")
printf "%s\t%s\n" "shard-0059-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0067-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0067-primary/valkey.pid" ]; then
  echo "shard-0067-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0067-primary/valkey.pid")
printf "%s\t%s\n" "shard-0067-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0075-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0075-primary/valkey.pid" ]; then
  echo "shard-0075-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0075-primary/valkey.pid")
printf "%s\t%s\n" "shard-0075-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0083-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0083-primary/valkey.pid" ]; then
  echo "shard-0083-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0083-primary/valkey.pid")
printf "%s\t%s\n" "shard-0083-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0091-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0091-primary/valkey.pid" ]; then
  echo "shard-0091-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0091-primary/valkey.pid")
printf "%s\t%s\n" "shard-0091-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0099-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0099-primary/valkey.pid" ]; then
  echo "shard-0099-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0099-primary/valkey.pid")
printf "%s\t%s\n" "shard-0099-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0006-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0006-replica-00/valkey.pid" ]; then
  echo "shard-0006-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0006-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0006-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0014-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0014-replica-00/valkey.pid" ]; then
  echo "shard-0014-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0014-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0014-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0022-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0022-replica-00/valkey.pid" ]; then
  echo "shard-0022-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0022-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0022-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0030-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0030-replica-00/valkey.pid" ]; then
  echo "shard-0030-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0030-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0030-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0038-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0038-replica-00/valkey.pid" ]; then
  echo "shard-0038-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0038-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0038-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0046-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0046-replica-00/valkey.pid" ]; then
  echo "shard-0046-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0046-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0046-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0054-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0054-replica-00/valkey.pid" ]; then
  echo "shard-0054-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0054-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0054-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0062-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0062-replica-00/valkey.pid" ]; then
  echo "shard-0062-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0062-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0062-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0070-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0070-replica-00/valkey.pid" ]; then
  echo "shard-0070-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0070-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0070-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0078-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0078-replica-00/valkey.pid" ]; then
  echo "shard-0078-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0078-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0078-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0086-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0086-replica-00/valkey.pid" ]; then
  echo "shard-0086-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0086-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0086-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0094-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0094-replica-00/valkey.pid" ]; then
  echo "shard-0094-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_200_layered_sample_01-20260628/shard-0094-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0094-replica-00" "$pid_value"

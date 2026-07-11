#!/bin/sh
set -eu
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0002-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0002-primary/valkey.pid" ]; then
  echo "shard-0002-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0002-primary/valkey.pid")
printf "%s\t%s\n" "shard-0002-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0006-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0006-primary/valkey.pid" ]; then
  echo "shard-0006-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0006-primary/valkey.pid")
printf "%s\t%s\n" "shard-0006-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0010-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0010-primary/valkey.pid" ]; then
  echo "shard-0010-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0010-primary/valkey.pid")
printf "%s\t%s\n" "shard-0010-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0014-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0014-primary/valkey.pid" ]; then
  echo "shard-0014-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0014-primary/valkey.pid")
printf "%s\t%s\n" "shard-0014-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0018-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0018-primary/valkey.pid" ]; then
  echo "shard-0018-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0018-primary/valkey.pid")
printf "%s\t%s\n" "shard-0018-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0022-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0022-primary/valkey.pid" ]; then
  echo "shard-0022-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0022-primary/valkey.pid")
printf "%s\t%s\n" "shard-0022-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0001-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0001-replica-00/valkey.pid" ]; then
  echo "shard-0001-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0001-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0001-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0005-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0005-replica-00/valkey.pid" ]; then
  echo "shard-0005-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0005-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0005-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0009-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0009-replica-00/valkey.pid" ]; then
  echo "shard-0009-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0009-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0009-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0013-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0013-replica-00/valkey.pid" ]; then
  echo "shard-0013-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0013-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0013-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0017-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0017-replica-00/valkey.pid" ]; then
  echo "shard-0017-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0017-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0017-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0021-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0021-replica-00/valkey.pid" ]; then
  echo "shard-0021-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_50_layered_sample_01-20260628/shard-0021-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0021-replica-00" "$pid_value"

#!/bin/sh
set -eu
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0001-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0001-primary/valkey.pid" ]; then
  echo "shard-0001-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0001-primary/valkey.pid")
printf "%s\t%s\n" "shard-0001-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0005-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0005-primary/valkey.pid" ]; then
  echo "shard-0005-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0005-primary/valkey.pid")
printf "%s\t%s\n" "shard-0005-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0009-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0009-primary/valkey.pid" ]; then
  echo "shard-0009-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0009-primary/valkey.pid")
printf "%s\t%s\n" "shard-0009-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0013-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0013-primary/valkey.pid" ]; then
  echo "shard-0013-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0013-primary/valkey.pid")
printf "%s\t%s\n" "shard-0013-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0017-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0017-primary/valkey.pid" ]; then
  echo "shard-0017-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0017-primary/valkey.pid")
printf "%s\t%s\n" "shard-0017-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0021-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0021-primary/valkey.pid" ]; then
  echo "shard-0021-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0021-primary/valkey.pid")
printf "%s\t%s\n" "shard-0021-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0025-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0025-primary/valkey.pid" ]; then
  echo "shard-0025-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0025-primary/valkey.pid")
printf "%s\t%s\n" "shard-0025-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0029-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0029-primary/valkey.pid" ]; then
  echo "shard-0029-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0029-primary/valkey.pid")
printf "%s\t%s\n" "shard-0029-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0033-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0033-primary/valkey.pid" ]; then
  echo "shard-0033-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0033-primary/valkey.pid")
printf "%s\t%s\n" "shard-0033-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0037-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0037-primary/valkey.pid" ]; then
  echo "shard-0037-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0037-primary/valkey.pid")
printf "%s\t%s\n" "shard-0037-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0041-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0041-primary/valkey.pid" ]; then
  echo "shard-0041-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0041-primary/valkey.pid")
printf "%s\t%s\n" "shard-0041-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0045-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0045-primary/valkey.pid" ]; then
  echo "shard-0045-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0045-primary/valkey.pid")
printf "%s\t%s\n" "shard-0045-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0049-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0049-primary/valkey.pid" ]; then
  echo "shard-0049-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0049-primary/valkey.pid")
printf "%s\t%s\n" "shard-0049-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0002-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0002-replica-00/valkey.pid" ]; then
  echo "shard-0002-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0002-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0002-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0006-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0006-replica-00/valkey.pid" ]; then
  echo "shard-0006-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0006-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0006-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0010-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0010-replica-00/valkey.pid" ]; then
  echo "shard-0010-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0010-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0010-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0014-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0014-replica-00/valkey.pid" ]; then
  echo "shard-0014-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0014-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0014-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0018-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0018-replica-00/valkey.pid" ]; then
  echo "shard-0018-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0018-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0018-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0022-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0022-replica-00/valkey.pid" ]; then
  echo "shard-0022-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0022-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0022-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0026-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0026-replica-00/valkey.pid" ]; then
  echo "shard-0026-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0026-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0026-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0030-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0030-replica-00/valkey.pid" ]; then
  echo "shard-0030-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0030-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0030-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0034-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0034-replica-00/valkey.pid" ]; then
  echo "shard-0034-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0034-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0034-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0038-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0038-replica-00/valkey.pid" ]; then
  echo "shard-0038-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0038-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0038-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0042-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0042-replica-00/valkey.pid" ]; then
  echo "shard-0042-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0042-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0042-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0046-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0046-replica-00/valkey.pid" ]; then
  echo "shard-0046-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0046-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0046-replica-00" "$pid_value"

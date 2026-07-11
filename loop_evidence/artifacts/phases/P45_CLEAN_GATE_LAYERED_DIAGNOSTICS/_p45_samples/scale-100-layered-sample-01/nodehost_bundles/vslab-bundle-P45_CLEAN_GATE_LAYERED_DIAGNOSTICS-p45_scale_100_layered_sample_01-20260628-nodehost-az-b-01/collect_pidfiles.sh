#!/bin/sh
set -eu
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0003-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0003-primary/valkey.pid" ]; then
  echo "shard-0003-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0003-primary/valkey.pid")
printf "%s\t%s\n" "shard-0003-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0007-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0007-primary/valkey.pid" ]; then
  echo "shard-0007-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0007-primary/valkey.pid")
printf "%s\t%s\n" "shard-0007-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0011-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0011-primary/valkey.pid" ]; then
  echo "shard-0011-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0011-primary/valkey.pid")
printf "%s\t%s\n" "shard-0011-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0015-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0015-primary/valkey.pid" ]; then
  echo "shard-0015-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0015-primary/valkey.pid")
printf "%s\t%s\n" "shard-0015-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0019-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0019-primary/valkey.pid" ]; then
  echo "shard-0019-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0019-primary/valkey.pid")
printf "%s\t%s\n" "shard-0019-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0023-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0023-primary/valkey.pid" ]; then
  echo "shard-0023-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0023-primary/valkey.pid")
printf "%s\t%s\n" "shard-0023-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0027-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0027-primary/valkey.pid" ]; then
  echo "shard-0027-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0027-primary/valkey.pid")
printf "%s\t%s\n" "shard-0027-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0031-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0031-primary/valkey.pid" ]; then
  echo "shard-0031-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0031-primary/valkey.pid")
printf "%s\t%s\n" "shard-0031-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0035-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0035-primary/valkey.pid" ]; then
  echo "shard-0035-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0035-primary/valkey.pid")
printf "%s\t%s\n" "shard-0035-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0039-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0039-primary/valkey.pid" ]; then
  echo "shard-0039-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0039-primary/valkey.pid")
printf "%s\t%s\n" "shard-0039-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0043-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0043-primary/valkey.pid" ]; then
  echo "shard-0043-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0043-primary/valkey.pid")
printf "%s\t%s\n" "shard-0043-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0047-primary/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0047-primary/valkey.pid" ]; then
  echo "shard-0047-primary\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0047-primary/valkey.pid")
printf "%s\t%s\n" "shard-0047-primary" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0000-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0000-replica-00/valkey.pid" ]; then
  echo "shard-0000-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0000-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0000-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0004-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0004-replica-00/valkey.pid" ]; then
  echo "shard-0004-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0004-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0004-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0008-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0008-replica-00/valkey.pid" ]; then
  echo "shard-0008-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0008-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0008-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0012-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0012-replica-00/valkey.pid" ]; then
  echo "shard-0012-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0012-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0012-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0016-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0016-replica-00/valkey.pid" ]; then
  echo "shard-0016-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0016-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0016-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0020-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0020-replica-00/valkey.pid" ]; then
  echo "shard-0020-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0020-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0020-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0024-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0024-replica-00/valkey.pid" ]; then
  echo "shard-0024-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0024-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0024-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0028-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0028-replica-00/valkey.pid" ]; then
  echo "shard-0028-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0028-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0028-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0032-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0032-replica-00/valkey.pid" ]; then
  echo "shard-0032-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0032-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0032-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0036-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0036-replica-00/valkey.pid" ]; then
  echo "shard-0036-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0036-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0036-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0040-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0040-replica-00/valkey.pid" ]; then
  echo "shard-0040-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0040-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0040-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0044-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0044-replica-00/valkey.pid" ]; then
  echo "shard-0044-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0044-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0044-replica-00" "$pid_value"
attempts=0
while [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0048-replica-00/valkey.pid" ] && [ "$attempts" -lt 30 ]; do
  attempts=$((attempts + 1))
  sleep 1
done
if [ ! -s "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0048-replica-00/valkey.pid" ]; then
  echo "shard-0048-replica-00\tMISSING" >&2
  exit 1
fi
pid_value=$(cat "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_100_layered_sample_01-20260628/shard-0048-replica-00/valkey.pid")
printf "%s\t%s\n" "shard-0048-replica-00" "$pid_value"

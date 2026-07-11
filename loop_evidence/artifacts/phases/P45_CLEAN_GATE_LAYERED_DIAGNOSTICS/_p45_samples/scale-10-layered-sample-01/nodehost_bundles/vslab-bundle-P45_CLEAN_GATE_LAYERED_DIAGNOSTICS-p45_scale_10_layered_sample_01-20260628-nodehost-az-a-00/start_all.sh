#!/bin/sh
set -eu
valkey-server "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_10_layered_sample_01-20260628/shard-0000-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_10_layered_sample_01-20260628/shard-0004-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_10_layered_sample_01-20260628/shard-0003-replica-00/valkey.conf"

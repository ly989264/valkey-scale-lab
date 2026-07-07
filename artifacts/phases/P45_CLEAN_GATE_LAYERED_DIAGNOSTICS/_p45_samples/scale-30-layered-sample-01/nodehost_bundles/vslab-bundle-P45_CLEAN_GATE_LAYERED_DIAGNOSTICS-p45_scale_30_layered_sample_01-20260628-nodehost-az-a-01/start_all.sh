#!/bin/sh
set -eu
valkey-server "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_30_layered_sample_01-20260628/shard-0002-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_30_layered_sample_01-20260628/shard-0006-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_30_layered_sample_01-20260628/shard-0010-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_30_layered_sample_01-20260628/shard-0014-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_30_layered_sample_01-20260628/shard-0003-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_30_layered_sample_01-20260628/shard-0007-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_30_layered_sample_01-20260628/shard-0011-replica-00/valkey.conf"

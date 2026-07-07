#!/bin/sh
set -eu
BUNDLE_DIR="/tmp/vslab-bundle-P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_10_layered_sample_01-20260628-nodehost-az-b-00"
mkdir -p "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_10_layered_sample_01-20260628/shard-0001-primary"
cp "$BUNDLE_DIR/node_configs/shard-0001-primary.conf" "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_10_layered_sample_01-20260628/shard-0001-primary/valkey.conf"
mkdir -p "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_10_layered_sample_01-20260628/shard-0000-replica-00"
cp "$BUNDLE_DIR/node_configs/shard-0000-replica-00.conf" "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_10_layered_sample_01-20260628/shard-0000-replica-00/valkey.conf"
mkdir -p "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_10_layered_sample_01-20260628/shard-0004-replica-00"
cp "$BUNDLE_DIR/node_configs/shard-0004-replica-00.conf" "/tmp/valkey-scale-lab/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS-p45_scale_10_layered_sample_01-20260628/shard-0004-replica-00/valkey.conf"

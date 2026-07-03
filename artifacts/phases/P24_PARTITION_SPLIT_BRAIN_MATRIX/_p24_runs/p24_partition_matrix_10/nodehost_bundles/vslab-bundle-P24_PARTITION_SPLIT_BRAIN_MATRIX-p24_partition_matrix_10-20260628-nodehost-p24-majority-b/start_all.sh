#!/bin/sh
set -eu
valkey-server "/tmp/valkey-scale-lab/P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_10-20260628/shard-0002-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_10-20260628/shard-0004-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_10-20260628/shard-0001-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P24_PARTITION_SPLIT_BRAIN_MATRIX-p24_partition_matrix_10-20260628/shard-0003-replica-00/valkey.conf"

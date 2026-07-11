#!/bin/sh
set -eu
valkey-server "/tmp/valkey-scale-lab/P22_FAULT_REPLICA_HOST_AZ_STOP-p22_fault_matrix_6-20260628/shard-0000-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P22_FAULT_REPLICA_HOST_AZ_STOP-p22_fault_matrix_6-20260628/shard-0002-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P22_FAULT_REPLICA_HOST_AZ_STOP-p22_fault_matrix_6-20260628/shard-0001-replica-00/valkey.conf"

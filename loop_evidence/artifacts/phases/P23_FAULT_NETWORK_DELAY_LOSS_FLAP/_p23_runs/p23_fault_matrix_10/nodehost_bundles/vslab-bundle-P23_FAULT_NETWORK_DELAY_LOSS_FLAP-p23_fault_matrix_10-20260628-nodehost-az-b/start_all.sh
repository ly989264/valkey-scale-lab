#!/bin/sh
set -eu
valkey-server "/tmp/valkey-scale-lab/P23_FAULT_NETWORK_DELAY_LOSS_FLAP-p23_fault_matrix_10-20260628/shard-0001-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P23_FAULT_NETWORK_DELAY_LOSS_FLAP-p23_fault_matrix_10-20260628/shard-0003-primary/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P23_FAULT_NETWORK_DELAY_LOSS_FLAP-p23_fault_matrix_10-20260628/shard-0000-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P23_FAULT_NETWORK_DELAY_LOSS_FLAP-p23_fault_matrix_10-20260628/shard-0002-replica-00/valkey.conf"
valkey-server "/tmp/valkey-scale-lab/P23_FAULT_NETWORK_DELAY_LOSS_FLAP-p23_fault_matrix_10-20260628/shard-0004-replica-00/valkey.conf"

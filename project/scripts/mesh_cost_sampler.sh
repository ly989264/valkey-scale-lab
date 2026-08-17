#!/bin/sh
# What does the cluster-bus mesh actually cost, per node and per host?
#
# Measured from outside the product, on the hosts, because a run's own evidence
# records neither term: `node_memory_limit_mb` is a dataset cap, nothing samples
# process RSS, and kernel socket memory appears nowhere at all.
#
# One row per host per interval, space separated:
#   ts host nodes rss_total_mb rss_mean_kb rss_max_kb tcp_inuse tcp_mem_pages load1
KEY=$HOME/.ssh/vslab_fleet
KH=$HOME/.ssh/vslab_fleet_known_hosts
INTERVAL=${INTERVAL:-20}
while :; do
  for i in $HOSTS; do
    h=10.148.0.$i
    ssh -o ConnectTimeout=6 -o BatchMode=yes -i "$KEY" -o UserKnownHostsFile="$KH" root@$h "
      ps -eo rss,comm 2>/dev/null | awk -v ts=\$(date +%s) -v h=$h -v ld=\$(cut -d' ' -f1 /proc/loadavg) '
        /valkey-server/ { s += \$1; c++; if (\$1 > m) m = \$1 }
        END {
          while ((getline line < \"/proc/net/sockstat\") > 0)
            if (line ~ /^TCP:/) { split(line, f, \" \"); inuse = f[3]; pages = f[length(f)] }
          printf \"%s %s %d %d %d %d %s %s %s\n\", ts, h, c, s/1024, (c ? s/c : 0), m, inuse, pages, ld
        }'
    " 2>/dev/null
  done
  sleep "$INTERVAL"
done

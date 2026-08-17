#!/bin/sh
# Did `cluster-link-sendbuf-limit` ever fire, and what did the send queues hold?
#
# A run that passes proves the cap did not break it. What says whether the cap
# was ever *reached* is `total_cluster_links_buffer_limit_exceeded`, Valkey's own
# count of links it freed for exceeding the limit - the difference between
# "harmless because it is sized right" and "harmless because it never fired".
#
# **That counter is already in a run's own evidence, and this samples it anyway
# for one reason.** It is a `CLUSTER INFO` field, and the product captures raw
# `CLUSTER INFO` text in `fault_sequence.json`, `fault_command_log.jsonl` and
# `fault_results.json` - 7,618 occurrences in the frozen
# `real-exact-200-c58a762a` baseline, every one of them `0`, which at an
# unlimited cap it could not have been anything else. So the fault lane can be
# read straight out of the artifacts and needs nothing from here.
#
# The window that cannot is **cluster formation**, which is where the send
# queues fill and so the only place a cap sized for 1280 nodes can bite. No
# artifact captures `CLUSTER INFO` there. That is what this is for, and it is
# the same evidence gap `mesh_cost_sampler.sh` was written for.
#
# `mem_cluster_links` is sampled beside it because the counter alone cannot say
# how close a run came: it is what the links hold right now, send queues and
# receive buffers together, and it is 426,656 bytes per node at 200 nodes.
#
# One row per host per interval, space separated:
#   ts host nodes_sampled links_freed_total mem_links_total_bytes
#   mem_links_max_bytes sendbuf_limit
#
# `links_freed_total` is cumulative per node since that node started, so it is
# summed over the host's sampled nodes and only grows within a run; any non-zero
# value at any point is the finding.
#
# HOSTS is the last-octet list, as in `mesh_cost_sampler.sh`. NODES_PER_HOST
# bounds how many of a host's nodes are asked, because at 107 nodes per host
# asking every one every interval is itself load. The sample is the lowest N by
# port and is reported in `nodes_sampled` rather than assumed to be all of them.
#
# The per-host half is a *file*, pushed once and then invoked, rather than a
# quoted blob inlined in the ssh command. Three levels of shell quoting is how
# the first version of this silently produced no rows at all.
KEY=$HOME/.ssh/vslab_fleet
KH=$HOME/.ssh/vslab_fleet_known_hosts
INTERVAL=${INTERVAL:-20}
NODES_PER_HOST=${NODES_PER_HOST:-8}
REMOTE=/tmp/vslab_sendbuf_probe.sh

probe='#!/bin/sh
n=${1:-8}
cli=$(ls -1 /opt/valkey-scale-lab/bundles/*/bin/valkey-cli 2>/dev/null | head -1)
[ -n "$cli" ] || exit 0
ports=$(ss -ltnH 2>/dev/null | awk "{print \$4}" | sed "s/.*://" \
        | awk -v lo=7000 -v hi=17000 "\$1+0>=lo && \$1+0<hi {print \$1}" \
        | sort -n | uniq | head -"$n")
[ -n "$ports" ] || exit 0
c=0; freed=0; mem=0; max=0; lim=-1
for p in $ports; do
  f=$("$cli" -p "$p" CLUSTER INFO 2>/dev/null | tr -d "\r" \
      | awk -F: "/^total_cluster_links_buffer_limit_exceeded:/{print \$2}")
  [ -n "$f" ] || continue
  m=$("$cli" -p "$p" INFO memory 2>/dev/null | tr -d "\r" \
      | awk -F: "/^mem_cluster_links:/{print \$2}")
  [ -n "$m" ] || m=0
  c=$((c+1)); freed=$((freed+f)); mem=$((mem+m))
  [ "$m" -gt "$max" ] && max=$m
  if [ "$lim" -lt 0 ]; then
    lim=$("$cli" -p "$p" CONFIG GET cluster-link-sendbuf-limit 2>/dev/null | tr -d "\r" | tail -1)
  fi
done
[ "$c" -gt 0 ] && echo "$(date +%s) $(hostname -I | cut -d" " -f1) $c $freed $mem $max $lim"
'

for i in $HOSTS; do
  printf '%s' "$probe" | ssh -o ConnectTimeout=6 -o BatchMode=yes -i "$KEY" \
    -o UserKnownHostsFile="$KH" "root@10.148.0.$i" "cat > $REMOTE" 2>/dev/null
done

while :; do
  for i in $HOSTS; do
    ssh -o ConnectTimeout=6 -o BatchMode=yes -i "$KEY" -o UserKnownHostsFile="$KH" \
      "root@10.148.0.$i" "sh $REMOTE $NODES_PER_HOST" 2>/dev/null
  done
  sleep "$INTERVAL"
done

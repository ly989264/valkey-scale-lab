# A simulated ECS instance: a plain Linux host that answers ssh.
#
# Lab tooling, not product. Docker stands where ECS will stand, and nothing the
# product receives says so - the harness hands the product an inventory manifest
# of addresses and nothing else.
#
# Derived from the pinned Valkey image so that the OS, glibc and shared
# libraries a native bundle links against are exactly the ones the pinned build
# produced its binaries for. That is the whole reason for the derivation, and it
# is also why the derivation *removes* what it inherits: a host that already
# carries valkey-server would let a bundle install prove nothing, because the
# binary on PATH would be the image's rather than the one the run shipped.
# Measured on the pinned image before writing this: /usr/local/bin holds
# valkey-server, valkey-cli and memtier_benchmark, and there is no sshd,
# ssh-keygen, ip or iptables.
#
# The runtime dependencies stay: libevent (memtier links against it) and python3
# (§11.1's on-host resource sampler). Provisioning those is a host-image concern
# on a real fleet too, so keeping them is faithful rather than convenient.
#
# The parent is referenced by tag, not by digest, because it is built locally
# and never pushed; a digest reference would send Docker looking for a registry.
# scripts/build_simulated_host_image.sh reads the parent's digest before it
# builds and records it, which is the same guarantee at the place that can
# actually check it.

ARG VALKEY_LAB_IMAGE=valkey-scale-lab/valkey:9.1.0-myslots
ARG DEBIAN_SNAPSHOT=20260713T000000Z

FROM ${VALKEY_LAB_IMAGE} AS simulated-host

ARG VALKEY_LAB_IMAGE
ARG DEBIAN_SNAPSHOT

# openssh-server is the host's control endpoint. iproute2 and iptables are what
# a later item's partition actuator needs in order to use the real mechanism
# instead of `docker network disconnect`; the container is granted NET_ADMIN at
# run time. snapshot.debian.org answers 500 intermittently, so the retry count
# is higher than the pinned image's and pipelining is off - measured while
# proving the packages install at all.
RUN sed -i \
        -e "s|URIs: http://deb.debian.org/debian$|URIs: http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}|" \
        -e "s|URIs: http://deb.debian.org/debian-security$|URIs: http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}|" \
        /etc/apt/sources.list.d/debian.sources \
    && printf '%s\n' \
        'Acquire::Check-Valid-Until "false";' \
        'Acquire::Retries "15";' \
        'Acquire::http::Pipeline-Depth "0";' \
        > /etc/apt/apt.conf.d/99snapshot \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        iproute2 \
        iptables \
        openssh-server \
    && rm -rf /var/lib/apt/lists/*

# What a bare host does not have. The run's own bundle puts these back; that is
# what makes a native install observable.
RUN rm -f \
        /usr/local/bin/valkey-server \
        /usr/local/bin/valkey-cli \
        /usr/local/bin/memtier_benchmark \
    && rm -rf /usr/local/share/valkey-scale-lab \
    && ! command -v valkey-server \
    && ! command -v memtier_benchmark

# Key-only root login. The manifest carries the user, so a real fleet is free to
# differ; root is what this harness offers because the partition actuator needs
# NET_ADMIN and adding a sudo path would be surface with nothing behind it.
RUN mkdir -p /run/sshd /root/.ssh \
    && chmod 700 /root/.ssh \
    && printf '%s\n' \
        'PermitRootLogin prohibit-password' \
        'PasswordAuthentication no' \
        'KbdInteractiveAuthentication no' \
        'PermitUserEnvironment no' \
        'UseDNS no' \
        'AcceptEnv LANG LC_*' \
        > /etc/ssh/sshd_config.d/10-simulated-host.conf

# Host keys are generated on first boot rather than baked in, so each simulated
# host has its own fingerprint and the manifest can carry it. A fleet whose
# hosts all present one key would hide a whole class of transport mistake.
#
# Deleting them here is the half that makes the entrypoint's `ssh-keygen -A`
# do anything: Debian's openssh-server postinst already generated a set during
# the apt step above, so the first fleet this harness brought up served one
# fingerprint from both hosts - measured, not predicted.
RUN rm -f /etc/ssh/ssh_host_*

RUN printf '%s\n' \
        '#!/bin/sh' \
        'set -eu' \
        'ssh-keygen -A >/dev/null' \
        'if [ -n "${SIMULATED_HOST_AUTHORIZED_KEY:-}" ]; then' \
        '  printf "%s\n" "$SIMULATED_HOST_AUTHORIZED_KEY" > /root/.ssh/authorized_keys' \
        '  chmod 600 /root/.ssh/authorized_keys' \
        'else' \
        '  echo "SIMULATED_HOST_AUTHORIZED_KEY is required" >&2' \
        '  exit 64' \
        'fi' \
        'exec /usr/sbin/sshd -D -e' \
        > /usr/local/sbin/simulated-host-entrypoint \
    && chmod 0755 /usr/local/sbin/simulated-host-entrypoint

# The parent's digest is read by the build script and passed back in, because a
# tag alone records nothing about which build this host was derived from.
ARG VALKEY_LAB_IMAGE_DIGEST
RUN test -n "${VALKEY_LAB_IMAGE_DIGEST}"

LABEL org.valkey-scale-lab.simulated-host="true" \
      org.valkey-scale-lab.simulated-host.parent.image="${VALKEY_LAB_IMAGE}" \
      org.valkey-scale-lab.simulated-host.parent.digest="${VALKEY_LAB_IMAGE_DIGEST}" \
      org.valkey-scale-lab.simulated-host.debian.snapshot="${DEBIAN_SNAPSHOT}"

EXPOSE 22
ENTRYPOINT ["/usr/local/sbin/simulated-host-entrypoint"]

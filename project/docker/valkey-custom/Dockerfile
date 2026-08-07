ARG VALKEY_VERSION=9.1.0
ARG VALKEY_SOURCE_SHA256=7789fe1df257774457bafb4c1d56c9f7020c3879a7f5b4234af9030b2bd82dfd
ARG VALKEY_PATCH_SHA256=d42df002c5c37c5900debabcb71dacc293236042661609ebb09379d350891c92
ARG VALKEY_BASE_IMAGE=valkey/valkey:9.1.0@sha256:8e8d64b405ce18f41b8e5ee20aa4687a8ed0022d1298f2ce31cdcf3a76e09411
ARG DEBIAN_SNAPSHOT=20260713T000000Z
# The load lane drives traffic from inside a nodehost container, because the
# cluster advertises Docker network addresses that a macOS host cannot route.
ARG MEMTIER_VERSION=2.5.1
ARG MEMTIER_SOURCE_SHA256=9b34e17a0d1d7e70b152eb442c6362161b5b764ce2ea98e97b7c74815bdd90b7

FROM ${VALKEY_BASE_IMAGE} AS builder

ARG VALKEY_VERSION
ARG VALKEY_SOURCE_SHA256
ARG VALKEY_PATCH_SHA256
ARG MEMTIER_VERSION
ARG MEMTIER_SOURCE_SHA256
ARG DEBIAN_SNAPSHOT

RUN sed -i \
        -e "s|URIs: http://deb.debian.org/debian$|URIs: http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}|" \
        -e "s|URIs: http://deb.debian.org/debian-security$|URIs: http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}|" \
        /etc/apt/sources.list.d/debian.sources \
    && printf '%s\n' \
        'Acquire::Check-Valid-Until "false";' \
        'Acquire::Retries "5";' \
        > /etc/apt/apt.conf.d/99snapshot \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        autoconf \
        automake \
        build-essential \
        ca-certificates \
        curl \
        libevent-dev \
        libpcre2-dev \
        libssl-dev \
        libsystemd-dev \
        libtool \
        patch \
        pkg-config \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

RUN curl --fail --location --silent --show-error \
        --output valkey.tar.gz \
        "https://github.com/valkey-io/valkey/archive/refs/tags/${VALKEY_VERSION}.tar.gz" \
    && echo "${VALKEY_SOURCE_SHA256}  valkey.tar.gz" | sha256sum --check --strict \
    && mkdir source \
    && tar --extract --gzip --file valkey.tar.gz --directory source --strip-components=1

COPY patches/valkey/0001-add-cluster-myslots.patch /build/cluster-myslots.patch

RUN echo "${VALKEY_PATCH_SHA256}  cluster-myslots.patch" | sha256sum --check --strict \
    && patch --directory=source --strip=1 --fuzz=0 --batch --input=/build/cluster-myslots.patch \
    && grep -F '"myslots"' source/src/commands.def

RUN make --directory=source -j"$(nproc)" \
        BUILD_TLS=yes \
        USE_SYSTEMD=yes \
    && source/src/valkey-server --version | grep -F 'malloc=jemalloc' \
    && source/src/valkey-cli --version \
    && mkdir /out \
    && install -m 0755 source/src/valkey-server /out/valkey-server \
    && install -m 0755 source/src/valkey-cli /out/valkey-cli \
    && server_sha="$(sha256sum /out/valkey-server | cut -d ' ' -f 1)" \
    && cli_sha="$(sha256sum /out/valkey-cli | cut -d ' ' -f 1)" \
    && printf '%s\n' \
        "valkey_version=${VALKEY_VERSION}" \
        "source_sha256=${VALKEY_SOURCE_SHA256}" \
        "patch_sha256=${VALKEY_PATCH_SHA256}" \
        "valkey_server_sha256=${server_sha}" \
        "valkey_cli_sha256=${cli_sha}" \
        > /out/build-manifest.txt

RUN curl --fail --location --silent --show-error \
        --output memtier.tar.gz \
        "https://github.com/RedisLabs/memtier_benchmark/archive/refs/tags/${MEMTIER_VERSION}.tar.gz" \
    && echo "${MEMTIER_SOURCE_SHA256}  memtier.tar.gz" | sha256sum --check --strict \
    && mkdir memtier \
    && tar --extract --gzip --file memtier.tar.gz --directory memtier --strip-components=1 \
    && cd memtier \
    && autoreconf -ivf \
    && ./configure \
    && make -j"$(nproc)" \
    && ./memtier_benchmark --version | grep -F "memtier_benchmark v=${MEMTIER_VERSION}" \
    && install -m 0755 memtier_benchmark /out/memtier_benchmark \
    && memtier_sha="$(sha256sum /out/memtier_benchmark | cut -d ' ' -f 1)" \
    && printf '%s\n' \
        "memtier_version=${MEMTIER_VERSION}" \
        "memtier_source_sha256=${MEMTIER_SOURCE_SHA256}" \
        "memtier_benchmark_sha256=${memtier_sha}" \
        >> /out/build-manifest.txt

FROM scratch AS binaries
COPY --from=builder /out/ /

FROM ${VALKEY_BASE_IMAGE} AS runtime

ARG VALKEY_VERSION
ARG VALKEY_SOURCE_SHA256
ARG VALKEY_PATCH_SHA256
ARG VALKEY_SERVER_SHA256
ARG VALKEY_CLI_SHA256
ARG MEMTIER_VERSION
ARG MEMTIER_SOURCE_SHA256
ARG MEMTIER_BENCHMARK_SHA256
ARG DEBIAN_SNAPSHOT

COPY --from=builder --chmod=0755 /out/valkey-server /usr/local/bin/valkey-server
COPY --from=builder --chmod=0755 /out/valkey-cli /usr/local/bin/valkey-cli
COPY --from=builder --chmod=0755 /out/memtier_benchmark /usr/local/bin/memtier_benchmark
COPY --from=builder /out/build-manifest.txt /usr/local/share/valkey-scale-lab/build-manifest.txt

# memtier links against libevent, which the Valkey base image does not carry.
# python3 runs the nodehost-local resource sampler: the design requires one
# long-lived sampler per nodehost reading its own procfs, not a session per
# sample from outside.
RUN sed -i \
        -e "s|URIs: http://deb.debian.org/debian$|URIs: http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}|" \
        -e "s|URIs: http://deb.debian.org/debian-security$|URIs: http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}|" \
        /etc/apt/sources.list.d/debian.sources \
    && printf '%s\n' \
        'Acquire::Check-Valid-Until "false";' \
        'Acquire::Retries "5";' \
        > /etc/apt/apt.conf.d/99snapshot \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        libevent-2.1-7 \
        libevent-extra-2.1-7 \
        libevent-openssl-2.1-7 \
        libevent-pthreads-2.1-7 \
        python3 \
    && rm -rf /var/lib/apt/lists/*

RUN test -n "${VALKEY_SERVER_SHA256}" \
    && test -n "${VALKEY_CLI_SHA256}" \
    && test -n "${MEMTIER_BENCHMARK_SHA256}" \
    && echo "${VALKEY_SERVER_SHA256}  /usr/local/bin/valkey-server" | sha256sum --check --strict \
    && echo "${VALKEY_CLI_SHA256}  /usr/local/bin/valkey-cli" | sha256sum --check --strict \
    && echo "${MEMTIER_BENCHMARK_SHA256}  /usr/local/bin/memtier_benchmark" | sha256sum --check --strict \
    && grep -Fx "valkey_version=${VALKEY_VERSION}" /usr/local/share/valkey-scale-lab/build-manifest.txt \
    && grep -Fx "source_sha256=${VALKEY_SOURCE_SHA256}" /usr/local/share/valkey-scale-lab/build-manifest.txt \
    && grep -Fx "patch_sha256=${VALKEY_PATCH_SHA256}" /usr/local/share/valkey-scale-lab/build-manifest.txt \
    && grep -Fx "memtier_version=${MEMTIER_VERSION}" /usr/local/share/valkey-scale-lab/build-manifest.txt \
    && grep -Fx "memtier_source_sha256=${MEMTIER_SOURCE_SHA256}" /usr/local/share/valkey-scale-lab/build-manifest.txt \
    && memtier_benchmark --version | grep -F "memtier_benchmark v=${MEMTIER_VERSION}" \
    && python3 -c "import json, pathlib, threading, resource; print('python3 ok')"

LABEL org.valkey-scale-lab.valkey.version="${VALKEY_VERSION}" \
      org.valkey-scale-lab.valkey.source.sha256="${VALKEY_SOURCE_SHA256}" \
      org.valkey-scale-lab.valkey.patch.sha256="${VALKEY_PATCH_SHA256}" \
      org.valkey-scale-lab.valkey.server.sha256="${VALKEY_SERVER_SHA256}" \
      org.valkey-scale-lab.valkey.cli.sha256="${VALKEY_CLI_SHA256}" \
      org.valkey-scale-lab.memtier.version="${MEMTIER_VERSION}" \
      org.valkey-scale-lab.memtier.source.sha256="${MEMTIER_SOURCE_SHA256}" \
      org.valkey-scale-lab.memtier.benchmark.sha256="${MEMTIER_BENCHMARK_SHA256}"

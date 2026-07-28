ARG VALKEY_VERSION=9.1.0
ARG VALKEY_SOURCE_SHA256=7789fe1df257774457bafb4c1d56c9f7020c3879a7f5b4234af9030b2bd82dfd
ARG VALKEY_PATCH_SHA256=d42df002c5c37c5900debabcb71dacc293236042661609ebb09379d350891c92
ARG VALKEY_BASE_IMAGE=valkey/valkey:9.1.0@sha256:8e8d64b405ce18f41b8e5ee20aa4687a8ed0022d1298f2ce31cdcf3a76e09411
ARG DEBIAN_SNAPSHOT=20260713T000000Z

FROM ${VALKEY_BASE_IMAGE} AS builder

ARG VALKEY_VERSION
ARG VALKEY_SOURCE_SHA256
ARG VALKEY_PATCH_SHA256
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
        build-essential \
        ca-certificates \
        curl \
        libssl-dev \
        libsystemd-dev \
        patch \
        pkg-config \
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

FROM scratch AS binaries
COPY --from=builder /out/ /

FROM ${VALKEY_BASE_IMAGE} AS runtime

ARG VALKEY_VERSION
ARG VALKEY_SOURCE_SHA256
ARG VALKEY_PATCH_SHA256
ARG VALKEY_SERVER_SHA256
ARG VALKEY_CLI_SHA256

COPY --from=builder --chmod=0755 /out/valkey-server /usr/local/bin/valkey-server
COPY --from=builder --chmod=0755 /out/valkey-cli /usr/local/bin/valkey-cli
COPY --from=builder /out/build-manifest.txt /usr/local/share/valkey-scale-lab/build-manifest.txt

RUN test -n "${VALKEY_SERVER_SHA256}" \
    && test -n "${VALKEY_CLI_SHA256}" \
    && echo "${VALKEY_SERVER_SHA256}  /usr/local/bin/valkey-server" | sha256sum --check --strict \
    && echo "${VALKEY_CLI_SHA256}  /usr/local/bin/valkey-cli" | sha256sum --check --strict \
    && grep -Fx "valkey_version=${VALKEY_VERSION}" /usr/local/share/valkey-scale-lab/build-manifest.txt \
    && grep -Fx "source_sha256=${VALKEY_SOURCE_SHA256}" /usr/local/share/valkey-scale-lab/build-manifest.txt \
    && grep -Fx "patch_sha256=${VALKEY_PATCH_SHA256}" /usr/local/share/valkey-scale-lab/build-manifest.txt

LABEL org.valkey-scale-lab.valkey.version="${VALKEY_VERSION}" \
      org.valkey-scale-lab.valkey.source.sha256="${VALKEY_SOURCE_SHA256}" \
      org.valkey-scale-lab.valkey.patch.sha256="${VALKEY_PATCH_SHA256}" \
      org.valkey-scale-lab.valkey.server.sha256="${VALKEY_SERVER_SHA256}" \
      org.valkey-scale-lab.valkey.cli.sha256="${VALKEY_CLI_SHA256}"

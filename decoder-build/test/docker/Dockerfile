# Test image: ARM (armel, soft-float) cross compiler + qemu-user, native arm64 on Apple silicon.
# Used only to build Linux-ARM copies of the same FFmpeg source/config and run them under qemu-arm.
FROM debian:bookworm-slim@sha256:3783cc01769c7b2b1b83a5c5ad96c815348e28ed7da68e2e3687004faa906251
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        gcc-arm-linux-gnueabi libc6-dev-armel-cross binutils-arm-linux-gnueabi \
        qemu-user make perl xz-utils ca-certificates gcc libc6-dev libglib2.0-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Runs SyncExtPack's upstream tools (crypto_pack, swfmill, secureSWF) inside
# Linux so none of those third-party binaries execute on the host.
FROM --platform=linux/amd64 ubuntu:20.04

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      python3 openjdk-8-jre-headless swfmill \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /work

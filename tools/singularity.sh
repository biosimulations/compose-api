#!/bin/bash

# Mount directory where you want singularity containers to be stored

# docker start --privileged --security-opt seccomp=unconfined --name singularity -it --platform linux/amd64 ubuntu:25.10

apt-get update && apt-get install -y \
    build-essential \
    libssl-dev \
    uuid-dev \
    libgpgme11-dev \
    squashfs-tools \
    libseccomp-dev \
    pkg-config \
    wget \
    libfuse3-dev \
    libsubid-dev \
    nano \
    runc \
    fuse \
    golang-go

export VERSION=4.3.3 &&
    wget https://github.com/sylabs/singularity/releases/download/v${VERSION}/singularity-ce-${VERSION}.tar.gz && \
    tar -xzf singularity-ce-${VERSION}.tar.gz && \
    cd singularity-ce-${VERSION}

./mconfig && \
    make -C builddir && \
    make -C builddir install

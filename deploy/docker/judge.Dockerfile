FROM xinbaoyan-backend:local
USER root
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl pkg-config libcap-dev libseccomp-dev libsystemd-dev \
    gcc-13 g++-13 openjdk-17-jdk-headless \
    && rm -rf /var/lib/apt/lists/*
# Pin the isolate version used by judge/linux_isolate.py and verify the
# archive digest before building the setuid binary.
RUN curl -fsSL https://github.com/ioi/isolate/archive/refs/tags/v2.0.tar.gz -o /tmp/isolate.tar.gz \
    && echo "17364f1b0f5d3d59fc917e1520f9a16d2b85bcb175b2615ab0dbfce09ab893f1  /tmp/isolate.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/isolate.tar.gz -C /tmp \
    && make -C /tmp/isolate-2.0 isolate isolate-cg-keeper \
    && make -C /tmp/isolate-2.0 install \
    && rm -rf /tmp/isolate-2.0 /tmp/isolate.tar.gz
RUN mkdir -p /opt/judge-toolchains/bin /opt/judge/rootfs \
    && ln -sf /usr/bin/gcc-13 /opt/judge-toolchains/bin/gcc \
    && ln -sf /usr/bin/g++-13 /opt/judge-toolchains/bin/g++ \
    && ln -sf /usr/bin/javac /opt/judge-toolchains/bin/javac \
    && ln -sf /usr/bin/java /opt/judge-toolchains/bin/java \
    && ln -sf /usr/bin/python3.12 /opt/judge-toolchains/bin/python3 \
    && printf 'box_root = /dev/shm/isolate\nlock_root = /run/isolate/locks\ncg_root = /sys/fs/cgroup/isolate\nfirst_uid = 60000\nfirst_gid = 60000\nnum_boxes = 1000\n' > /usr/local/etc/isolate

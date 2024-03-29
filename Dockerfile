FROM ghcr.io/metricq/metricq-python:v4.2 AS builder
LABEL maintainer="mario.bielert@tu-dresden.de"

USER root
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/* 

USER metricq
COPY --chown=metricq:metricq . /home/metricq/sink-nsca

WORKDIR /home/metricq/sink-nsca
RUN pip install --user .

FROM ghcr.io/metricq/metricq-python:v4.2

USER root
RUN echo 'deb http://deb.debian.org/debian bullseye-backports main' > /etc/apt/sources.list.d/backports.list \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y -t bullseye-backports\
    nsca-client \
    && rm -rf /var/lib/apt/lists/* 


USER metricq
COPY --from=BUILDER --chown=metricq:metricq /home/metricq/.local /home/metricq/.local

ENTRYPOINT [ "/home/metricq/.local/bin/metricq-sink-nsca" ]

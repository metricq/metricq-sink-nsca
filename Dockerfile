FROM python:3.11-slim-bookworm AS base
LABEL maintainer="mario.bielert@tu-dresden.de"

RUN useradd -m metricq

FROM base AS builder

USER root
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/* 

USER metricq
COPY --chown=metricq:metricq . /home/metricq/sink-nsca

WORKDIR /home/metricq/sink-nsca
RUN pip install --user .

FROM base

USER root
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    nsca-client \
    && rm -rf /var/lib/apt/lists/* 


USER metricq
COPY --from=BUILDER --chown=metricq:metricq /home/metricq/.local /home/metricq/.local

ENTRYPOINT [ "/home/metricq/.local/bin/metricq-sink-nsca" ]

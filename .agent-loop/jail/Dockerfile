# The jail image for this consumer's worker. Consumer data: the kernel names no
# image and builds none (agent-loop README "The jail"). It has to carry what
# this project's own commands need - python3 and git for ./gate and the pytest
# tree - and the agent CLI the claude-code adapter starts.
#
#   docker build -t agent-loop-jail-valkey:local .agent-loop/jail
#
FROM node:22-bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates python3 python3-pip \
 && rm -rf /var/lib/apt/lists/*

# The adapter starts `claude`; without it a jailed claude-code worker cannot run.
RUN npm install -g @anthropic-ai/claude-code@2.1.252

# What ./gate and the hermetic suite need. pytest is the version project/
# requirements-dev.txt pins.
RUN python3 -m pip install --no-cache-dir --break-system-packages pytest==8.4.2 pyyaml

COPY canary.py /usr/local/bin/agent-loop-canary
RUN chmod +x /usr/local/bin/agent-loop-canary

WORKDIR /workspace

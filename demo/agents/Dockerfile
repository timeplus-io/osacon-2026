# Agents container: Claude Code + Codex + the offline simulator, all wired to
# export OpenTelemetry to the Collector and to consult Proton through hooks.
FROM node:22-bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-pip git ca-certificates curl jq procps less \
 && rm -rf /var/lib/apt/lists/*

ARG CLAUDE_CODE_VERSION=latest
ARG CODEX_VERSION=latest
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} @openai/codex@${CODEX_VERSION} \
 && npm cache clean --force

COPY simulator/requirements.txt /opt/demo/simulator/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /opt/demo/simulator/requirements.txt

# hooks + agent configuration (system-level, so they apply to every session)
COPY hooks/proton_gate.py /opt/demo/hooks/proton_gate.py
COPY agents/claude/managed-settings.json /etc/claude-code/managed-settings.json
COPY agents/codex/config.toml /etc/codex/config.toml
COPY agents/codex/hooks.json /etc/codex/hooks.json
COPY simulator/simulator.py /opt/demo/simulator/simulator.py
COPY agents/entrypoint.sh /usr/local/bin/entrypoint.sh

# the base image's `node` user (uid 1000) runs the agents; Claude Code refuses
# some modes as root
USER node
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["bash"]

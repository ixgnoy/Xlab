# PersonaLab worker (Sokosumi Task executor + Masumi paid flow) and Standard API (MIP-003), one image.
# SERVICE=worker|api selects the process. Build from the repo root:
#   docker build -f deploy/node.Dockerfile -t personalab-node .
FROM node:24-slim

RUN npm install -g @masumi_network/sokosumi@1.0.4 && npm cache clean --force

ENV NODE_ENV=production \
    HOSTED=1 \
    DATA_DIR=/data \
    AGENT_API_HOST=:: \
    SERVICE=worker

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY *.mjs ./
# Public registration record (agent identifier, payment source index, seller vkey). No secrets.
COPY docs/registration-state.json ./docs/

# Runs as root: Railway volumes mount root-owned at /data and the worker sets 0700 on its data directory.
RUN mkdir -p /data
EXPOSE 8080
CMD ["sh", "-c", "case \"$SERVICE\" in worker) exec node worker.mjs ;; api) exec node agent-api.mjs ;; *) echo 'SERVICE must be worker or api' >&2; exit 64 ;; esac"]

# The service and its interface, with no build toolchain in
# the image. web/dist is committed, so this copies the built
# interface rather than installing Node to produce it.
FROM python:3.12-slim

# Runs unprivileged. The service reads provider credentials
# when they are mounted, and nothing here needs root.
RUN useradd --create-home --uid 10001 agent \
  && mkdir -p /data && chown agent:agent /data
WORKDIR /app

COPY agent_usage/ /app/agent_usage/
COPY web/dist/ /app/web/dist/
COPY LICENSE README.md /app/

USER agent

# Loopback inside the container. Publish a port to reach it,
# which keeps the decision to expose it an explicit one.
# Credential discovery follows HOME, so one volume holds both
# the state and whichever credential directories are mounted.
ENV HOME=/data
ENV AGENT_USAGE_STATE_DIR=/data/state
ENV PYTHONPATH=/app
VOLUME ["/data"]
EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s \
  CMD python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8787/healthz',timeout=3)"

ENTRYPOINT ["python3", "-m", "agent_usage.cli"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8787", "--allow-any-host"]

# Multi-stage build for memorygraph
# Stage 1: build
FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir build && python -m build --wheel

# Stage 2: runtime
FROM python:3.12-slim
LABEL org.opencontainers.image.title="memorygraph"
LABEL org.opencontainers.image.description="Local code knowledge graph with semantic layer"
LABEL org.opencontainers.image.version="0.0.1"

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

# Pre-install tree-sitter grammars so the non-root user doesn't need pip
RUN pip install --no-cache-dir \
    tree-sitter-python \
    tree-sitter-typescript \
    tree-sitter-go \
    tree-sitter-rust \
    tree-sitter-java \
    tree-sitter-c-sharp

RUN useradd --create-home --shell /bin/bash memorygraph
USER memorygraph
WORKDIR /project

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD ["memorygraph", "doctor", "--project-root", "/project"]

EXPOSE 8765
ENTRYPOINT ["memorygraph"]
CMD ["serve", "--web", "--host", "0.0.0.0", "--port", "8765"]

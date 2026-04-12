# =============================================================================
# Multi-stage Dockerfile for the dYdX Market Making Bot
#
# Stage 1: Build the C++ order book module (pybind11)
# Stage 2: Lightweight Python runtime with compiled .so
#
# Build:  docker build -t dydx-bot .
# Run:    docker run --env-file .env dydx-bot
# =============================================================================

# ── Stage 1: C++ Builder ────────────────────────────────────────────────────
FROM python:3.11-slim AS cpp-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        g++ \
        git \
        python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install pybind11 for the build
RUN pip install --no-cache-dir pybind11

WORKDIR /build
COPY cpp/ ./cpp/

RUN cd cpp \
    && mkdir -p build && cd build \
    && cmake .. \
        -DCMAKE_BUILD_TYPE=Release \
        -DPYTHON_EXECUTABLE="$(which python3)" \
    && make -j"$(nproc)" \
    && cp orderbook_cpp*.so /build/

# ── Stage 2: Runtime ────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL maintainer="meril" \
      description="dYdX v3 Market Making Bot with C++ order book engine" \
      version="3.0.0"

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        tini \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN useradd --create-home --shell /bin/bash botuser

WORKDIR /app

# Install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the compiled C++ module from builder stage
COPY --from=cpp-builder /build/orderbook_cpp*.so ./

# Copy application code
COPY dydx3/ ./dydx3/
COPY quant/ ./quant/
COPY bot.py .

# Ensure the app directory is on PYTHONPATH
ENV PYTHONPATH=/app

# Switch to non-root user
USER botuser

# Health check — bot logs heartbeat every BOT_HEARTBEAT_INTERVAL seconds
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD test -f /app/bot.log && find /app/bot.log -mmin -10 | grep -q . || exit 1

# Use tini as init to handle PID 1 and signal forwarding
ENTRYPOINT ["tini", "--"]
CMD ["python3", "bot.py"]

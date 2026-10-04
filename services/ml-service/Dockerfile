FROM python:3.12-slim
WORKDIR /app
# libgomp1 is required by LightGBM's native library (OpenMP runtime) --
# python:3.12-slim omits it, and the container fails at import time
# ("libgomp.so.1: cannot open shared object file") without this.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd -r vigil && useradd -r -g vigil vigil
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# Model artifacts are bind-mounted at runtime (see docker-compose.yml), not baked in.
RUN mkdir -p /app/artifacts && chown vigil:vigil /app/artifacts
USER vigil
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]

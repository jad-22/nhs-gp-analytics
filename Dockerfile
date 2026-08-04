# Two stages so the Parquet files and the pandas/pyarrow toolchain needed to compile
# them never reach the runtime image. What ships is FastAPI, DuckDB and one .duckdb
# file — no pandas, no statsmodels, no statsforecast, no Prophet. The API cannot fit a
# model even by accident, which is the point: forecasts are precomputed.

FROM python:3.11-slim AS builder

WORKDIR /build

# Compiling the serving database needs pandas and pyarrow; the runtime does not.
RUN pip install --no-cache-dir pandas==2.3.3 pyarrow==18.1.0 duckdb==1.5.4

COPY pipeline/__init__.py pipeline/config.py pipeline/entities.py ./pipeline/
COPY scripts/build_serving_db.py ./scripts/
COPY data/processed/list_size.parquet data/processed/mapping.parquet ./data/processed/
COPY data/processed/forecasts.parquet data/processed/forecast_metrics.parquet ./data/processed/

RUN python scripts/build_serving_db.py --output /build/serving.duckdb


FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SERVING_DB_PATH=/app/data/serving.duckdb

WORKDIR /app

COPY requirements-api.txt ./
RUN pip install --no-cache-dir -r requirements-api.txt

COPY api/ ./api/
COPY --from=builder /build/serving.duckdb /app/data/serving.duckdb

# Unprivileged, and the data is read-only anyway — there is nothing to write.
RUN useradd --create-home --uid 10001 api && chown -R api:api /app
USER api

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

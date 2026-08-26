# Multi-stage Docker build for Hugging Face Space
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY src/ ./src/
COPY run_experiment.py ./
COPY generate_interactive_quant_dashboard.py ./
COPY run_max_profit_simulation.py ./
COPY run_daily_reflection.py ./
COPY cpp_engine/ ./cpp_engine/
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

ENV PYTHONPATH=/app/backend:/app
ENV OMP_NUM_THREADS=8
ENV MKL_NUM_THREADS=8
ENV OPENBLAS_NUM_THREADS=8
ENV NUMEXPR_NUM_THREADS=8

RUN python3 generate_interactive_quant_dashboard.py || true

EXPOSE 7860

CMD ["uvicorn", "backend.main_api:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "4"]

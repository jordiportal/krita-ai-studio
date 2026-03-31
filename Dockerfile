# Krita AI Plugin Web - Backend Python + Frontend Angular
# Docker unificado para ejecutar todo en un solo contenedor

# ==================== ETAPA 1: Build Frontend ====================
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

# Copiar configuración
COPY frontend/package*.json ./
COPY frontend/angular.json ./
COPY frontend/tsconfig*.json ./

# Instalar dependencias
RUN npm install --no-audit --no-fund

# Copiar código fuente
COPY frontend/src ./src

# Build de producción
RUN npm run build -- --configuration production

# ==================== ETAPA 2: Backend + Serve ====================
FROM python:3.11-slim

# Variables de entorno
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar requirements e instalar
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar frontend build
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Copiar código backend
COPY backend/main.py .
COPY backend/workflow_krita.py .
COPY backend/civitai.py .

# Directorio de datos persistente (SQLite)
RUN mkdir -p /app/data
ENV DATA_DIR=/app/data

# Puerto
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:3000/api/health || exit 1

# Iniciar servidor
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3000"]

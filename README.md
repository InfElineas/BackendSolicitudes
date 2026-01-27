# Backend Solicitudes (FastAPI)

Backend en FastAPI para gestión de solicitudes internas. Usa MongoDB como base de datos y expone un API REST bajo el prefijo `/api`.

## Requisitos

- Python 3.10+ (recomendado 3.11)
- MongoDB en local o accesible por red

## Instalación local

1. **Clonar el repositorio** y entrar al directorio.
2. **Crear y activar un entorno virtual**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
   En Windows:
   ```powershell
   .venv\Scripts\Activate.ps1
   ```
3. **Instalar dependencias**:
   ```bash
   pip install -r requirements.txt
   ```
4. **Configurar variables de entorno**:
   ```bash
   cp .env.sample .env
   ```
   Ajusta los valores en `.env` según tu entorno (Mongo, JWT, CORS, etc.).

## Configuración (variables de entorno)

El archivo `.env.sample` incluye todas las variables soportadas. Las más importantes:

- `MONGO_URL`: cadena de conexión a MongoDB.
- `DB_NAME`: nombre de la base de datos.
- `SECRET_KEY`: clave para firmar JWT.
- `CORS_ORIGINS`: lista de orígenes permitidos (separados por coma).
- `PORT`: puerto local para el servidor.

## Ejecutar en local

Con el entorno virtual activo y MongoDB disponible:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Si usas `PORT` en `.env`, puedes omitir `--port`.

## Endpoints útiles

- `GET /health` → salud básica.
- `GET /ready` → readiness.
- API principal bajo `/api`.

## Notas

- En el arranque se crean índices y se aplican migraciones idempotentes.
- Para datos de ejemplo, revisa el bloque comentado `init_data()` en `app/main.py`.

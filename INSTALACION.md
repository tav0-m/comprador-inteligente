# 🛠️ Guía de Instalación — Comprador Inteligente

> Sigue los pasos en orden. Cada sección tiene un ✅ al final para que puedas marcar tu avance.

---

## Requisitos previos

Antes de empezar, necesitas tener instalado en tu computador:

| Herramienta | Versión mínima | Link de descarga |
|---|---|---|
| Python | 3.11+ | https://www.python.org/downloads/ |
| Docker Desktop | Cualquier reciente | https://www.docker.com/products/docker-desktop/ |
| Node.js | 18+ | https://nodejs.org/en/download |
| Go | 1.22+ | https://go.dev/dl/ |
| Rust + Cargo | 1.77+ | https://rustup.rs/ |
| Git | Cualquier reciente | https://git-scm.com/downloads |

> **Nota Windows:** Para Rust y Go en Windows, asegúrate de que estén en el PATH del sistema. Reinicia la terminal después de instalar cada uno.

---

## PASO 1 — Crear el entorno virtual Python

Abre una terminal **dentro de la carpeta del proyecto** (`Comprador _Inteligente`) y ejecuta:

```bash
# Crear entorno virtual
python -m venv venv

# Activarlo (Windows)
venv\Scripts\activate

# Activarlo (Mac / Linux)
source venv/bin/activate
```

Deberías ver `(venv)` al inicio de tu terminal. ✅

---

## PASO 2 — Instalar dependencias Python

Con el entorno virtual activo:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

Esto instala FastAPI, Streamlit, pandas, scikit-learn, LightGBM, Celery, Elasticsearch, Kafka, maturin y todas las demás dependencias.

> ⏳ Tarda entre 3 y 8 minutos la primera vez.

✅

---

## PASO 3 — Instalar Playwright (navegador headless)

```bash
playwright install chromium
```

Esto descarga el navegador Chromium que usan los scrapers avanzados (Sodimac, Falabella, Easy).

✅

---

## PASO 4 — Levantar todos los servicios con Docker

Asegúrate de que **Docker Desktop esté abierto y corriendo**.

```bash
docker-compose up -d
```

Esto levanta automáticamente:

| Servicio | URL / Puerto | Para qué sirve |
|---|---|---|
| API FastAPI | http://localhost:8000 | API REST principal |
| Documentación API | http://localhost:8000/docs | Swagger interactivo |
| Dashboard Streamlit | http://localhost:8501 | Dashboard de búsqueda |
| Frontend React | http://localhost:3000 | UI web moderna |
| Redis | localhost:6379 | Caché de búsquedas |
| PostgreSQL | localhost:5432 | Base de datos principal |
| Celery Worker | — | Búsquedas en background |
| Flower (monitor Celery) | http://localhost:5555 | Ver tareas async |
| Elasticsearch | http://localhost:9200 | Búsqueda full-text |
| Kibana | http://localhost:5601 | UI de Elasticsearch |
| Kafka | localhost:9092 | Mensajería event-driven |
| Kafka UI | http://localhost:8090 | Ver topics y mensajes |
| Go Scrapers | http://localhost:8081 | Scrapers de alta velocidad |
| n8n Automatización | http://localhost:5678 | Workflows automáticos |

> ⏳ La primera vez Docker descarga las imágenes. Puede tardar 10-15 minutos.

Para ver que todo esté bien:

```bash
docker-compose ps
```

Todos los servicios deben mostrar `Up` o `healthy`. ✅

---

## PASO 5 — Variables de entorno (opcional pero recomendado)

Crea un archivo `.env` en la raíz del proyecto copiando el ejemplo:

```bash
# Windows
copy .env.example .env

# Mac / Linux
cp .env.example .env
```

Luego abre `.env` con cualquier editor y configura las claves que necesites:

```env
# ── Obligatorio para alertas por email ────────────────────────
ALERT_EMAIL_FROM=tu_correo@gmail.com
ALERT_EMAIL_PASSWORD=tu_app_password_gmail

# ── Opcional: mejora los resultados de búsqueda ───────────────
SERPAPI_KEY=tu_clave_de_serpapi

# ── Contraseñas de UIs admin ──────────────────────────────────
FLOWER_USER=admin
FLOWER_PASS=comprador2026
N8N_USER=admin
N8N_PASS=comprador2026
```

> Para Gmail: necesitas crear una "Contraseña de aplicación" en https://myaccount.google.com/security (no uses tu contraseña normal de Gmail).

✅

---

## PASO 6 — Compilar la extensión Rust (mejora de rendimiento)

Este paso es **opcional** — el sistema funciona sin él usando Python puro como fallback.

Primero instala maturin si no lo hiciste con pip:

```bash
pip install maturin
```

Luego compila la extensión:

```bash
cd rust_ext
maturin develop --release
cd ..
```

Para verificar que funcionó:

```python
python -c "import clp_parser; print(clp_parser.info())"
# Debe mostrar: clp_parser v0.1.0 — Rust/PyO3 CLP price parser...
```

✅

---

## PASO 7 — Instalar el frontend Next.js (desarrollo local)

> Este paso solo es necesario si quieres correr el frontend fuera de Docker, por ejemplo para desarrollar.

```bash
cd frontend
npm install
npm run dev
```

El frontend estará en http://localhost:3000. ✅

---

## PASO 8 — Compilar el microservicio Go (desarrollo local)

> Solo necesario si quieres correr el servicio Go fuera de Docker.

```bash
cd go_scrapers
go mod download
go build -o go_scrapers .
./go_scrapers --port 8081
```

Para verificar:
```bash
curl http://localhost:8081/health
# Debe responder: {"status":"ok"}
```

✅

---

## PASO 9 — Verificar que todo funciona

Abre tu navegador y comprueba cada URL:

**1. API FastAPI — documentación interactiva**
```
http://localhost:8000/docs
```
Deberías ver la interfaz Swagger con todos los endpoints.

**2. Prueba una búsqueda**
```
http://localhost:8000/search?q=taladro&country=cl&max_results=5
```
Debe devolver JSON con productos.

**3. Dashboard Streamlit**
```
http://localhost:8501
```
Deberías ver el dashboard con el campo de búsqueda.

**4. Estado de servicios**
```
http://localhost:8000/health
http://localhost:8000/elasticsearch/status
http://localhost:8000/kafka/status
http://localhost:8000/worker/status
```

✅

---

## Comandos útiles del día a día

```bash
# Iniciar todo (después de apagarlo)
docker-compose up -d

# Apagar todo (sin borrar datos)
docker-compose down

# Ver logs en tiempo real
docker-compose logs -f api
docker-compose logs -f worker

# Reiniciar un servicio específico
docker-compose restart api

# Correr el dashboard Streamlit localmente (sin Docker)
streamlit run streamlit_app.py

# Correr los tests
pytest tests/ -v

# Ver estado de todos los contenedores
docker-compose ps
```

---

## Solución de problemas frecuentes

### ❌ "Port already in use" al hacer docker-compose up
Algún puerto está siendo usado por otro programa. Identifica cuál:
```bash
# Windows (cmd como administrador)
netstat -ano | findstr :8000

# Mac / Linux
lsof -i :8000
```
Cierra el programa que usa ese puerto, o cambia el puerto en `docker-compose.yml`.

### ❌ Streamlit no conecta con la API
Verifica que la API esté corriendo:
```bash
docker-compose ps api
curl http://localhost:8000/health
```

### ❌ Los scrapers no traen resultados
Verifica tu conexión a internet y que Playwright esté instalado:
```bash
playwright install chromium --force
```

### ❌ Elasticsearch no arranca (error de memoria)
```bash
# En Linux/Mac, aumentar vm.max_map_count
sudo sysctl -w vm.max_map_count=262144
```
En Windows, esto Docker lo maneja automáticamente si tienes al menos 4GB de RAM asignados a Docker Desktop.

### ❌ Error al compilar la extensión Rust
Asegúrate de tener Rust actualizado:
```bash
rustup update stable
```

### ❌ "ModuleNotFoundError" al correr Python directamente
Activa el entorno virtual primero:
```bash
# Windows
venv\Scripts\activate

# Mac / Linux
source venv/bin/activate
```

---

## Resumen de puertos

```
8000  →  API FastAPI          (principal)
8501  →  Streamlit Dashboard
3000  →  Frontend React/Next.js
8081  →  Go Scrapers
6379  →  Redis
5432  →  PostgreSQL
5555  →  Flower (Celery UI)
9092  →  Kafka
8090  →  Kafka UI
9200  →  Elasticsearch
5601  →  Kibana
5678  →  n8n
```

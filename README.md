# Comprador Inteligente v3.0 — Constructora Chile

Sistema profesional de comparación de precios con ML para constructoras.
Busca en **Sodimac · Easy · Falabella · Mercado Libre Chile** y rankea con IA.

## Arquitectura del sistema

```
Búsqueda
   │
   ├─ Sodimac CL (API interna)
   ├─ Easy CL (API VTEX)
   ├─ Falabella CL (API catálogo)
   ├─ Mercado Libre CL (API pública)
   ├─ SerpApi Google Shopping (opcional, requiere key)
   └─ CSV local (cotizaciones manuales)
          │
          ▼
   Normalización semántica (HTML clean + TF-IDF dedup)
          │
          ▼
   Detección de anomalías (IQR + Isolation Forest)
          │
          ▼
   ML Ranking (LightGBM — 16 features)
          │
          ▼
   FastAPI /search  →  Streamlit Dashboard
```

## Features del ranking ML

| Feature | Descripción |
|---|---|
| price_ratio_to_min | Qué tan barato es vs el más barato |
| price_ratio_to_median | Vs el precio mediano |
| title_sim | Similitud fuzzy título/query |
| store_trust | Confiabilidad de la tienda (Sodimac=1.0) |
| has_free_shipping | Envío gratis |
| rating_norm | Rating normalizado (0-1) |
| log_reviews | Logaritmo de reseñas |
| has_stock | Disponibilidad explícita |
| source_* | One-hot encoding de la fuente |

## Instalación

### 1. Entrar a la carpeta
```bash
cd "Comprador _Inteligente"
```

### 2. Crear y activar entorno virtual
```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# Mac/Linux
python -m venv .venv
source .venv/bin/activate
```

### 3. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 4. Configurar variables de entorno
```bash
# Windows
copy .env.example .env

# Mac/Linux
cp .env.example .env
```
Edita `.env` y agrega tu `SERPAPI_KEY` si tienes una (opcional).

### 5. Levantar la API
```bash
uvicorn app.main:app --reload --port 8000
```
Abre: http://127.0.0.1:8000/docs

### 6. Levantar el dashboard
En otra terminal (con el venv activado):
```bash
streamlit run streamlit_app.py
```
Abre: http://localhost:8501

## Endpoints disponibles

| Endpoint | Método | Descripción |
|---|---|---|
| /search?q=martillo | GET | Búsqueda principal con ML |
| /price-history?q=martillo | GET | Historial de precios |
| /stats | GET | Estadísticas globales |
| /history | GET | Últimas ofertas registradas |
| /feature-importance | GET | Importancia de features del modelo |
| /feedback | POST | Feedback usuario (mejora el modelo) |
| /retrain | POST | Re-entrena el modelo (requiere 100+ búsquedas) |

## Ejemplo de uso
```bash
curl "http://127.0.0.1:8000/search?q=tornillos+3+pulgadas&max_results=10"
curl "http://127.0.0.1:8000/search?q=martillo+carpintero"
curl "http://127.0.0.1:8000/search?q=cemento+portland+25+kg"
```

## Productos de construcción recomendados para buscar
- cemento portland 25 kg
- fierro corrugado 12mm
- tornillos volcanita 1 pulgada
- plancha OSB 9mm
- plancha yeso carton
- pintura anticorrosiva
- taladro percutor
- amoladora 4.5 pulgadas
- tubo PVC 4 pulgadas
- membrana impermeabilizante

## Re-entrenamiento del modelo ML
Después de hacer 100+ búsquedas, el sistema puede re-entrenarse con datos reales:
```bash
curl -X POST http://127.0.0.1:8000/retrain
```
O desde el dashboard en la sección **ML Info → Re-entrenar modelo**.

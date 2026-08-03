# Agregador Inmobiliario Mendoza — Fase 1

Extractor de publicaciones de "Venta de Departamentos y Casas" en Mendoza
desde **Mercado Libre Inmuebles**.

## Decisión de arquitectura de esta fase

En vez de scrapear el HTML de Mercado Libre con BeautifulSoup/Playwright,
esta primera versión usa la **API pública oficial de Mercado Libre**
(`https://api.mercadolibre.com/sites/MLA/search`). Motivos:

- Devuelve JSON estructurado y estable, sin depender de clases CSS que
  cambian cada semana.
- No requiere renderizar JS (más rápido, sin Playwright para esta fuente).
- Es la vía que el propio ML ofrece para consultar su catálogo, así que
  el riesgo de bloqueo por anti-bot es mucho menor que golpeando el HTML.

Cuando en próximas fases agreguemos **Zonaprop** y **Argenprop** (que no
tienen API pública), ahí sí vamos a necesitar `httpx` + `BeautifulSoup4`
o `Playwright` para sitios con contenido dinámico. La estructura del
proyecto ya está pensada para eso: cada portal es un módulo independiente
en `scrapers/`, y todos devuelven el mismo esquema (`schema.Propiedad`).

## Estructura de archivos

```
inmo-agregador/
├── config.py                      # configuración centralizada (URLs, timeouts, logging)
├── schema.py                      # esquema estándar (Propiedad) al que todo scraper normaliza
├── main.py                        # punto de entrada: corre el scraper y guarda JSON
├── requirements.txt
├── scrapers/
│   ├── __init__.py
│   ├── mercadolibre.py            # scraper de Mercado Libre (vía API pública)
│   └── utils/
│       ├── __init__.py
│       └── normalizador.py        # funciones puras de limpieza/normalización
├── data/                           # acá se guardan los JSON extraídos (se crea sola)
└── logs/                           # logs de ejecución (se crea sola)
```

## Instalación

```bash
# 1. Crear entorno virtual (recomendado)
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Instalar dependencias
pip install -r requirements.txt

# (playwright se instala ahora pero recién se usa en Fase 2+ para
# portales sin API pública; si querés instalar sus navegadores:)
playwright install chromium
```

## Ejecución

```bash
# Extracción por defecto: 200 departamentos en venta en Mendoza
python main.py

# Personalizar cantidad y búsqueda
python main.py --max 100 --query "casa venta mendoza"
python main.py --max 300 --query "terreno venta mendoza" --output data/terrenos.json
```

El resultado queda en `data/propiedades_mercadolibre.json`, con esta forma
por cada propiedad (esquema estándar que van a compartir TODOS los
portales que agreguemos después):

```json
{
  "id_fuente": "MLA999999999",
  "portal": "mercadolibre",
  "url_fuente": "https://articulo.mercadolibre.com.ar/MLA-999999999",
  "titulo": "Departamento 2 ambientes en Godoy Cruz",
  "tipo_operacion": "venta",
  "tipo_propiedad": "departamento",
  "precio": 85000.0,
  "moneda": "USD",
  "provincia": "Mendoza",
  "departamento": "Godoy Cruz",
  "barrio": "Palmares",
  "direccion": "Av. San Martin 1234",
  "latitud": -32.95,
  "longitud": -68.85,
  "superficie_cubierta_m2": 45.0,
  "superficie_total_m2": 45.0,
  "ambientes": 2,
  "dormitorios": 1,
  "banios": 1,
  "cochera": true,
  "fotos": ["https://img.mlstatic.com/foto1.jpg", "..."],
  "foto_portada": "https://img.mlstatic.com/foto1.jpg",
  "fecha_extraccion": "2026-07-29T23:41:02+00:00",
  "hash_duplicado": "1d2ee729b6394ee7cd8b6482863b3b0a"
}
```

### Sobre `hash_duplicado`

Es un primer filtro barato para detectar posibles duplicados entre
portales (misma propiedad publicada en ML y en una inmobiliaria local,
por ejemplo): combina tipo de propiedad, barrio, superficie y precio
redondeado. **No es definitivo** — en Fase 2 (base de datos) vamos a
afinar esto con matching geoespacial y/o similitud de texto, porque dos
propiedades distintas pueden coincidir por casualidad y una misma
propiedad puede tener pequeñas diferencias de precio entre portales.

## Notas y limitaciones de esta fase

- La API pública de búsqueda de ML no permite paginar más allá de ~1000
  resultados por query (está en `config.ML_MAX_OFFSET`); para traer todo
  el stock de Mendoza vamos a necesitar combinar varias queries por
  zona/tipo de propiedad en vez de una sola búsqueda gigante.
- Algunos campos (fotos en alta resolución, datos de contacto) requieren
  autenticación OAuth de ML, que no se implementó todavía porque no
  hace falta para el buscador.
- Si un item no tiene algún atributo (ej. superficie no informada), el
  campo queda en `null` — es esperable, no un error del scraper.

## Próximos pasos (Fase 2)

Diseño del esquema PostgreSQL/Supabase para la tabla `propiedades`
(basado 1 a 1 en `schema.Propiedad`), con:
- índice geoespacial (PostGIS) sobre `latitud`/`longitud`,
- estrategia definitiva de deduplicación,
- tabla `portales` para trackear de dónde vino cada fuente.
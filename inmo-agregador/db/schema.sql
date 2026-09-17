-- db/schema.sql
-- ---------------------------------------------------------------------
-- Esquema relacional de Fase 2.
--
-- Diseño: dos tablas en vez de una tabla plana, porque la MISMA
-- propiedad física suele estar publicada en varios portales a la vez
-- (ej: un depto en Godoy Cruz publicado en Mercado Libre Y en la web de
-- la inmobiliaria). Modelarlo plano forzaría a elegir "cuál publicación
-- es la real", perdiendo información. Con dos tablas:
--
--   inmuebles     -> el inmueble físico (registro canónico/unificado)
--   publicaciones -> cada publicación individual de un portal,
--                    apuntando (opcionalmente) a su inmueble canónico
--
-- inmueble_id es NULLABLE a propósito: cuando el scraper trae una
-- publicación nueva, todavía no sabemos con certeza si corresponde a un
-- inmueble ya visto por otro portal. El matching (por hash o, más
-- adelante, por cercanía geoespacial) puede fallar o no ejecutarse
-- todavía, y no queremos que eso bloquee guardar la publicación.
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS inmuebles (
    id                      BIGSERIAL PRIMARY KEY,

    -- Datos "canónicos": representan el consenso entre publicaciones
    -- (por ahora, los de la primera publicación que creó el registro;
    -- en fases futuras se puede afinar con lógica de "mejor dato entre
    -- fuentes", ej: la superficie más frecuente entre 3 publicaciones).
    titulo_representativo   TEXT,
    tipo_propiedad          TEXT,               -- departamento | casa | terreno | ph | local...

    provincia               TEXT NOT NULL DEFAULT 'Mendoza',
    departamento            TEXT,               -- ej: "Godoy Cruz", "Capital"
    barrio                  TEXT,
    direccion               TEXT,
    latitud                 DOUBLE PRECISION,
    longitud                DOUBLE PRECISION,

    superficie_cubierta_m2  NUMERIC(10, 2),
    superficie_total_m2     NUMERIC(10, 2),
    ambientes               SMALLINT,
    dormitorios             SMALLINT,
    banios                  SMALLINT,
    cochera                 BOOLEAN,

    -- Hash usado para matchear publicaciones nuevas contra inmuebles
    -- existentes (ver schema.py::Propiedad.hash_duplicado en el lado
    -- Python). Es un primer filtro barato, NO definitivo: dos
    -- propiedades distintas pueden coincidir por casualidad. Fase 3+
    -- puede reemplazar/complementar esto con matching geoespacial.
    hash_deduplicacion      TEXT,

    creado_en               TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado_en          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_inmuebles_hash ON inmuebles (hash_deduplicacion);
CREATE INDEX IF NOT EXISTS idx_inmuebles_departamento ON inmuebles (departamento);
-- Índice geoespacial: se agrega en una fase posterior cuando se habilite
-- la extensión PostGIS y se migren latitud/longitud a un tipo geography.


CREATE TABLE IF NOT EXISTS publicaciones (
    id                  BIGSERIAL PRIMARY KEY,

    -- FK nullable: ver comentario de arriba. ON DELETE SET NULL para
    -- que si en el futuro se borra/fusiona un inmueble canónico, la
    -- publicación no se pierda (queda "huérfana" y se puede re-matchear).
    inmueble_id         BIGINT REFERENCES inmuebles(id) ON DELETE SET NULL,

    fuente              TEXT NOT NULL,          -- 'mercadolibre' | 'zonaprop' | 'argenprop' | ...
    id_fuente           TEXT NOT NULL,          -- ID original en el portal
    url                 TEXT NOT NULL,

    titulo              TEXT NOT NULL,
    tipo_operacion      TEXT NOT NULL DEFAULT 'venta',
    tipo_propiedad      TEXT,                   -- departamento | casa | terreno | ph | local...
    precio              NUMERIC(14, 2),
    moneda              TEXT,                   -- 'USD' | 'ARS'

    -- Estos campos son necesarios acá (no solo en `inmuebles`) porque
    -- services/deduplicator.py necesita leer ubicación/m²/ambientes de
    -- CADA publicación individual (todavía sin inmueble_id asignado)
    -- para poder compararla contra otras. Antes de este fix estos
    -- datos se extraían en el scraper pero nunca llegaban a guardarse
    -- acá, y se perdían.
    provincia               TEXT NOT NULL DEFAULT 'Mendoza',
    departamento             TEXT,
    barrio                   TEXT,
    direccion                TEXT,
    latitud                  DOUBLE PRECISION,
    longitud                 DOUBLE PRECISION,
    superficie_cubierta_m2   NUMERIC(10, 2),
    superficie_total_m2      NUMERIC(10, 2),
    ambientes                SMALLINT,
    dormitorios              SMALLINT,
    banios                   SMALLINT,
    cochera                  BOOLEAN,

    fotos               JSONB NOT NULL DEFAULT '[]'::jsonb,
    foto_portada        TEXT,

    fecha_extraccion    TIMESTAMPTZ NOT NULL,

    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado_en      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Restricción clave de esta fase: si el scraper vuelve a traer la
    -- misma publicación (mismo portal + mismo id_fuente), no se
    -- duplica: se actualiza (ver repository.py -> ON CONFLICT DO UPDATE).
    UNIQUE (fuente, id_fuente)
);

CREATE INDEX IF NOT EXISTS idx_publicaciones_inmueble ON publicaciones (inmueble_id);
CREATE INDEX IF NOT EXISTS idx_publicaciones_fuente ON publicaciones (fuente);


-- ---------------------------------------------------------------------
-- Trigger genérico para mantener 'actualizado_en' al día en cada UPDATE,
-- sin tener que acordarse de setearlo a mano en cada UPSERT.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_actualizado_en()
RETURNS TRIGGER AS $$
BEGIN
    NEW.actualizado_en = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_inmuebles_actualizado_en ON inmuebles;
CREATE TRIGGER trg_inmuebles_actualizado_en
    BEFORE UPDATE ON inmuebles
    FOR EACH ROW EXECUTE FUNCTION set_actualizado_en();

DROP TRIGGER IF EXISTS trg_publicaciones_actualizado_en ON publicaciones;
CREATE TRIGGER trg_publicaciones_actualizado_en
    BEFORE UPDATE ON publicaciones
    FOR EACH ROW EXECUTE FUNCTION set_actualizado_en();

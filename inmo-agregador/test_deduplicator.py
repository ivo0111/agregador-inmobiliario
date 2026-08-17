"""
test_deduplicator.py
----------------------
Script de prueba para el motor de deduplicación (Fase 3).

Inserta publicaciones de prueba deliberadamente duplicadas
en la base de datos, ejecuta el DeduplicatorEngine y verifica
que se agruparon correctamente.

Requisitos:
    - PostgreSQL corriendo (configurado en .env)
    - Esquema aplicado (python init_db.py)

Uso:
    python test_deduplicator.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.connection import obtener_conexion
from db.repository import crear_esquema
from services.deduplicator import DeduplicatorEngine


def limpiar_datos_test(conn):
    """Elimina datos de prueba de las tablas."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM publicaciones WHERE fuente = 'test'")
        cur.execute("DELETE FROM inmuebles WHERE titulo_representativo LIKE 'Test%'")
    conn.commit()


def insertar_publicaciones_test(conn):
    """
    Inserta 6 publicaciones de prueba:
    - Pub 1 y Pub 2: mismo inmueble (departamento Godoy Cruz, 2 dorm, 70m2)
      con precios ligeramente distintos (variación < 5%).
    - Pub 3 y Pub 4: mismo inmueble (casa Luján de Cuyo, 3 dorm, 120m2)
      con precios distintos.
    - Pub 5: inmueble único (departamento Capital, 1 dorm, 45m2).
    - Pub 6: duplicado de Pub 5 con variación de precio < 5%.
    """
    publicaciones = [
        # Par 1: mismo inmueble, precios ligeramente distintos
        {
            "fuente": "test",
            "id_fuente": "TEST001",
            "url": "https://inmuebles.mercadolibre.com.ar/test-1",
            "titulo": "Departamento en venta Godoy Cruz",
            "tipo_operacion": "venta",
            "precio": 100000.0,
            "moneda": "USD",
            "provincia": "Mendoza",
            "departamento": "Godoy Cruz",
            "barrio": "Villa del Parque",
            "direccion": "Calle Falsa 123",
            "latitud": -32.45,
            "longitud": -68.95,
            "superficie_cubierta_m2": 70.0,
            "superficie_total_m2": 70.0,
            "ambientes": 2,
            "dormitorios": 2,
            "banios": 1,
            "cochera": False,
            "fotos": [],
            "foto_portada": None,
            "fecha_extraccion": "2026-01-01T00:00:00+00:00",
        },
        {
            "fuente": "test",
            "id_fuente": "TEST002",
            "url": "https://inmuebles.mercadolibre.com.ar/test-2",
            "titulo": "Departamento Godoy Cruz 70m2",
            "tipo_operacion": "venta",
            "precio": 103000.0,  # 3% más alto, dentro del 5%
            "moneda": "USD",
            "provincia": "Mendoza",
            "departamento": "Godoy Cruz",
            "barrio": "Villa del Parque",
            "direccion": "Calle Falsa 123",
            "latitud": -32.45,
            "longitud": -68.95,
            "superficie_cubierta_m2": 70.0,
            "superficie_total_m2": 70.0,
            "ambientes": 2,
            "dormitorios": 2,
            "banios": 1,
            "cochera": False,
            "fotos": [],
            "foto_portada": None,
            "fecha_extraccion": "2026-01-02T00:00:00+00:00",
        },
        # Par 2: mismo inmueble, precios distintos
        {
            "fuente": "test",
            "id_fuente": "TEST003",
            "url": "https://inmuebles.mercadolibre.com.ar/test-3",
            "titulo": "Casa en Luján de Cuyo",
            "tipo_operacion": "venta",
            "precio": 200000.0,
            "moneda": "USD",
            "provincia": "Mendoza",
            "departamento": "Luján de Cuyo",
            "barrio": "Chacras de Coria",
            "direccion": "Avida Siempre Viva 456",
            "latitud": -32.55,
            "longitud": -68.80,
            "superficie_cubierta_m2": 120.0,
            "superficie_total_m2": 150.0,
            "ambientes": 3,
            "dormitorios": 3,
            "banios": 2,
            "cochera": True,
            "fotos": [],
            "foto_portada": None,
            "fecha_extraccion": "2026-01-03T00:00:00+00:00",
        },
        {
            "fuente": "test",
            "id_fuente": "TEST004",
            "url": "https://inmuebles.mercadolibre.com.ar/test-4",
            "titulo": "Casa Luján de Cuyo Chacras",
            "tipo_operacion": "venta",
            "precio": 195000.0,  # 2.5% menos, dentro del 5%
            "moneda": "USD",
            "provincia": "Mendoza",
            "departamento": "Luján de Cuyo",
            "barrio": "Chacras de Coria",
            "direccion": "Avida Siempre Viva 456",
            "latitud": -32.55,
            "longitud": -68.80,
            "superficie_cubierta_m2": 120.0,
            "superficie_total_m2": 150.0,
            "ambientes": 3,
            "dormitorios": 3,
            "banios": 2,
            "cochera": True,
            "fotos": [],
            "foto_portada": None,
            "fecha_extraccion": "2026-01-04T00:00:00+00:00",
        },
        # Pub 5: inmueble único
        {
            "fuente": "test",
            "id_fuente": "TEST005",
            "url": "https://inmuebles.mercadolibre.com.ar/test-5",
            "titulo": "Departamento Capital 45m2",
            "tipo_operacion": "venta",
            "precio": 50000.0,
            "moneda": "USD",
            "provincia": "Mendoza",
            "departamento": "Capital",
            "barrio": "Centro",
            "direccion": "Peatonal Sarmiento 789",
            "latitud": -32.88,
            "longitud": -68.84,
            "superficie_cubierta_m2": 45.0,
            "superficie_total_m2": 45.0,
            "ambientes": 1,
            "dormitorios": 1,
            "banios": 1,
            "cochera": False,
            "fotos": [],
            "foto_portada": None,
            "fecha_extraccion": "2026-01-05T00:00:00+00:00",
        },
        # Pub 6: duplicado de Pub 5, precio ligeramente distinto
        {
            "fuente": "test",
            "id_fuente": "TEST006",
            "url": "https://inmuebles.mercadolibre.com.ar/test-6",
            "titulo": "Departamento Centro Mendoza 45m²",
            "tipo_operacion": "venta",
            "precio": 52000.0,  # 4% más, dentro del 5%
            "moneda": "USD",
            "provincia": "Mendoza",
            "departamento": "Capital",
            "barrio": "Centro",
            "direccion": "Peatonal Sarmiento 789",
            "latitud": -32.88,
            "longitud": -68.84,
            "superficie_cubierta_m2": 45.0,
            "superficie_total_m2": 45.0,
            "ambientes": 1,
            "dormitorios": 1,
            "banios": 1,
            "cochera": False,
            "fotos": [],
            "foto_portada": None,
            "fecha_extraccion": "2026-01-06T00:00:00+00:00",
        },
    ]

    with conn.cursor() as cur:
        for pub in publicaciones:
            cur.execute(
                """
                INSERT INTO publicaciones (
                    inmueble_id, fuente, id_fuente, url, titulo, tipo_operacion,
                    precio, moneda, fotos, foto_portada, fecha_extraccion,
                    provincia, departamento, barrio, direccion, latitud, longitud,
                    superficie_cubierta_m2, superficie_total_m2,
                    ambientes, dormitorios, banios, cochera
                ) VALUES (
                    NULL, %(fuente)s, %(id_fuente)s, %(url)s, %(titulo)s,
                    %(tipo_operacion)s, %(precio)s, %(moneda)s,
                    %(fotos)s, %(foto_portada)s, %(fecha_extraccion)s,
                    %(provincia)s, %(departamento)s, %(barrio)s, %(direccion)s,
                    %(latitud)s, %(longitud)s, %(superficie_cubierta_m2)s,
                    %(superficie_total_m2)s, %(ambientes)s, %(dormitorios)s,
                    %(banios)s, %(cochera)s
                )
                """,
                pub,
            )
    conn.commit()
    return len(publicaciones)


def verificar_resultados(conn):
    """
    Verifica que la deduplicación produjo los resultados esperados:
    - 3 inmuebles canónicos (uno para cada par + uno único)
    - 6 publicaciones con inmueble_id asignado
    - Pub TEST001 y TEST002 comparten el mismo inmueble_id
    - Pub TEST003 y TEST004 comparten el mismo inmueble_id
    - Pub TEST005 y TEST006 comparten el mismo inmueble_id
    """
    with conn.cursor() as cur:
        # Contar inmuebles creados por el test
        cur.execute(
            "SELECT COUNT(*) FROM inmuebles WHERE titulo_representativo LIKE 'Test%'"
        )
        inmuebles_test = cur.fetchone()[0]

        # Contar publicaciones con inmueble_id asignado
        cur.execute(
            "SELECT COUNT(*) FROM publicaciones WHERE fuente = 'test' AND inmueble_id IS NOT NULL"
        )
        pub_asignadas = cur.fetchone()[0]

        # Verificar agrupación: TEST001 y TEST002 mismo inmueble
        cur.execute(
            """
            SELECT p1.inmueble_id = p2.inmueble_id
            FROM publicaciones p1
            JOIN publicaciones p2 ON p1.inmueble_id = p2.inmueble_id
            WHERE p1.id_fuente = 'TEST001' AND p2.id_fuente = 'TEST002'
            AND p1.inmueble_id IS NOT NULL
            """
        )
        par1_juntos = cur.fetchone()
        par1_mismo = par1_juntos[0] if par1_juntos else False

        # Verificar agrupación: TEST003 y TEST004 mismo inmueble
        cur.execute(
            """
            SELECT p1.inmueble_id = p2.inmueble_id
            FROM publicaciones p1
            JOIN publicaciones p2 ON p1.inmueble_id = p2.inmueble_id
            WHERE p1.id_fuente = 'TEST003' AND p2.id_fuente = 'TEST004'
            AND p1.inmueble_id IS NOT NULL
            """
        )
        par2_juntos = cur.fetchone()
        par2_mismo = par2_juntos[0] if par2_juntos else False

        # Verificar agrupación: TEST005 y TEST006 mismo inmueble
        cur.execute(
            """
            SELECT p1.inmueble_id = p2.inmueble_id
            FROM publicaciones p1
            JOIN publicaciones p2 ON p1.inmueble_id = p2.inmueble_id
            WHERE p1.id_fuente = 'TEST005' AND p2.id_fuente = 'TEST006'
            AND p1.inmueble_id IS NOT NULL
            """
        )
        par3_juntos = cur.fetchone()
        par3_mismo = par3_juntos[0] if par3_juntos else False

    print(f"  Inmuebles de test creados: {inmuebles_test}")
    print(f"  Publicaciones asignadas: {pub_asignadas}")
    print(f"  Par 1 (TEST001/TEST002) mismo inmueble: {par1_mismo}")
    print(f"  Par 2 (TEST003/TEST004) mismo inmueble: {par2_mismo}")
    print(f"  Par 3 (TEST005/TEST006) mismo inmueble: {par3_mismo}")

    assert inmuebles_test == 3, f"Se esperaban 3 inmuebles, se encontraron {inmuebles_test}"
    assert pub_asignadas == 6, f"Se esperaban 6 publicaciones asignadas, se encontraron {pub_asignadas}"
    assert par1_mismo, "TEST001 y TEST002 deberían compartir inmueble_id"
    assert par2_mismo, "TEST003 y TEST004 deberían compartir inmueble_id"
    assert par3_mismo, "TEST005 y TEST006 deberían compartir inmueble_id"


def main():
    print("=" * 60)
    print("TEST DE DEDUPLICACIÓN — Fase 3")
    print("=" * 60)

    conn = obtener_conexion()

    try:
        # Asegurar que el esquema existe
        crear_esquema(conn)

        # Limpiar datos de tests anteriores
        limpiar_datos_test(conn)

        # Insertar publicaciones de prueba
        count = insertar_publicaciones_test(conn)
        print(f"\n📝 Insertadas {count} publicaciones de prueba (inmueble_id = NULL)")

        # Ejecutar deduplicación
        print("\n🔗 Ejecutando DeduplicatorEngine...")
        dedup = DeduplicatorEngine(conn)
        resultado = dedup.ejecutar()

        print(f"\n📊 Resultado de deduplicación:")
        print(f"   Publicaciones asignadas: {resultado.publicaciones_asignadas}")
        print(f"   Inmuebles creados: {resultado.inmuebles_creados}")
        print(f"   Inmuebles reutilizados: {resultado.inmuebles_reutilizados}")
        print(f"   Errores: {resultado.errores}")

        # Verificar resultados
        print("\n🔍 Verificando resultados...")
        verificar_resultados(conn)

        print("\n✅ Todos los tests de deduplicación pasaron.")

    except Exception as exc:
        conn.rollback()
        print(f"\n❌ Error en test: {exc}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
"""
init_db.py
----------
Corre una sola vez (o las veces que quieras, es idempotente) para crear
las tablas en la base de datos apuntada por .env.

Uso:
    python init_db.py
"""

from config import get_logger
from db.connection import obtener_conexion
from db.repository import crear_esquema

logger = get_logger("init_db")


def main():
    logger.info("Conectando a la base de datos...")
    with obtener_conexion() as conn:
        crear_esquema(conn)
    print("✅ Esquema creado/verificado correctamente.")


if __name__ == "__main__":
    main()

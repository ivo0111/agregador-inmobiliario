"""
db/connection.py
-----------------
Manejo de conexión a PostgreSQL. Las credenciales NUNCA se hardcodean:
se leen desde variables de entorno (archivo .env, cargado con
python-dotenv). Esto evita el clásico error de subir contraseñas al
repositorio.
"""

import os

import psycopg
from dotenv import load_dotenv

from config import get_logger

logger = get_logger("db.connection")

load_dotenv()  # busca un archivo .env en el directorio del proyecto

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "inmo_agregador")
DB_USER = os.getenv("DB_USER", "inmo_user")
DB_PASSWORD = os.getenv("DB_PASSWORD")

if not DB_PASSWORD:
    logger.warning(
        "DB_PASSWORD no está seteada. Copiá .env.example a .env y "
        "completá las credenciales antes de conectar a la base."
    )


def obtener_conninfo() -> str:
    """Arma el string de conexión que espera psycopg."""
    return (
        f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} "
        f"user={DB_USER} password={DB_PASSWORD}"
    )


def obtener_conexion() -> psycopg.Connection:
    """
    Abre una nueva conexión a PostgreSQL. El caller es responsable de
    cerrarla (usar como context manager: `with obtener_conexion() as conn:`).

    Para un scraper batch (no un servidor web), una conexión por
    ejecución alcanza y sobra — no hace falta un pool acá.
    """
    return psycopg.connect(obtener_conninfo())

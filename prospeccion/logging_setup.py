"""Configuración de logging: fichero por ejecución + consola.

Regla del proyecto: no silenciar excepciones. Cada error se registra con
contexto. Este módulo solo configura los handlers.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

LOG_DIR = Path("logs")


def configurar_logging(nivel: int = logging.INFO) -> logging.Logger:
    """Configura el logger raíz del pipeline.

    Escribe a logs/run_YYYY-MM-DD.log (append) y a stderr. Devuelve el logger
    'prospeccion' ya configurado. Idempotente: no duplica handlers si se llama
    más de una vez en el mismo proceso.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fichero = LOG_DIR / f"run_{date.today().isoformat()}.log"

    logger = logging.getLogger("prospeccion")
    logger.setLevel(nivel)
    logger.propagate = False

    # Evita handlers duplicados si se reconfigura.
    ya_tiene = {getattr(h, "_prospeccion_tag", None) for h in logger.handlers}

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    if "file" not in ya_tiene:
        fh = logging.FileHandler(fichero, encoding="utf-8")
        fh.setFormatter(fmt)
        fh._prospeccion_tag = "file"  # type: ignore[attr-defined]
        logger.addHandler(fh)

    if "console" not in ya_tiene:
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        ch._prospeccion_tag = "console"  # type: ignore[attr-defined]
        logger.addHandler(ch)

    return logger

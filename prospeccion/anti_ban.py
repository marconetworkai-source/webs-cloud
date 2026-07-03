"""Ritmo anti-baneo: pausas aleatorias centralizadas.

La velocidad es el ÚLTIMO criterio. Estas pausas son obligatorias y no deben
recortarse. Todos los rangos vienen del brief:

  - entre fichas de detalle:      5-10 s
  - entre combinaciones nicho×ciudad: 30-60 s
  - entre lotes de 20:            5 min (300 s)
  - scroll del panel de resultados:  2-4 s
  - entre búsquedas de DuckDuckGo:   3-5 s
"""

from __future__ import annotations

import logging
import random
import time

logger = logging.getLogger("prospeccion")

# Rangos (segundos). Centralizados para no dispersar números mágicos.
FICHA = (5.0, 10.0)
COMBINACION = (30.0, 60.0)
LOTE = (300.0, 300.0)      # 5 min fijos
SCROLL = (2.0, 4.0)
DUCKDUCKGO = (3.0, 5.0)
BLOQUEO = (1800.0, 1800.0)  # 30 min fijos


def dormir(rango: tuple[float, float], motivo: str = "") -> float:
    """Duerme un tiempo aleatorio uniforme dentro de `rango`. Devuelve los
    segundos dormidos. Registra el motivo para trazabilidad."""
    segundos = random.uniform(*rango)
    if motivo:
        logger.debug("Pausa %.1fs (%s)", segundos, motivo)
    time.sleep(segundos)
    return segundos

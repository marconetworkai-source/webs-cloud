"""Fase 3 — Puntuación 1-5.

Fórmula (del brief):
  base 3
  +1 si tiene Instagram o Facebook
  +1 si el nicho es Clínica estética, Dental o Fisioterapia
  -1 si tiene menos de 10 reseñas
  resultado acotado a [1, 5]
"""

from __future__ import annotations

NICHOS_ALTO_VALOR = {"Clínica estética", "Dental", "Fisioterapia"}


def calcular_puntuacion(
    *,
    nicho: str,
    resenas: int | None,
    tiene_red_social: bool,
) -> int:
    """Devuelve la puntuación entera acotada a [1, 5]."""
    score = 3
    if tiene_red_social:
        score += 1
    if nicho in NICHOS_ALTO_VALOR:
        score += 1
    # 'menos de 10 reseñas': None (desconocido) se trata como < 10 por prudencia.
    if resenas is None or resenas < 10:
        score -= 1
    return max(1, min(5, score))

"""Tests de la lógica del scraper que NO necesita un navegador real.

Se prueban con una sesión y respuestas simuladas: la detección de estructura de
ficha (distinguir 'sin teléfono' de 'bloqueado') y que un fallo de fetch active
el protocolo de bloqueo en vez de reventar el run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prospeccion.maps_scraper import BloqueoDetectado, MapsScraper  # noqa: E402
from prospeccion.models import RawCard  # noqa: E402


class _FakeEl:
    def __init__(self, attrib=None):
        self.attrib = attrib or {}

    def get_all_text(self, strip=True):
        return ""


class _FakeResp:
    """Respuesta simulada: css(sel) devuelve elementos según un mapa selector->lista."""

    def __init__(self, por_selector=None, url="https://www.google.com/maps/place/x",
                 status=200, html=""):
        self._map = por_selector or {}
        self.url = url
        self.status = status
        self.html_content = html

    def css(self, sel, adaptive=False, auto_save=False):
        return self._map.get(sel, [])


def _scraper_sin_navegador():
    """MapsScraper sin abrir navegador real (no llamamos a __enter__)."""
    return MapsScraper(visible=False)


# ------------------------------------------------------------ estructura ficha
def test_estructura_true_con_telefono():
    assert MapsScraper._ficha_tiene_estructura(_FakeResp(), "+34963111222") is True


def test_estructura_true_con_h1_sin_telefono():
    resp = _FakeResp({"h1": [_FakeEl()]})
    assert MapsScraper._ficha_tiene_estructura(resp, None) is True


def test_estructura_false_pagina_vacia():
    assert MapsScraper._ficha_tiene_estructura(_FakeResp(), None) is False


# ------------------------------------------------------ fetch falla -> bloqueo
class _SesionQueRevienta:
    def fetch(self, url, **kwargs):
        raise TimeoutError("feed nunca apareció")


def test_buscar_fetch_falla_lanza_bloqueo():
    s = _scraper_sin_navegador()
    s._session = _SesionQueRevienta()
    with pytest.raises(BloqueoDetectado):
        s.buscar("Fontanero", "Valencia")


def test_abrir_ficha_fetch_falla_cuenta_para_bloqueo():
    s = _scraper_sin_navegador()
    s._session = _SesionQueRevienta()
    card = RawCard(nombre="X", nota_google=None, resenas=None, tiene_web=False,
                   place_url="https://www.google.com/maps/place/x")
    # dos fallos: devuelven None sin lanzar
    assert s.abrir_ficha(card, "Fontanero", "Valencia") is None
    assert s.abrir_ficha(card, "Fontanero", "Valencia") is None
    # al tercero, protocolo de bloqueo
    with pytest.raises(BloqueoDetectado):
        s.abrir_ficha(card, "Fontanero", "Valencia")


def test_abrir_ficha_sin_place_url_cuenta_fallo():
    s = _scraper_sin_navegador()
    s._session = _SesionQueRevienta()   # no se usa; no hay place_url
    card = RawCard(nombre="X", nota_google=None, resenas=None, tiene_web=False,
                   place_url=None)
    assert s.abrir_ficha(card, "Fontanero", "Valencia") is None
    assert s._fallos_consecutivos == 1

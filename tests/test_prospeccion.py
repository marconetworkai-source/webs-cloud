"""Tests del pipeline de prospección.

Cubre la lógica que NO necesita red (que es donde viven las garantías de
'cero datos falsos' y 'cero duplicados') y ejercita la orquestación completa
con un scraper y un DuckDuckGo simulados.

Ejecutar:
    pip install pytest
    pytest -q

Las pausas anti-baneo se anulan (monkeypatch) para que los tests sean rápidos;
NO se toca la lógica que se prueba.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prospeccion import anti_ban  # noqa: E402
from prospeccion.checkpoint import Checkpoint  # noqa: E402
from prospeccion.config import Config  # noqa: E402
from prospeccion.models import Candidato, RawCard  # noqa: E402
from prospeccion.pipeline import Pipeline, construir_combinaciones  # noqa: E402
from prospeccion.scoring import calcular_puntuacion  # noqa: E402
from prospeccion.verify import (  # noqa: E402
    confirmar_sin_web,
    normalizar_telefono,
)


# --------------------------------------------------------------------------
# Fase 2 — normalización de teléfono
# --------------------------------------------------------------------------
@pytest.mark.parametrize("entrada,esperado", [
    ("+34 963 12 34 56", "+34963123456"),
    ("0034963123456", "+34963123456"),
    ("34963123456", "+34963123456"),
    ("963123456", "+34963123456"),
    ("tel:+34 600 111 222", "+34600111222"),
    ("600-111-222", "+34600111222"),
    ("(+34) 711 222 333", "+34711222333"),
    ("812345678", "+34812345678"),
])
def test_normalizar_telefono_validos(entrada, esperado):
    assert normalizar_telefono(entrada) == esperado


@pytest.mark.parametrize("entrada", [
    None, "", "123", "12345678",          # muy corto
    "512345678",                          # empieza por 5 (inválido)
    "112345678",                          # empieza por 1
    "+34 12 34",                          # incompleto
    "0000000000000",                      # basura
    "+33 6 12 34 56 78",                  # francés, no español
])
def test_normalizar_telefono_invalidos(entrada):
    assert normalizar_telefono(entrada) is None


# --------------------------------------------------------------------------
# Fase 3 — puntuación
# --------------------------------------------------------------------------
def test_puntuacion_base():
    # base 3, >=10 reseñas, sin red, nicho normal -> 3
    assert calcular_puntuacion(nicho="Fontanero", resenas=50, tiene_red_social=False) == 3


def test_puntuacion_maxima_acotada():
    # 3 +1 red +1 nicho alto valor = 5 (no supera 5)
    assert calcular_puntuacion(nicho="Dental", resenas=100, tiene_red_social=True) == 5


def test_puntuacion_minima_acotada():
    # 3 -1 pocas reseñas = 2; sin red ni nicho premium
    assert calcular_puntuacion(nicho="Pintor", resenas=3, tiene_red_social=False) == 2


def test_puntuacion_resenas_none_penaliza():
    # None se trata como <10 -> penaliza
    assert calcular_puntuacion(nicho="Pintor", resenas=None, tiene_red_social=False) == 2


def test_puntuacion_nicho_premium_pocas_resenas():
    # 3 +1 nicho -1 pocas reseñas = 3
    assert calcular_puntuacion(nicho="Fisioterapia", resenas=2, tiene_red_social=False) == 3


# --------------------------------------------------------------------------
# Fase 2 — confirmación 'sin web' vía DDG (con fetcher simulado)
# --------------------------------------------------------------------------
class _FakeResp:
    def __init__(self, html):
        self.html_content = html
        self.status = 200
        self.url = "https://html.duckduckgo.com/html/"


def _ddg(html):
    return lambda url: _FakeResp(html)


def test_ddg_detecta_web_propia():
    html = '''
      <a class="result__a" href="https://fontaneriagomez.es/servicios">Fontanería Gómez</a>
      <a class="result__a" href="https://paginasamarillas.es/x">PA</a>
    '''
    r = confirmar_sin_web("Fontanería Gómez", "Valencia", _ddg(html))
    assert r.tiene_web_propia is True
    assert r.dominio_detectado == "fontaneriagomez.es"


def test_ddg_solo_agregadores_no_descarta():
    html = '''
      <a class="result__a" href="https://www.paginasamarillas.es/x">PA</a>
      <a class="result__a" href="https://www.facebook.com/fontygomez">FB</a>
      <a class="result__a" href="https://www.instagram.com/fontygomez">IG</a>
    '''
    r = confirmar_sin_web("Fontanería Gómez", "Valencia", _ddg(html))
    assert r.tiene_web_propia is False
    assert r.facebook and "facebook.com" in r.facebook
    assert r.instagram and "instagram.com" in r.instagram


def test_ddg_coincidencia_generica_conserva_con_duda():
    # 'dental' es genérico del nicho: dentalexpress.es NO debe descartar a
    # 'Clínica Dental Sonrisa' (nombre parcialmente coincidente -> conservar + duda).
    html = '<a class="result__a" href="https://dentalexpress.es/precios">x</a>'
    r = confirmar_sin_web("Clínica Dental Sonrisa", "Madrid", _ddg(html))
    assert r.tiene_web_propia is False
    assert any("posible_web_no_confirmada" in d for d in r.dudas)


def test_ddg_coincidencia_distintiva_si_descarta():
    # 'sonrisa' es token distintivo: clinicasonrisa.es SÍ es su web -> descartar.
    html = '<a class="result__a" href="https://clinicasonrisa.es/">x</a>'
    r = confirmar_sin_web("Clínica Dental Sonrisa", "Madrid", _ddg(html))
    assert r.tiene_web_propia is True
    assert r.dominio_detectado == "clinicasonrisa.es"


def test_ddg_dominio_ambiguo_conserva_con_duda():
    # dominio no-agregador sin relación de nombre -> se conserva, con duda anotada
    html = '''
      <a class="result__a" href="https://reformaslevante.com/blog">otro</a>
    '''
    r = confirmar_sin_web("Fontanería Gómez", "Valencia", _ddg(html))
    assert r.tiene_web_propia is False
    assert any("dominio_ambiguo" in d for d in r.dudas)


def test_ddg_desenvuelve_redirect():
    # DDG envuelve el destino en /l/?uddg=<url-encoded>
    html = (
        '<a class="result__a" '
        'href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fclinicadentalsonrisa.es%2F">x</a>'
    )
    r = confirmar_sin_web("Clínica Dental Sonrisa", "Madrid", _ddg(html))
    assert r.tiene_web_propia is True
    assert r.dominio_detectado == "clinicadentalsonrisa.es"


# --------------------------------------------------------------------------
# Orquestación completa (scraper + DDG simulados, dry-run)
# --------------------------------------------------------------------------
def _config():
    field_ids = {n: f"fld{n[:12]:_<14}" for n in [
        "Negocio", "Teléfono", "Ciudad", "Nicho", "Reseñas",
        "Nota Google", "Estado", "Google Maps URL", "Notas", "Puntuación",
    ]}
    return Config(
        base_id="appTEST", leads_table_id="tblTEST", field_ids=field_ids,
        ciudades=["Valencia", "Madrid"], nichos=["Fontanero", "Dental"],
    )


class FakeScraper:
    """Simula MapsScraper: devuelve tarjetas y fichas predefinidas por combinación."""

    def __init__(self, datos, bloquea_en=None):
        # datos: dict[(ciudad,nicho)] -> list[(RawCard, Candidato|None)]
        self.datos = datos
        self.bloquea_en = bloquea_en or []   # lista de (ciudad,nicho) que lanzan bloqueo una vez
        self._bloqueos_lanzados = set()
        self._cola = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def buscar(self, nicho, ciudad):
        from prospeccion.maps_scraper import BloqueoDetectado
        clave = (ciudad, nicho)
        if clave in self.bloquea_en and clave not in self._bloqueos_lanzados:
            self._bloqueos_lanzados.add(clave)
            raise BloqueoDetectado(f"bloqueo simulado en {clave}")
        pares = self.datos.get(clave, [])
        self._cola[clave] = list(pares)
        return [card for card, _ in pares]

    def abrir_ficha(self, card, nicho, ciudad):
        clave = (ciudad, nicho)
        for c, cand in self.datos.get(clave, []):
            if c is card:
                return cand
        return None


@pytest.fixture(autouse=True)
def _sin_pausas(monkeypatch):
    monkeypatch.setattr(anti_ban, "dormir", lambda *a, **k: 0.0)


@pytest.fixture(autouse=True)
def _estado_temporal(monkeypatch, tmp_path):
    # Aísla checkpoint/seen en un directorio temporal.
    import prospeccion.checkpoint as cp
    monkeypatch.setattr(cp, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cp, "CHECKPOINT_PATH", tmp_path / "state" / "checkpoint.json")
    monkeypatch.setattr(cp, "SEEN_PHONES_PATH", tmp_path / "state" / "seen.json")
    import prospeccion.pipeline as pl
    monkeypatch.setattr(pl, "RESUMEN_DIR", tmp_path / "logs")


def _card(nombre, web=False, place="https://www.google.com/maps/place/x"):
    return RawCard(nombre=nombre, nota_google=4.5, resenas=20,
                   tiene_web=web, place_url=place)


def _cand(nombre, tel, ciudad="Valencia", nicho="Fontanero", resenas=20):
    return Candidato(nombre=nombre, ciudad=ciudad, nicho=nicho, nota_google=4.5,
                     resenas=resenas, telefono_raw=tel,
                     maps_url="https://www.google.com/maps/place/x")


def test_pipeline_dry_run_reconciliacion():
    """Vistos = guardados + descartados, con mezcla de casos."""
    c_ok = _card("Fontanería Buena")             # sin web, tel válido -> guardado
    c_web = _card("Fontanería ConWeb", web=True)  # web en tarjeta -> descarte con_web
    c_notel = _card("Fontanería SinTel")          # sin teléfono válido -> descarte
    datos = {
        ("Valencia", "Fontanero"): [
            (c_ok, _cand("Fontanería Buena", "+34 963 111 222")),
            (c_web, _cand("Fontanería ConWeb", "+34 963 333 444")),
            (c_notel, _cand("Fontanería SinTel", "12345")),
        ],
    }
    scraper = FakeScraper(datos)
    ddg = _ddg('<a class="result__a" href="https://facebook.com/x">FB</a>')
    pipe = Pipeline(_config(), cliente=None, checkpoint=Checkpoint.cargar(),
                    quota=80, lote=20, ciudad="Valencia", nicho="Fontanero",
                    dry_run=True, ddg_get=ddg, scraper=scraper)
    r = pipe.ejecutar()

    assert r.vistos == 3
    assert r.guardados == 1
    assert r.descartados["con_web"] == 1
    assert r.descartados["sin_telefono"] == 1
    assert r.cuadra()


def test_pipeline_descarta_web_confirmada_por_ddg():
    c = _card("Clínica Dental Sonrisa")
    datos = {("Valencia", "Fontanero"): [
        (c, _cand("Clínica Dental Sonrisa", "+34 963 111 222")),
    ]}
    scraper = FakeScraper(datos)
    # DDG revela dominio propio -> descarte con_web
    ddg = _ddg('<a class="result__a" href="https://clinicadentalsonrisa.es/">x</a>')
    pipe = Pipeline(_config(), cliente=None, checkpoint=Checkpoint.cargar(),
                    quota=80, lote=20, ciudad="Valencia", nicho="Fontanero",
                    dry_run=True, ddg_get=ddg, scraper=scraper)
    r = pipe.ejecutar()
    assert r.guardados == 0
    assert r.descartados["con_web"] == 1
    assert r.cuadra()


def test_pipeline_dedup_local():
    """Un teléfono ya visto se descarta como duplicado."""
    cp = Checkpoint.cargar()
    cp.marcar_visto("+34963111222")
    c = _card("Fontanería Repetida")
    datos = {("Valencia", "Fontanero"): [
        (c, _cand("Fontanería Repetida", "+34 963 111 222")),
    ]}
    scraper = FakeScraper(datos)
    ddg = _ddg("<html></html>")
    pipe = Pipeline(_config(), cliente=None, checkpoint=cp,
                    quota=80, lote=20, ciudad="Valencia", nicho="Fontanero",
                    dry_run=True, ddg_get=ddg, scraper=scraper)
    r = pipe.ejecutar()
    assert r.guardados == 0
    assert r.descartados["duplicado"] == 1
    assert r.cuadra()


def test_pipeline_respeta_cuota():
    """Con quota=2 solo se guardan 2 aunque haya más candidatos."""
    datos = {("Valencia", "Fontanero"): [
        (_card(f"Neg {i}"), _cand(f"Neg {i}", f"+3496311100{i}"))
        for i in range(5)
    ]}
    scraper = FakeScraper(datos)
    ddg = _ddg("<html></html>")
    pipe = Pipeline(_config(), cliente=None, checkpoint=Checkpoint.cargar(),
                    quota=2, lote=20, ciudad="Valencia", nicho="Fontanero",
                    dry_run=True, ddg_get=ddg, scraper=scraper)
    r = pipe.ejecutar()
    assert r.guardados == 2
    # las tarjetas no procesadas por la cuota NO cuentan como vistas -> cuadra
    assert r.vistos == 2
    assert r.cuadra()


def test_pipeline_protocolo_bloqueo_reintenta_una_vez():
    """Un bloqueo en la 1ª combinación: se reintenta una vez y luego procede."""
    c = _card("Fontanería Tras Bloqueo")
    datos = {("Valencia", "Fontanero"): [
        (c, _cand("Fontanería Tras Bloqueo", "+34 963 111 222")),
    ]}
    # bloquea la primera vez que se busca esa combinación; al reintentar, funciona
    scraper = FakeScraper(datos, bloquea_en=[("Valencia", "Fontanero")])
    ddg = _ddg("<html></html>")
    pipe = Pipeline(_config(), cliente=None, checkpoint=Checkpoint.cargar(),
                    quota=80, lote=20, ciudad="Valencia", nicho="Fontanero",
                    dry_run=True, ddg_get=ddg, scraper=scraper)
    r = pipe.ejecutar()
    assert r.bloqueos == 1
    assert r.guardados == 1        # tras el reintento, el lead se guarda
    assert r.cuadra()


def test_construir_combinaciones_orden():
    """Primera combinación del barrido = (Valencia, Fontanero)."""
    combos = construir_combinaciones(_config(), None, None)
    assert combos[0] == ("Valencia", "Fontanero")
    assert combos == [
        ("Valencia", "Fontanero"), ("Valencia", "Dental"),
        ("Madrid", "Fontanero"), ("Madrid", "Dental"),
    ]


def test_checkpoint_avanza_y_persiste(tmp_path, monkeypatch):
    cp = Checkpoint.cargar()
    assert cp.combo_index == 0
    cp.avanzar_combo()
    cp.avanzar_combo()
    cp2 = Checkpoint.cargar()
    assert cp2.combo_index == 2
    assert cp2.combos_completados == 2

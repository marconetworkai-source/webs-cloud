"""Tests del cliente Airtable con una sesión HTTP simulada.

Bloquean las garantías clave sin tocar la red:
  - upsert con merge sobre el field ID de Teléfono (cero duplicados)
  - typecast=False (no se crean opciones nuevas en desplegables)
  - Estado='Por llamar' y Notas SOLO en registros nuevos (no pisar leads trabajados)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prospeccion.airtable_client import AirtableClient  # noqa: E402
from prospeccion.models import Lead  # noqa: E402

FIELD_IDS = {
    "Negocio": "fldNegocio000001", "Teléfono": "fldTelefono00001",
    "Ciudad": "fldCiudad0000001", "Nicho": "fldNicho00000001",
    "Reseñas": "fldResenas000001", "Nota Google": "fldNota000000001",
    "Estado": "fldEstado0000001", "Google Maps URL": "fldMaps000000001",
    "Notas": "fldNotas00000001", "Puntuación": "fldPunt000000001",
}


class _FakeResp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self.ok = status < 400
        self._payload = payload or {}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


class _FakeSession:
    """Registra las peticiones y devuelve respuestas encoladas."""

    def __init__(self, respuestas):
        self.headers = {}
        self._respuestas = list(respuestas)
        self.llamadas = []

    def request(self, metodo, url, json=None, timeout=None):
        self.llamadas.append({"metodo": metodo, "url": url, "json": json})
        return self._respuestas.pop(0)


def _lead(nombre, tel):
    return Lead(negocio=nombre, telefono=tel, ciudad="Valencia", nicho="Fontanero",
                resenas=20, nota_google=4.5, maps_url="https://maps/x",
                puntuacion=4, notas=f"scrapeado: {nombre}")


def _cliente(session):
    c = AirtableClient(token="tok", base_id="appX", table_id="tblX",
                       field_ids=dict(FIELD_IDS))
    c._session = session
    return c


def test_upsert_usa_merge_por_telefono_y_typecast_false():
    upsert_resp = _FakeResp(200, {
        "records": [
            {"id": "recNEW", "fields": {"fldTelefono00001": "+34963111222"}},
        ],
        "createdRecords": ["recNEW"],
        "updatedRecords": [],
    })
    patch_resp = _FakeResp(200, {"records": [{"id": "recNEW"}]})
    session = _FakeSession([upsert_resp, patch_resp])
    cliente = _cliente(session)

    res = cliente.upsert_lote([_lead("Fontanería Nueva", "+34963111222")])

    assert res == {"creados": 1, "actualizados": 0}
    # 1ª llamada = upsert
    up = session.llamadas[0]
    assert up["metodo"] == "PATCH"
    body = up["json"]
    assert body["performUpsert"]["fieldsToMergeOn"] == ["fldTelefono00001"]
    assert body["typecast"] is False
    # el upsert NO debe fijar Estado (eso es solo para nuevos, en 2ª llamada)
    campos_upsert = body["records"][0]["fields"]
    assert "fldEstado0000001" not in campos_upsert
    assert campos_upsert["fldTelefono00001"] == "+34963111222"


def test_estado_y_notas_solo_en_registros_nuevos():
    # rec1 creado, rec2 actualizado (ya existía y estaba 'trabajado')
    upsert_resp = _FakeResp(200, {
        "records": [
            {"id": "rec1", "fields": {"fldTelefono00001": "+34963111222"}},
            {"id": "rec2", "fields": {"fldTelefono00001": "+34963333444"}},
        ],
        "createdRecords": ["rec1"],
        "updatedRecords": ["rec2"],
    })
    patch_resp = _FakeResp(200, {"records": [{"id": "rec1"}]})
    session = _FakeSession([upsert_resp, patch_resp])
    cliente = _cliente(session)

    cliente.upsert_lote([
        _lead("Nueva", "+34963111222"),
        _lead("YaExiste", "+34963333444"),
    ])

    # 2ª llamada = PATCH de inicialización SOLO para el creado (rec1)
    assert len(session.llamadas) == 2
    patch = session.llamadas[1]
    registros = patch["json"]["records"]
    ids = {r["id"] for r in registros}
    assert ids == {"rec1"}                      # rec2 (actualizado) NO se toca
    campos = registros[0]["fields"]
    assert campos["fldEstado0000001"] == "Por llamar"
    assert "fldNotas00000001" in campos


def test_upsert_trocea_en_grupos_de_10():
    # 12 leads -> 2 peticiones de upsert (10 + 2); sin creados -> sin PATCH extra
    leads = [_lead(f"N{i}", f"+3496311{i:04d}") for i in range(12)]
    r1 = _FakeResp(200, {"records": [], "createdRecords": [], "updatedRecords": []})
    r2 = _FakeResp(200, {"records": [], "createdRecords": [], "updatedRecords": []})
    session = _FakeSession([r1, r2])
    cliente = _cliente(session)
    cliente.upsert_lote(leads)
    assert len(session.llamadas) == 2
    assert len(session.llamadas[0]["json"]["records"]) == 10
    assert len(session.llamadas[1]["json"]["records"]) == 2


def test_backoff_reintenta_en_429(monkeypatch):
    import prospeccion.airtable_client as mod
    monkeypatch.setattr(mod.time, "sleep", lambda *_: None)  # sin esperas reales
    ok = _FakeResp(200, {"records": [], "createdRecords": [], "updatedRecords": []})
    session = _FakeSession([_FakeResp(429), _FakeResp(429), ok])
    cliente = _cliente(session)
    cliente.upsert_lote([_lead("N", "+34963111222")])
    # 2 reintentos + éxito = 3 llamadas
    assert len(session.llamadas) == 3

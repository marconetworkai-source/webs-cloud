"""Fase 4 — Persistencia en Airtable vía API REST.

Garantías:
  - CERO duplicados: upsert (performUpsert) con el field ID de Teléfono como
    clave de merge. Un teléfono ya existente se actualiza, no se duplica.
  - No pisar el CRM del humano: Estado y Notas SOLO se escriben en registros
    NUEVOS (createdRecords). En un lead ya trabajado (p. ej. Estado='Interesado')
    se refrescan únicamente los datos objetivos del scrapeo (reseñas, nota,
    puntuación, URL) sin resetear su Estado ni machacar sus notas.
  - Robustez: lotes de 10, <=4 req/s, reintentos con backoff exponencial ante
    429/5xx (máx 5).
"""

from __future__ import annotations

import logging
import time
from typing import Iterable, Optional

import requests

from .models import Lead

logger = logging.getLogger("prospeccion")

API_ROOT = "https://api.airtable.com/v0"
META_ROOT = f"{API_ROOT}/meta/bases"
MAX_RECORDS_POR_PETICION = 10
MIN_INTERVALO_S = 0.25          # <= 4 peticiones/segundo
MAX_REINTENTOS = 5


class AirtableError(RuntimeError):
    """Fallo no recuperable contra la API de Airtable (incluye scope faltante)."""


class AirtableClient:
    def __init__(
        self,
        token: str,
        base_id: str,
        table_id: str,
        field_ids: dict[str, str],
    ) -> None:
        self.base_id = base_id
        self.table_id = table_id
        self.field_ids = field_ids
        self._session = requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        )
        self._ultimo_request = 0.0

    # ------------------------------------------------------------------ HTTP
    def _throttle(self) -> None:
        delta = time.monotonic() - self._ultimo_request
        if delta < MIN_INTERVALO_S:
            time.sleep(MIN_INTERVALO_S - delta)
        self._ultimo_request = time.monotonic()

    def _request(self, metodo: str, url: str, payload: Optional[dict] = None) -> dict:
        """Petición con rate-limit y backoff exponencial ante 429/5xx."""
        for intento in range(1, MAX_REINTENTOS + 1):
            self._throttle()
            try:
                resp = self._session.request(metodo, url, json=payload, timeout=30)
            except requests.RequestException as exc:
                espera = 2 ** intento
                logger.warning("Red Airtable falló (%s), intento %d/%d, espero %ds",
                               exc, intento, MAX_REINTENTOS, espera)
                time.sleep(espera)
                continue

            if resp.status_code in (429, 500, 502, 503, 504):
                espera = 2 ** intento
                logger.warning("Airtable %d, intento %d/%d, espero %ds",
                               resp.status_code, intento, MAX_REINTENTOS, espera)
                time.sleep(espera)
                continue

            if resp.status_code == 401:
                raise AirtableError(
                    "401 Unauthorized: AIRTABLE_TOKEN inválido o revocado."
                )
            if resp.status_code == 403:
                raise AirtableError(
                    "403 Forbidden: al token le falta un scope. Para crear el campo "
                    "'Puntuación' necesitas 'schema.bases:write'; para escribir "
                    "registros 'data.records:write'. Revisa los scopes del PAT."
                )
            if resp.status_code == 422:
                raise AirtableError(f"422 Unprocessable: {resp.text}")
            if not resp.ok:
                raise AirtableError(f"{resp.status_code}: {resp.text}")

            return resp.json() if resp.text else {}

        raise AirtableError(
            f"Agotados {MAX_REINTENTOS} reintentos contra {url} (429/5xx persistente)."
        )

    # -------------------------------------------------- schema / Puntuación
    def asegurar_campo_puntuacion(self) -> str:
        """Crea el campo 'Puntuación' (number, 0 decimales) si no existe.
        Idempotente. Devuelve su field ID. Requiere scope schema.bases:*."""
        if "Puntuación" in self.field_ids and self.field_ids["Puntuación"]:
            # Confirmamos que existe de verdad en el schema.
            schema = self._request("GET", f"{META_ROOT}/{self.base_id}/tables")
            for tabla in schema.get("tables", []):
                if tabla.get("id") == self.table_id:
                    ids = {f.get("id") for f in tabla.get("fields", [])}
                    nombres = {f.get("name"): f.get("id") for f in tabla.get("fields", [])}
                    if self.field_ids["Puntuación"] in ids:
                        return self.field_ids["Puntuación"]
                    if "Puntuación" in nombres:
                        self.field_ids["Puntuación"] = nombres["Puntuación"]
                        return nombres["Puntuación"]
            # No estaba: se crea abajo.

        logger.info("Creando campo 'Puntuación' vía Metadata API…")
        creado = self._request(
            "POST",
            f"{META_ROOT}/{self.base_id}/tables/{self.table_id}/fields",
            {"name": "Puntuación", "type": "number", "options": {"precision": 0}},
        )
        fid = creado.get("id")
        if not fid:
            raise AirtableError(f"Respuesta inesperada al crear Puntuación: {creado}")
        self.field_ids["Puntuación"] = fid
        return fid

    # ------------------------------------------------------------ escritura
    def _lead_a_fields_objetivos(self, lead: Lead) -> dict:
        """Campos objetivos del scrapeo (se refrescan también en updates)."""
        f = self.field_ids
        fields = {
            f["Negocio"]: lead.negocio,
            f["Teléfono"]: lead.telefono,
            f["Ciudad"]: lead.ciudad,
            f["Nicho"]: lead.nicho,
            f["Google Maps URL"]: lead.maps_url,
            f["Puntuación"]: lead.puntuacion,
        }
        if lead.resenas is not None:
            fields[f["Reseñas"]] = lead.resenas
        if lead.nota_google is not None:
            fields[f["Nota Google"]] = lead.nota_google
        return fields

    def upsert_lote(self, leads: list[Lead]) -> dict:
        """Hace upsert de una lista de leads (troceada en peticiones de 10).

        Devuelve un resumen {creados, actualizados}. Tras el upsert, fija
        Estado='Por llamar' y Notas SOLO en los registros nuevos.
        """
        creados_total = 0
        actualizados_total = 0
        telefono_fid = self.field_ids["Teléfono"]

        for grupo in _trocear(leads, MAX_RECORDS_POR_PETICION):
            payload = {
                "performUpsert": {"fieldsToMergeOn": [telefono_fid]},
                "records": [{"fields": self._lead_a_fields_objetivos(l)} for l in grupo],
                "typecast": False,       # exigimos que las opciones ya existan
                "returnFieldsByFieldId": True,
            }
            url = f"{API_ROOT}/{self.base_id}/{self.table_id}"
            resp = self._request("PATCH", url, payload)

            creados = resp.get("createdRecords", []) or []
            actualizados = resp.get("updatedRecords", []) or []
            creados_total += len(creados)
            actualizados_total += len(actualizados)

            # Inicializa Estado y Notas solo en los NUEVOS (no pisa leads trabajados).
            self._inicializar_nuevos(resp, grupo, creados)

        logger.info("Airtable: %d creados, %d actualizados (%d leads).",
                    creados_total, actualizados_total, len(leads))
        return {"creados": creados_total, "actualizados": actualizados_total}

    def _inicializar_nuevos(self, resp: dict, grupo: list[Lead], creados_ids: list[str]) -> None:
        """Escribe Estado='Por llamar' + Notas en los registros recién creados.

        Mapea record_id -> lead usando el teléfono devuelto (returnFieldsByFieldId).
        """
        if not creados_ids:
            return
        telefono_fid = self.field_ids["Teléfono"]
        por_telefono = {l.telefono: l for l in grupo}

        registros_patch = []
        for rec in resp.get("records", []):
            if rec.get("id") not in creados_ids:
                continue
            tel = (rec.get("fields", {}) or {}).get(telefono_fid)
            lead = por_telefono.get(tel)
            if not lead:
                continue
            registros_patch.append(
                {
                    "id": rec["id"],
                    "fields": {
                        self.field_ids["Estado"]: "Por llamar",
                        self.field_ids["Notas"]: lead.notas,
                    },
                }
            )

        for grupo_patch in _trocear(registros_patch, MAX_RECORDS_POR_PETICION):
            url = f"{API_ROOT}/{self.base_id}/{self.table_id}"
            self._request("PATCH", url, {"records": grupo_patch, "typecast": False})


def _trocear(items: list, n: int) -> Iterable[list]:
    for i in range(0, len(items), n):
        yield items[i : i + n]

"""Carga y validación de config.json + credenciales.

Regla del brief: si config.json no existe o está INCOMPLETO, DETENERSE y avisar.
No se inventan IDs jamás. Este módulo convierte esa regla en una excepción
clara que el CLI muestra y aborta.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path("config.json")

# Field IDs que el pipeline necesita SÍ o SÍ en la tabla Leads.
CAMPOS_REQUERIDOS = [
    "Negocio", "Teléfono", "Ciudad", "Nicho", "Reseñas",
    "Nota Google", "Estado", "Google Maps URL", "Notas", "Puntuación",
]


class ConfigIncompleta(Exception):
    """config.json ausente o sin los IDs necesarios. El CLI la traduce en
    'DETENTE y pídemelo'."""


@dataclass(frozen=True)
class Config:
    base_id: str
    leads_table_id: str
    field_ids: dict[str, str]          # nombre de campo -> fldXXXX
    ciudades: list[str]
    nichos: list[str]

    def field(self, nombre: str) -> str:
        try:
            return self.field_ids[nombre]
        except KeyError as exc:  # pragma: no cover - protegido por validación previa
            raise ConfigIncompleta(f"Falta el field ID de '{nombre}' en config.json") from exc


def cargar_config(path: Path = CONFIG_PATH) -> Config:
    """Lee y valida config.json. Lanza ConfigIncompleta si algo falta."""
    if not path.exists():
        raise ConfigIncompleta(
            f"No existe {path}. DETENGO: no puedo inventar baseId/tableId/fieldIds. "
            "Pásame un config.json válido en la raíz del repo."
        )

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigIncompleta(f"{path} no es JSON válido: {exc}") from exc

    try:
        airtable = data["airtable"]
        base_id = airtable["baseId"]
        leads = airtable["tables"]["leads"]
        table_id = leads["tableId"]
        field_ids = dict(leads["fieldIds"])
        targets = data.get("targets", {})
        ciudades = list(targets.get("ciudades", []))
        nichos = list(targets.get("nichos", []))
    except (KeyError, TypeError) as exc:
        raise ConfigIncompleta(
            f"{path} no tiene la estructura esperada (airtable.tables.leads...): {exc}"
        ) from exc

    faltan = [c for c in CAMPOS_REQUERIDOS if c not in field_ids or not field_ids[c]]
    if faltan:
        raise ConfigIncompleta(
            "config.json incompleto. Faltan field IDs de: "
            + ", ".join(faltan)
            + ". DETENGO: no invento IDs."
        )
    if not base_id or not table_id:
        raise ConfigIncompleta("baseId o tableId de Leads vacíos en config.json.")
    if not ciudades or not nichos:
        raise ConfigIncompleta(
            "Faltan 'targets.ciudades' o 'targets.nichos' en config.json."
        )

    return Config(
        base_id=base_id,
        leads_table_id=table_id,
        field_ids=field_ids,
        ciudades=ciudades,
        nichos=nichos,
    )


def cargar_token() -> str:
    """Lee AIRTABLE_TOKEN del entorno. Lanza ConfigIncompleta si no está
    (salvo en --dry-run, donde el CLI no llama aquí)."""
    token = os.environ.get("AIRTABLE_TOKEN", "").strip()
    if not token:
        raise ConfigIncompleta(
            "AIRTABLE_TOKEN no está en el entorno. Expórtalo antes de un run real "
            "(no hace falta en --dry-run). Ver .env.example."
        )
    return token

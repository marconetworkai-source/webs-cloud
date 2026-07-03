"""Checkpoint persistente en disco.

Garantiza que cada ejecución reanuda exactamente donde terminó la anterior y
que un bloqueo no corrompe el estado (escritura atómica: fichero temporal +
os.replace).

Dos ficheros en state/:
  - checkpoint.json : puntero a la próxima combinación nicho×ciudad a procesar.
  - seen_phones.json: teléfonos ya guardados (dedup local, ahorra llamadas a DDG
                      y refuerza el 'cero duplicados' además del upsert de Airtable).

El puntero SOLO avanza cuando una combinación se procesa por completo. Si la
cuota del run corta a mitad de una combinación, el puntero no avanza y el
siguiente run la re-scrapea desde el principio; el upsert por teléfono evita
duplicados en Airtable, así que re-scrapear es idempotente (solo cuesta tiempo,
y la velocidad es el último criterio).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

STATE_DIR = Path("state")
CHECKPOINT_PATH = STATE_DIR / "checkpoint.json"
SEEN_PHONES_PATH = STATE_DIR / "seen_phones.json"


def _escritura_atomica(path: Path, contenido: str) -> None:
    """Escribe `contenido` en `path` de forma atómica."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(contenido, encoding="utf-8")
    os.replace(tmp, path)  # atómico en el mismo sistema de ficheros


@dataclass
class Checkpoint:
    """Estado de avance del barrido de combinaciones."""

    combo_index: int = 0                       # índice de la próxima combinación
    combos_completados: int = 0                # contador histórico (informativo)
    _seen: set[str] = field(default_factory=set, repr=False)

    # ---- combinaciones ----
    @staticmethod
    def cargar() -> "Checkpoint":
        cp = Checkpoint()
        if CHECKPOINT_PATH.exists():
            try:
                data = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
                cp.combo_index = int(data.get("combo_index", 0))
                cp.combos_completados = int(data.get("combos_completados", 0))
            except (json.JSONDecodeError, ValueError, TypeError):
                # Checkpoint corrupto: empezar de cero es preferible a explotar.
                cp.combo_index = 0
                cp.combos_completados = 0
        cp._seen = _cargar_seen_phones()
        return cp

    def guardar(self) -> None:
        _escritura_atomica(
            CHECKPOINT_PATH,
            json.dumps(
                {
                    "combo_index": self.combo_index,
                    "combos_completados": self.combos_completados,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    def avanzar_combo(self) -> None:
        """Marca la combinación actual como completada y avanza el puntero."""
        self.combo_index += 1
        self.combos_completados += 1
        self.guardar()

    def reiniciar_barrido(self) -> None:
        """Vuelve al inicio del barrido (todas las combinaciones agotadas)."""
        self.combo_index = 0
        self.guardar()

    # ---- dedup de teléfonos ----
    def ya_visto(self, telefono: str) -> bool:
        return telefono in self._seen

    def marcar_visto(self, telefono: str) -> None:
        if telefono and telefono not in self._seen:
            self._seen.add(telefono)
            _guardar_seen_phones(self._seen)

    @property
    def total_vistos(self) -> int:
        return len(self._seen)


def _cargar_seen_phones() -> set[str]:
    if not SEEN_PHONES_PATH.exists():
        return set()
    try:
        data = json.loads(SEEN_PHONES_PATH.read_text(encoding="utf-8"))
        return set(data) if isinstance(data, list) else set()
    except (json.JSONDecodeError, ValueError, TypeError):
        return set()


def _guardar_seen_phones(phones: set[str]) -> None:
    _escritura_atomica(
        SEEN_PHONES_PATH,
        json.dumps(sorted(phones), ensure_ascii=False, indent=0),
    )

"""Orquestación del pipeline: barrido de combinaciones, cuota, lotes, pausas,
protocolo de bloqueo y resumen.

Invariante de aceptación: vistos = guardados + descartados. Los contadores del
resumen se llevan de forma que esta igualdad se cumpla siempre.
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional

from . import anti_ban
from .airtable_client import AirtableClient
from .checkpoint import Checkpoint
from .config import Config
from .maps_scraper import BloqueoDetectado, MapsScraper
from .models import Lead
from .scoring import calcular_puntuacion
from .verify import buscar_ddg_fetcher, confirmar_sin_web, normalizar_telefono

logger = logging.getLogger("prospeccion")

RESUMEN_DIR = Path("logs")


@dataclass
class Resumen:
    vistos: int = 0
    guardados: int = 0
    descartados: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    por_ciudad: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    por_nicho: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    por_combo: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    bloqueos: int = 0
    duracion_s: float = 0.0
    dry_run: bool = False
    combos_procesados: int = 0

    def total_descartados(self) -> int:
        return sum(self.descartados.values())

    def cuadra(self) -> bool:
        return self.vistos == self.guardados + self.total_descartados()

    def como_dict(self) -> dict:
        return {
            "vistos": self.vistos,
            "guardados": self.guardados,
            "descartados": dict(self.descartados),
            "total_descartados": self.total_descartados(),
            "desglose_por_ciudad": dict(self.por_ciudad),
            "desglose_por_nicho": dict(self.por_nicho),
            "desglose_por_combinacion": dict(self.por_combo),
            "bloqueos": self.bloqueos,
            "combos_procesados": self.combos_procesados,
            "duracion_segundos": round(self.duracion_s, 1),
            "dry_run": self.dry_run,
            "cuadra_vistos_igual_guardados_mas_descartados": self.cuadra(),
        }


def construir_combinaciones(
    config: Config, ciudad: Optional[str], nicho: Optional[str]
) -> list[tuple[str, str]]:
    """Lista ordenada de (ciudad, nicho). Orden: ciudad externa, nicho interno
    -> primera combinación = (Valencia, Fontanero), que es la del PASO 1."""
    ciudades = [ciudad] if ciudad else config.ciudades
    nichos = [nicho] if nicho else config.nichos
    return [(c, n) for c in ciudades for n in nichos]


def _construir_notas(cand, verif, timestamp: str) -> str:
    partes: list[str] = []
    email = cand.email or verif.email
    if email:
        partes.append(f"email: {email}")
    if verif.instagram:
        partes.append(f"Instagram: {verif.instagram}")
    if verif.facebook:
        partes.append(f"Facebook: {verif.facebook}")
    dudas = list(cand.dudas) + list(verif.dudas)
    if dudas:
        partes.append("dudas: " + "; ".join(dudas))
    partes.append(f"scrapeado: {timestamp}")
    return " | ".join(partes)


class Pipeline:
    def __init__(
        self,
        config: Config,
        cliente: Optional[AirtableClient],
        checkpoint: Checkpoint,
        *,
        quota: int,
        lote: int,
        ciudad: Optional[str] = None,
        nicho: Optional[str] = None,
        visible: bool = False,
        dry_run: bool = False,
        ddg_get: Optional[Callable] = None,
        scraper: Optional[MapsScraper] = None,
    ) -> None:
        self.config = config
        self.cliente = cliente
        self.checkpoint = checkpoint
        self.quota = quota
        self.lote = lote
        self.ciudad = ciudad
        self.nicho = nicho
        self.visible = visible
        self.dry_run = dry_run
        self.filtrado = bool(ciudad or nicho)
        self._ddg_get = ddg_get or buscar_ddg_fetcher()
        self._scraper_inyectado = scraper

        self.resumen = Resumen(dry_run=dry_run)
        self._en_lote: list[Lead] = []
        self._bloqueo_recuperado = False

    # ------------------------------------------------------------ helpers
    @property
    def _listos(self) -> int:
        return self.resumen.guardados + len(self._en_lote)

    def _flush(self, *, final: bool) -> None:
        """Escribe el lote actual en Airtable (o simula en dry-run), marca
        teléfonos vistos, guarda checkpoint y pausa 5 min si procede."""
        if not self._en_lote:
            return
        n = len(self._en_lote)
        if self.dry_run or self.cliente is None:
            logger.info("[dry-run] Se guardarían %d leads (no se escribe en Airtable).", n)
        else:
            self.cliente.upsert_lote(self._en_lote)

        for lead in self._en_lote:
            self.checkpoint.marcar_visto(lead.telefono)
        self.resumen.guardados += n
        self._en_lote.clear()
        self.checkpoint.guardar()

        lote_completo = n >= self.lote
        if not final and lote_completo and self._listos < self.quota:
            logger.info("Lote completado. Pausa de 5 minutos…")
            anti_ban.dormir(anti_ban.LOTE, "entre lotes")

    def _descartar(self, motivo: str, nombre: str, detalle: str = "") -> None:
        # 'vistos' se cuenta en cada desenlace terminal (descarte o lead) para que
        # 'vistos = guardados + descartados' cuadre SIEMPRE, incluso si la cuota
        # corta a mitad de combinación o salta un bloqueo (tarjetas no procesadas
        # no se cuentan como vistas).
        self.resumen.vistos += 1
        self.resumen.descartados[motivo] += 1
        logger.info("DESCARTE [%s] '%s' %s", motivo, nombre, detalle)

    # ------------------------------------------------------------ combos
    def _procesar_combo(self, scraper: MapsScraper, ciudad: str, nicho: str) -> None:
        """Procesa una combinación completa. Puede lanzar BloqueoDetectado.
        Si la cuota se alcanza a mitad, retorna sin terminar la combinación
        (el checkpoint NO se avanza en ese caso — lo decide el llamador)."""
        cards = scraper.buscar(nicho, ciudad)

        for card in cards:
            if self._listos >= self.quota:
                return
            # Regla: negocio CON web en la tarjeta -> descartar sin abrir ficha.
            if card.tiene_web:
                self._descartar("con_web", card.nombre, "(web visible en tarjeta)")
                continue

            cand = scraper.abrir_ficha(card, nicho, ciudad)
            anti_ban.dormir(anti_ban.FICHA, "entre fichas")

            if cand is None:
                self._descartar("sin_datos_ficha", card.nombre)
                continue

            telefono = normalizar_telefono(cand.telefono_raw)
            if not telefono:
                self._descartar("sin_telefono", cand.nombre,
                                f"(raw={cand.telefono_raw!r})")
                continue

            if self.checkpoint.ya_visto(telefono):
                self._descartar("duplicado", cand.nombre, f"({telefono})")
                continue

            verif = confirmar_sin_web(cand.nombre, ciudad, self._ddg_get)
            anti_ban.dormir(anti_ban.DUCKDUCKGO, "entre búsquedas DDG")

            if verif.tiene_web_propia:
                self._descartar("con_web", cand.nombre,
                                f"(dominio {verif.dominio_detectado})")
                continue

            tiene_red = bool(verif.instagram or verif.facebook)
            puntuacion = calcular_puntuacion(
                nicho=nicho, resenas=cand.resenas, tiene_red_social=tiene_red
            )
            notas = _construir_notas(cand, verif, datetime.now().isoformat(timespec="seconds"))

            lead = Lead(
                negocio=cand.nombre, telefono=telefono, ciudad=ciudad, nicho=nicho,
                resenas=cand.resenas, nota_google=cand.nota_google,
                maps_url=cand.maps_url or card.place_url or "", puntuacion=puntuacion,
                notas=notas, instagram=verif.instagram, facebook=verif.facebook,
                email=cand.email or verif.email,
            )
            self._en_lote.append(lead)
            self.resumen.vistos += 1   # desenlace terminal 'lead' (ver _descartar)
            self.resumen.por_ciudad[ciudad] += 1
            self.resumen.por_nicho[nicho] += 1
            self.resumen.por_combo[f"{ciudad}×{nicho}"] += 1
            logger.info("LEAD OK '%s' %s punt=%d (%s/%s) [%d/%d]",
                        lead.negocio, telefono, puntuacion, ciudad, nicho,
                        self._listos, self.quota)

            if len(self._en_lote) >= self.lote:
                self._flush(final=False)

    # ------------------------------------------------------------ run
    def ejecutar(self) -> Resumen:
        t0 = time.monotonic()
        combos = construir_combinaciones(self.config, self.ciudad, self.nicho)

        if self.filtrado:
            inicio = 0
            logger.info("Run FILTRADO (%s / %s): no se toca el checkpoint global.",
                        self.ciudad or "*", self.nicho or "*")
        else:
            inicio = self.checkpoint.combo_index % len(combos) if combos else 0
            logger.info("Run de BARRIDO: reanudo en combinación #%d de %d.",
                        inicio, len(combos))

        scraper_ctx = self._scraper_inyectado or MapsScraper(visible=self.visible)
        try:
            with scraper_ctx as scraper:
                i = inicio
                while i < len(combos) and self._listos < self.quota:
                    ciudad, nicho = combos[i]
                    try:
                        self._procesar_combo(scraper, ciudad, nicho)
                        # _procesar_combo solo retorna antes de terminar si se
                        # alcanzó la cuota; en ese caso NO avanzamos el checkpoint.
                        if self._listos >= self.quota:
                            # cuota alcanzada, posiblemente a mitad de combo -> no avanzar
                            logger.info("Cuota de %d alcanzada.", self.quota)
                            break
                        # combinación terminada por completo
                        self.resumen.combos_procesados += 1
                        if not self.filtrado:
                            self.checkpoint.avanzar_combo()
                        i += 1
                        if i < len(combos) and self._listos < self.quota:
                            anti_ban.dormir(anti_ban.COMBINACION, "entre combinaciones")
                    except BloqueoDetectado as exc:
                        self.resumen.bloqueos += 1
                        ts = datetime.now().isoformat(timespec="seconds")
                        logger.error("BLOQUEO DETECTADO %s — %s", ts, exc)
                        self.checkpoint.guardar()
                        self._flush(final=True)   # salva lo verificado; sin pausa de lote
                        if self._bloqueo_recuperado:
                            logger.error("Segundo bloqueo: termino limpiamente (nunca segunda espera).")
                            break
                        self._bloqueo_recuperado = True
                        logger.warning("Espero 30 min y reintento UNA vez la misma combinación…")
                        anti_ban.dormir(anti_ban.BLOQUEO, "espera anti-bloqueo")
                        # reintenta el MISMO i (no se avanza)
                        continue

                # barrido agotado sin alcanzar cuota
                if i >= len(combos) and self._listos < self.quota and not self.filtrado:
                    logger.info("Barrido completo de todas las combinaciones. Reinicio puntero.")
                    self.checkpoint.reiniciar_barrido()

                self._flush(final=True)
        finally:
            self.resumen.duracion_s = time.monotonic() - t0

        self._emitir_resumen()
        return self.resumen

    # ------------------------------------------------------------ resumen
    def _emitir_resumen(self) -> None:
        d = self.resumen.como_dict()
        logger.info("===== RESUMEN =====")
        logger.info("Vistos: %d | Guardados: %d | Descartados: %d (%s)",
                    d["vistos"], d["guardados"], d["total_descartados"], d["descartados"])
        logger.info("Bloqueos: %d | Combos: %d | Duración: %ss | Cuadra: %s",
                    d["bloqueos"], d["combos_procesados"], d["duracion_segundos"],
                    d["cuadra_vistos_igual_guardados_mas_descartados"])
        if not d["cuadra_vistos_igual_guardados_mas_descartados"]:
            logger.warning("¡El resumen NO cuadra! Revisa el conteo (vistos != guardados+descartados).")

        RESUMEN_DIR.mkdir(parents=True, exist_ok=True)
        destino = RESUMEN_DIR / f"resumen_{date.today().isoformat()}.json"
        destino.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Resumen guardado en %s", destino)

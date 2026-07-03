"""Fase 1 — Scraping de Google Maps con Scrapling StealthyFetcher.

Una sola sesión stealth persistente (perfil en disco -> cookies de consentimiento
sobreviven entre ejecuciones), una sola pestaña, secuencial. Extracción en
cascada por ficha: CSS actual -> selectores adaptativos -> JSON embebido. Si las
tres fallan en 3 fichas consecutivas -> BloqueoDetectado.

IMPORTANTE (deuda conocida): los selectores CSS del DOM de Google Maps cambian
con frecuencia y NO han podido validarse contra HTML real en el entorno de
construcción (Google está bloqueado por política de red). El PASO 1 del protocolo
de arranque (--visible en tu máquina) es precisamente la validación: si algún
campo sale vacío, ajusta los selectores de la sección SELECTORES — están todos
centralizados aquí y la cascada + el fallback JSON amortiguan los cambios.
"""

from __future__ import annotations

import json
import logging
import random
import re
from typing import Optional
from urllib.parse import quote, urlparse

from . import anti_ban
from .models import Candidato, RawCard

logger = logging.getLogger("prospeccion")

PERFIL_DIR = "state/browser_profile"
MAX_RESULTADOS = 40
MAX_SCROLL_ITER = 25

# --------------------------------------------------------------------------
# SELECTORES  (ajústalos en el PASO 1 si el DOM de Maps ha cambiado)
# --------------------------------------------------------------------------
SEL_FEED = 'div[role="feed"]'
SEL_CARDS = [
    'div[role="feed"] > div > div[jsaction]',
    "div.Nv2PK",
    'a.hfpxzc',
]
SEL_CARD_NOMBRE = [".qBF1Pd", ".fontHeadlineSmall", 'a.hfpxzc[aria-label]']
SEL_CARD_NOTA = [".MW4etd", 'span[role="img"][aria-label*="estrella"]']
SEL_CARD_RESENAS = [".UY7F9", "span.RDApEe", ".ZkP5Je"]
SEL_CARD_LINK = ["a.hfpxzc", 'a[href*="/maps/place/"]']
SEL_CARD_WEB = [  # presencia = la tarjeta ya ofrece 'Sitio web'
    'a[data-value="Sitio web"]',
    'a[data-value="Website"]',
    "a.lcr4fd",
    'a[aria-label*="Visitar sitio web"]',
    'a[aria-label*="sitio web"]',
]
SEL_FIN_LISTA = [".HlvSq", ".PbZDve", ".m6QErb.XiKgde"]

SEL_DETALLE_TELEFONO = [
    'button[data-item-id^="phone:tel:"]',
    'a[data-item-id^="phone:tel:"]',
    'button[aria-label*="Teléfono"]',
    'button[aria-label*="Telefono"]',
]
SEL_DETALLE_WEB = [
    'a[data-item-id="authority"]',
    'a[aria-label*="Sitio web"]',
    'a[data-tooltip="Abrir sitio web"]',
]
SEL_CONSENT_BTNS = [
    'button[aria-label*="Aceptar todo"]',
    'button[aria-label*="Acepto"]',
    'form[action*="consent"] button[jsname]',
    "button.tHlp8d",
    'div[role="dialog"] button:has-text("Aceptar todo")',
]


class BloqueoDetectado(Exception):
    """Captcha, /sorry/, o 3 fichas consecutivas sin estructura esperada."""


def _primero(selectors):
    """Devuelve el primer elemento de un resultado .css(...) o None."""
    if selectors is None:
        return None
    try:
        return selectors[0]
    except (IndexError, TypeError):
        return None


def _texto(el) -> str:
    if el is None:
        return ""
    try:
        t = el.get_all_text(strip=True)
    except Exception:  # noqa: BLE001
        t = getattr(el, "text", "") or ""
    return (t or "").strip()


def _num_resenas(texto: str) -> Optional[int]:
    """'(1.234)' / '1.234 reseñas' -> 1234."""
    if not texto:
        return None
    m = re.search(r"([\d.\s]+)", texto.replace(" ", " "))
    if not m:
        return None
    digits = re.sub(r"[^\d]", "", m.group(1))
    return int(digits) if digits else None


def _nota_google(texto: str) -> Optional[float]:
    """'4,6' o '4.6' -> 4.6."""
    if not texto:
        return None
    m = re.search(r"([0-5])[.,](\d)", texto)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m2 = re.search(r"\b([0-5])\b", texto)
    return float(m2.group(1)) if m2 else None


class MapsScraper:
    """Envuelve una StealthySession reutilizable. Usar como context manager."""

    def __init__(self, visible: bool = False) -> None:
        self.visible = visible
        self._session = None
        self._fallos_consecutivos = 0

    def __enter__(self) -> "MapsScraper":
        from scrapling.fetchers import StealthySession

        logger.info("Abriendo sesión stealth (headless=%s, perfil=%s)",
                    not self.visible, PERFIL_DIR)
        self._session = StealthySession(
            headless=not self.visible,
            user_data_dir=PERFIL_DIR,       # perfil persistente -> cookies de consent
            max_pages=1,                    # una sola pestaña
            timezone_id="Europe/Madrid",
            locale="es-ES",
            block_webrtc=True,
            disable_resources=False,
        )
        # Algunas versiones exponen start(); el context manager lo hace por dentro.
        self._session.__enter__()
        return self

    def __exit__(self, *exc) -> None:
        if self._session is not None:
            try:
                self._session.__exit__(*exc)
            except Exception as e:  # noqa: BLE001
                logger.warning("Error cerrando la sesión stealth: %s", e)

    # ---------------------------------------------------------------- bloqueo
    @staticmethod
    def _detectar_bloqueo(resp) -> bool:
        url = (getattr(resp, "url", "") or "").lower()
        if "/sorry/" in url or "/recaptcha" in url:
            return True
        if getattr(resp, "status", 200) in (429, 403):
            return True
        html = (getattr(resp, "html_content", "") or "").lower()
        señales = ("unusual traffic", "tráfico inusual", "trafico inusual",
                   "detección de robots", "not a robot", "id=\"recaptcha\"",
                   "nuestros sistemas han detectado")
        return any(s in html for s in señales)

    def _nota_bloqueo_o_sigue(self, resp, contexto: str) -> None:
        if self._detectar_bloqueo(resp):
            raise BloqueoDetectado(f"Señal de bloqueo en {contexto}: url={getattr(resp,'url','?')}")

    # --------------------------------------------------------- page_actions
    def _accion_resultados(self, page) -> None:
        """Resuelve consent y hace scroll progresivo del panel de resultados."""
        self._resolver_consent(page)
        self._scroll_feed(page)

    def _resolver_consent(self, page) -> None:
        try:
            url = page.url or ""
        except Exception:  # noqa: BLE001
            url = ""
        necesita = "consent.google" in url or "consent" in url
        for sel in SEL_CONSENT_BTNS:
            try:
                btn = page.query_selector(sel)
            except Exception:  # noqa: BLE001
                btn = None
            if btn:
                try:
                    btn.click(timeout=5000)
                    logger.info("Consentimiento aceptado (%s).", sel)
                    page.wait_for_timeout(1500)
                    return
                except Exception as e:  # noqa: BLE001
                    logger.debug("No pude clicar consent %s: %s", sel, e)
        if necesita:
            logger.warning("Pantalla de consent presente pero no encontré botón conocido.")

    def _scroll_feed(self, page) -> None:
        try:
            feed = page.query_selector(SEL_FEED)
        except Exception:  # noqa: BLE001
            feed = None

        prev, estable = 0, 0
        for i in range(MAX_SCROLL_ITER):
            try:
                if feed:
                    page.evaluate("(el) => el.scrollBy(0, el.scrollHeight)", feed)
                else:
                    page.mouse.wheel(0, 3000)
            except Exception as e:  # noqa: BLE001
                logger.debug("Scroll iter %d falló: %s", i, e)
            page.wait_for_timeout(int(random.uniform(*anti_ban.SCROLL) * 1000))

            # ¿Fin de la lista?
            fin = False
            for sel in SEL_FIN_LISTA:
                try:
                    if page.query_selector(sel):
                        fin = True
                        break
                except Exception:  # noqa: BLE001
                    pass

            try:
                cards = page.query_selector_all(SEL_CARDS[0]) or page.query_selector_all(".Nv2PK")
                count = len(cards)
            except Exception:  # noqa: BLE001
                count = prev

            if fin or count >= MAX_RESULTADOS:
                logger.debug("Scroll detenido en iter %d (count=%d, fin=%s)", i, count, fin)
                break
            if count == prev:
                estable += 1
                if estable >= 3:
                    logger.debug("Lista estable en %d resultados.", count)
                    break
            else:
                estable = 0
            prev = count

    @staticmethod
    def _esperar_ficha(page) -> None:
        try:
            page.wait_for_selector('button[data-item-id^="phone:tel:"], h1',
                                   timeout=8000)
        except Exception:  # noqa: BLE001
            pass  # se maneja en la cascada de extracción

    # --------------------------------------------------------------- búsqueda
    def buscar(self, nicho: str, ciudad: str) -> list[RawCard]:
        """Devuelve las tarjetas de la combinación. Lanza BloqueoDetectado."""
        url = (
            "https://www.google.com/maps/search/"
            f"{quote(nicho)}+en+{quote(ciudad)}?hl=es"
        )
        logger.info("Buscando: %s en %s -> %s", nicho, ciudad, url)
        resp = self._session.fetch(
            url,
            page_action=self._accion_resultados,
            wait_selector=SEL_FEED,
            wait_selector_state="visible",
            load_dom=True,
            timeout=60000,
        )
        self._nota_bloqueo_o_sigue(resp, "resultados")
        cards = self._extraer_tarjetas(resp)
        logger.info("  %d tarjetas leídas (%s en %s).", len(cards), nicho, ciudad)
        return cards

    def _extraer_tarjetas(self, resp) -> list[RawCard]:
        """Cascada: CSS -> adaptativo -> JSON embebido."""
        # (a) CSS actual
        cards = self._tarjetas_desde_dom(resp, adaptive=False)
        if cards:
            return cards
        # (b) selectores adaptativos de Scrapling
        logger.info("CSS de tarjetas vacío; probando selectores adaptativos.")
        cards = self._tarjetas_desde_dom(resp, adaptive=True)
        if cards:
            return cards
        # (c) JSON embebido APP_INITIALIZATION_STATE
        logger.info("Adaptativo vacío; probando JSON embebido.")
        cards = self._tarjetas_desde_json(resp)
        return cards

    def _tarjetas_desde_dom(self, resp, adaptive: bool) -> list[RawCard]:
        elementos = None
        for sel in SEL_CARDS:
            try:
                res = resp.css(sel, adaptive=adaptive, auto_save=adaptive)
            except Exception as e:  # noqa: BLE001
                logger.debug("css(%s) falló: %s", sel, e)
                res = None
            if res and len(res) > 0:
                elementos = res
                break
        if not elementos:
            return []

        cards: list[RawCard] = []
        for el in elementos:
            nombre = _texto(_primero(_css_multi(el, SEL_CARD_NOMBRE)))
            if not nombre:
                # a veces el nombre está en aria-label del propio enlace
                link = _primero(_css_multi(el, SEL_CARD_LINK))
                nombre = (link.attrib.get("aria-label") if link is not None else "") or ""
                nombre = nombre.strip()
            if not nombre:
                continue

            nota = _nota_google(_texto(_primero(_css_multi(el, SEL_CARD_NOTA))))
            resenas = _num_resenas(_texto(_primero(_css_multi(el, SEL_CARD_RESENAS))))

            link = _primero(_css_multi(el, SEL_CARD_LINK))
            place_url = None
            if link is not None:
                href = link.attrib.get("href")
                if href:
                    place_url = href if href.startswith("http") else "https://www.google.com" + href

            tiene_web = self._tarjeta_tiene_web(el)

            cards.append(RawCard(
                nombre=nombre, nota_google=nota, resenas=resenas,
                tiene_web=tiene_web, place_url=place_url,
                metodo_extraccion="adaptive" if adaptive else "css",
            ))
        return cards

    @staticmethod
    def _tarjeta_tiene_web(el) -> bool:
        for sel in SEL_CARD_WEB:
            try:
                res = el.css(sel)
            except Exception:  # noqa: BLE001
                res = None
            if res and len(res) > 0:
                # confirma que el href no es de google
                cand = res[0]
                href = (cand.attrib.get("href") or "") if hasattr(cand, "attrib") else ""
                host = urlparse(href).netloc.lower()
                if href and "google." not in host:
                    return True
                if not href:  # botón sin href pero con data-value 'Sitio web'
                    return True
        return False

    def _tarjetas_desde_json(self, resp) -> list[RawCard]:
        """Último recurso: rasca APP_INITIALIZATION_STATE. Best-effort y de baja
        confianza; se marca metodo_extraccion='json' y se anota como duda aguas
        abajo. No inventa: si no puede, devuelve lista vacía."""
        html = getattr(resp, "html_content", "") or ""
        m = re.search(r"window\.APP_INITIALIZATION_STATE\s*=\s*(\[.*?\]);</script>",
                      html, re.DOTALL)
        if not m:
            m = re.search(r"APP_INITIALIZATION_STATE\s*=\s*(\[.+?\]);", html, re.DOTALL)
        if not m:
            logger.warning("No se encontró APP_INITIALIZATION_STATE en el HTML.")
            return []
        try:
            blob = json.loads(m.group(1))
        except json.JSONDecodeError as e:
            logger.warning("APP_INITIALIZATION_STATE no parseable: %s", e)
            return []

        # El blob es enorme y anidado. Rascamos place URLs + nombres de forma laxa.
        texto_blob = json.dumps(blob, ensure_ascii=False)
        place_urls = re.findall(r"https://www\.google\.com/maps/place/[^\"\\]+", texto_blob)
        cards: list[RawCard] = []
        vistos = set()
        for pu in place_urls[:MAX_RESULTADOS]:
            if pu in vistos:
                continue
            vistos.add(pu)
            # nombre aproximado desde el slug de la URL
            try:
                slug = urlparse(pu).path.split("/place/")[1].split("/")[0]
                nombre = slug.replace("+", " ")
            except (IndexError, ValueError):
                nombre = ""
            if not nombre:
                continue
            cards.append(RawCard(
                nombre=nombre, nota_google=None, resenas=None,
                tiene_web=False,           # desconocido -> lo confirmará DDG en Fase 2
                place_url=pu, metodo_extraccion="json",
            ))
        logger.info("JSON embebido: %d place URLs rascadas (baja confianza).", len(cards))
        return cards

    # ----------------------------------------------------------------- ficha
    def abrir_ficha(self, card: RawCard, nicho: str, ciudad: str) -> Optional[Candidato]:
        """Abre la ficha de un candidato y extrae teléfono + URL canónica.

        Cuenta fallos consecutivos de extracción; al tercero lanza BloqueoDetectado.
        """
        if not card.place_url:
            logger.info("Candidato '%s' sin place_url; no puedo abrir ficha.", card.nombre)
            self._registrar_fallo_ficha()
            return None

        resp = self._session.fetch(
            card.place_url,
            page_action=self._esperar_ficha,
            load_dom=True,
            timeout=45000,
        )
        self._nota_bloqueo_o_sigue(resp, f"ficha:{card.nombre}")

        telefono = self._extraer_telefono(resp)
        maps_url = getattr(resp, "url", None) or card.place_url
        email = self._extraer_email(resp)
        dudas: list[str] = []

        if card.metodo_extraccion == "json":
            dudas.append("tarjeta_via_json_baja_confianza")

        if telefono is None:
            logger.info("Ficha '%s': sin teléfono extraíble.", card.nombre)
            self._registrar_fallo_ficha()
        else:
            self._fallos_consecutivos = 0  # éxito -> resetea contador de bloqueo

        return Candidato(
            nombre=card.nombre, ciudad=ciudad, nicho=nicho,
            nota_google=card.nota_google, resenas=card.resenas,
            telefono_raw=telefono, maps_url=maps_url, email=email,
            metodo_extraccion=card.metodo_extraccion, dudas=dudas,
        )

    def _registrar_fallo_ficha(self) -> None:
        self._fallos_consecutivos += 1
        if self._fallos_consecutivos >= 3:
            raise BloqueoDetectado(
                "3 fichas consecutivas sin estructura esperada (posible bloqueo)."
            )

    def _extraer_telefono(self, resp) -> Optional[str]:
        # (a) data-item-id="phone:tel:+34..." — lo más fiable
        for sel in SEL_DETALLE_TELEFONO:
            try:
                el = _primero(resp.css(sel))
            except Exception:  # noqa: BLE001
                el = None
            if el is None:
                continue
            data_id = el.attrib.get("data-item-id") if hasattr(el, "attrib") else None
            if data_id and "phone:tel:" in data_id:
                return data_id.split("phone:tel:")[-1]
            aria = el.attrib.get("aria-label") if hasattr(el, "attrib") else None
            if aria:
                m = re.search(r"(\+?\d[\d\s]{7,}\d)", aria)
                if m:
                    return m.group(1)
        # (b) adaptativo
        try:
            el = _primero(resp.css('button[data-item-id^="phone:tel:"]', adaptive=True, auto_save=True))
            if el is not None:
                data_id = el.attrib.get("data-item-id")
                if data_id and "phone:tel:" in data_id:
                    return data_id.split("phone:tel:")[-1]
        except Exception:  # noqa: BLE001
            pass
        # (c) JSON / regex sobre el HTML
        html = getattr(resp, "html_content", "") or ""
        m = re.search(r"tel:(\+?\d[\d\s\-]{7,}\d)", html)
        if m:
            return m.group(1)
        return None

    @staticmethod
    def _extraer_email(resp) -> Optional[str]:
        """Email SOLO si aparece explícito en la ficha (Maps casi nunca lo muestra).
        No se inventa ni se deriva del dominio."""
        html = getattr(resp, "html_content", "") or ""
        m = re.search(r"mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", html)
        return m.group(1) if m else None


def _css_multi(el, selectores: list[str]):
    """Prueba una lista de selectores y devuelve el primer resultado no vacío."""
    for sel in selectores:
        try:
            res = el.css(sel)
        except Exception:  # noqa: BLE001
            res = None
        if res and len(res) > 0:
            return res
    return None

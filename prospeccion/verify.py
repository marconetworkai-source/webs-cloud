"""Fase 2 — Verificación de candidatos.

Orden: teléfono -> confirmación 'sin web' -> redes sociales. Se descarta al
PRIMER fallo, registrando el motivo. Ante la duda sobre si un dominio es del
negocio, se CONSERVA el lead y se anota la duda (mejor un falso candidato que
descartar en silencio un buen lead).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

logger = logging.getLogger("prospeccion")

# --------------------------------------------------------------------------
# Teléfono
# --------------------------------------------------------------------------
_SOLO_DIGITOS_Y_MAS = re.compile(r"[^\d+]")


def normalizar_telefono(raw: Optional[str]) -> Optional[str]:
    """Normaliza a +34XXXXXXXXX. Válido = 9 dígitos tras el prefijo, empezando
    por 6, 7, 8 o 9. Devuelve None si no es un móvil/fijo español válido.

    Acepta entradas tipo '+34 963 12 34 56', '0034963123456', '963123456',
    'tel:+34963123456'. No 'corrige' ni inventa: si no encaja, devuelve None.
    """
    if not raw:
        return None
    s = _SOLO_DIGITOS_Y_MAS.sub("", raw.strip())
    if not s:
        return None
    # Prefijos internacionales a formato nacional de 9 dígitos.
    if s.startswith("+34"):
        s = s[3:]
    elif s.startswith("0034"):
        s = s[4:]
    elif s.startswith("34") and len(s) == 11:  # 34 + 9 dígitos
        s = s[2:]
    s = s.lstrip("+")
    if len(s) != 9 or s[0] not in "6789":
        return None
    return "+34" + s


# --------------------------------------------------------------------------
# Confirmación 'sin web' vía DuckDuckGo HTML
# --------------------------------------------------------------------------
DDG_URL = "https://html.duckduckgo.com/html/?q={q}"

# Dominios que NO cuentan como web propia (directorios / agregadores / redes).
AGREGADORES = {
    "paginasamarillas.es", "paginasamarillas.com", "qdq.com", "habitissimo.es",
    "milanuncios.com", "facebook.com", "fb.com", "instagram.com", "tiktok.com",
    "linkedin.com", "google.com", "google.es", "tripadvisor.com", "tripadvisor.es",
    "yelp.com", "yelp.es", "yell.com", "cylex.es", "cylex-espana.es",
    "infoisinfo.es", "11870.com", "einforma.com", "axesor.es", "indeed.com",
    "booking.com", "doctoralia.es", "doctoralia.com", "guiasocial.com",
    "hotfrog.es", "europages.es", "solofos.com", "empresite.eleconomista.es",
    "youtube.com", "twitter.com", "x.com", "wa.me", "maps.google.com",
    "goo.gl", "bing.com", "duckduckgo.com", "es.wikipedia.org", "wikipedia.org",
}

# Redes cuyo perfil SÍ nos interesa detectar (no descartan; puntúan).
_RE_INSTAGRAM = re.compile(r"https?://(?:www\.)?instagram\.com/[^\s\"'>&]+", re.I)
_RE_FACEBOOK = re.compile(r"https?://(?:www\.|m\.|es-es\.)?facebook\.com/[^\s\"'>&]+", re.I)
_RE_EMAIL = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

_ACENTOS = re.compile(r"[̀-ͯ]")
_NO_ALNUM = re.compile(r"[^a-z0-9]+")
_STOPWORDS = {
    "el", "la", "los", "las", "de", "del", "y", "e", "sl", "slu", "sa", "cb",
    "sc", "sll", "and", "the", "grupo", "hermanos", "hnos", "servicios",
    "clinica", "centro", "estudio", "taller", "reformas",
}


@dataclass
class ResultadoVerificacion:
    tiene_web_propia: bool
    instagram: Optional[str] = None
    facebook: Optional[str] = None
    email: Optional[str] = None
    dominio_detectado: Optional[str] = None
    dudas: list[str] = field(default_factory=list)


def _norm_texto(texto: str) -> str:
    """Minúsculas, sin acentos, solo alfanumérico separado por espacios."""
    nfkd = unicodedata.normalize("NFKD", texto.lower())
    sin_acentos = _ACENTOS.sub("", nfkd)
    return _NO_ALNUM.sub(" ", sin_acentos).strip()


def _tokens_negocio(nombre: str) -> set[str]:
    return {t for t in _norm_texto(nombre).split() if len(t) > 2 and t not in _STOPWORDS}


def _registered_domain(host: str) -> str:
    """Aproxima el dominio registrable (segundo nivel). Suficiente para comparar
    contra la lista de agregadores y contra el nombre del negocio."""
    host = host.lower().lstrip(".")
    if host.startswith("www."):
        host = host[4:]
    partes = host.split(".")
    if len(partes) <= 2:
        return host
    # ccTLD de segundo nivel comunes en ES (.com.es, .org.es...).
    if partes[-2] in {"com", "org", "net", "gob", "co"} and partes[-1] in {"es", "eu"}:
        return ".".join(partes[-3:])
    return ".".join(partes[-2:])


def _extraer_urls_resultados(html: str) -> list[str]:
    """Extrae los enlaces de resultado del HTML de DuckDuckGo, en orden.

    DDG HTML envuelve los destinos en /l/?uddg=<url-encoded>. Se desenvuelven.
    """
    urls: list[str] = []
    # Enlaces de resultado: class="result__a" href="...".
    for m in re.finditer(r'result__a[^>]*href="([^"]+)"', html):
        href = m.group(1).replace("&amp;", "&")
        if "/l/?" in href or href.startswith("//duckduckgo.com/l/"):
            parsed = urlparse(href if href.startswith("http") else "https:" + href)
            qs = parse_qs(parsed.query)
            if "uddg" in qs:
                href = unquote(qs["uddg"][0])
        urls.append(href)
    return urls


def confirmar_sin_web(
    nombre: str,
    ciudad: str,
    fetcher_get,
) -> ResultadoVerificacion:
    """Busca «"{nombre}" {ciudad}» en DuckDuckGo y decide si el negocio tiene web propia.

    `fetcher_get` es un callable (url) -> objeto con .html_content/.status/.url
    (se inyecta el Fetcher.get de Scrapling; así este módulo es testeable).

    Analiza los 5 primeros resultados. Si un dominio no-agregador comparte token
    con el nombre del negocio -> web propia -> descartar. Si el solape es parcial
    o dudoso -> conservar y anotar la duda.
    """
    from urllib.parse import quote_plus

    q = quote_plus(f'"{nombre}" {ciudad}')
    url = DDG_URL.format(q=q)

    try:
        resp = fetcher_get(url)
    except Exception as exc:  # noqa: BLE001 - se registra, no se silencia
        logger.warning("DDG falló para '%s' (%s): %s. Conservo el lead por prudencia.",
                       nombre, ciudad, exc)
        return ResultadoVerificacion(
            tiene_web_propia=False,
            dudas=[f"verificacion_ddg_fallida:{type(exc).__name__}"],
        )

    html = getattr(resp, "html_content", "") or ""
    if not html:
        logger.warning("DDG devolvió HTML vacío para '%s'. Conservo el lead.", nombre)
        return ResultadoVerificacion(
            tiene_web_propia=False, dudas=["ddg_html_vacio"]
        )

    resultado = ResultadoVerificacion(tiene_web_propia=False)

    # Redes sociales (en todo el HTML, no solo top 5): alimentan puntuación.
    m_ig = _RE_INSTAGRAM.search(html)
    if m_ig:
        resultado.instagram = m_ig.group(0)
    m_fb = _RE_FACEBOOK.search(html)
    if m_fb:
        resultado.facebook = m_fb.group(0)
    m_mail = _RE_EMAIL.search(html)
    if m_mail and not m_mail.group(0).endswith((".png", ".jpg")):
        resultado.email = m_mail.group(0)

    tokens = _tokens_negocio(nombre)
    top5 = _extraer_urls_resultados(html)[:5]
    logger.debug("DDG top5 para '%s': %s", nombre, top5)

    for u in top5:
        try:
            host = urlparse(u).netloc
        except ValueError:
            continue
        if not host:
            continue
        dom = _registered_domain(host)
        if not dom or dom in AGREGADORES:
            continue
        # Dominio candidato a web propia: ¿comparte token con el negocio?
        etiqueta = dom.split(".")[0]
        etiqueta_tokens = set(_norm_texto(etiqueta).split())
        solape = tokens & etiqueta_tokens
        # Coincidencia también si un token del negocio está contenido en la etiqueta.
        contenido = any(t in etiqueta for t in tokens if len(t) >= 4)

        if solape or contenido:
            resultado.tiene_web_propia = True
            resultado.dominio_detectado = dom
            logger.info("Web propia detectada para '%s': %s (solape=%s)",
                        nombre, dom, solape or "substring")
            return resultado
        else:
            # Dominio no-agregador sin solape claro: duda, no descarta.
            resultado.dudas.append(f"dominio_ambiguo:{dom}")

    return resultado


def buscar_ddg_fetcher():
    """Devuelve el callable Fetcher.get de Scrapling con cabeceras razonables.

    Se define aquí para que verify.py no importe Scrapling salvo cuando se usa
    de verdad (los tests pueden inyectar su propio fetcher)."""
    from scrapling.fetchers import Fetcher

    def _get(url: str):
        return Fetcher.get(
            url,
            headers={
                "Accept-Language": "es-ES,es;q=0.9",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0 Safari/537.36"
                ),
            },
            timeout=30,
        )

    return _get

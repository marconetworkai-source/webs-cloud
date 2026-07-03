"""Modelos de datos del pipeline. Sin lógica de red; solo estructura."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class MotivoDescarte(str, Enum):
    """Motivos por los que un candidato no llega a guardarse. Se registran
    en el resumen para que los totales cuadren (vistos = guardados + descartados)."""

    TIENE_WEB_EN_TARJETA = "con_web"           # la tarjeta de Maps ya muestra 'Sitio web'
    SIN_TELEFONO = "sin_telefono"              # sin teléfono español válido
    WEB_CONFIRMADA_DDG = "con_web"             # DuckDuckGo revela un dominio propio
    SIN_DATOS_FICHA = "sin_datos_ficha"        # no se pudo extraer nada de la ficha
    DUPLICADO_LOCAL = "duplicado"              # ya procesado/guardado en un run anterior


@dataclass
class RawCard:
    """Lo que se lee de UNA tarjeta del panel de resultados, sin abrir la ficha."""

    nombre: str
    nota_google: Optional[float]        # valoración 0-5 (1 decimal)
    resenas: Optional[int]              # nº de reseñas
    tiene_web: bool                     # True si la tarjeta muestra enlace 'Sitio web' externo
    place_url: Optional[str]            # href a /maps/place/... para abrir el detalle
    metodo_extraccion: str = "css"      # css | adaptive | json — para observabilidad


@dataclass
class Candidato:
    """Negocio SIN web en la tarjeta, con los datos de su ficha de detalle ya extraídos."""

    nombre: str
    ciudad: str
    nicho: str
    nota_google: Optional[float]
    resenas: Optional[int]
    telefono_raw: Optional[str]         # tal cual se leyó de Maps, sin normalizar
    maps_url: Optional[str]             # URL canónica de la ficha (post-navegación)
    email: Optional[str] = None         # solo si aparece explícito en la ficha
    metodo_extraccion: str = "css"
    dudas: list[str] = field(default_factory=list)   # anotaciones de incertidumbre


@dataclass
class Lead:
    """Candidato que ha superado la verificación y está listo para Airtable."""

    negocio: str
    telefono: str                       # normalizado +34XXXXXXXXX (clave de merge)
    ciudad: str
    nicho: str
    resenas: Optional[int]
    nota_google: Optional[float]
    maps_url: str
    puntuacion: int
    notas: str                          # concatenado: email, redes, dudas, timestamp
    # campos auxiliares que alimentan la puntuación / notas (no van a columnas propias)
    instagram: Optional[str] = None
    facebook: Optional[str] = None
    email: Optional[str] = None

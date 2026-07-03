"""Pipeline de prospección B2B: scrapea Google Maps, verifica negocios sin web,
puntúa y persiste en Airtable.

Diseñado para correr de noche sin supervisión en la máquina del usuario
(IP residencial). NO está pensado para ejecutarse en un entorno cloud/CI:
Google Maps banea IPs de datacenter casi al instante.
"""

__version__ = "1.0.0"

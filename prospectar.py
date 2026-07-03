#!/usr/bin/env python3
"""CLI del pipeline de prospección B2B.

Uso:
  python prospectar.py --quota 80 --lote 20 [--ciudad X] [--nicho Y] [--dry-run] [--visible]

Protocolo de arranque (validación humana obligatoria entre fases):
  PASO 1:  python prospectar.py --dry-run --quota 5 --ciudad Valencia --nicho Fontanero --visible
  PASO 2:  python prospectar.py --quota 20
  PASO 3:  python prospectar.py --quota 80        (habilitado solo tras OK de 1 y 2)

Este script está pensado para ejecutarse en TU máquina (IP residencial), no en
un entorno cloud/CI: Google Maps banea IPs de datacenter.
"""

from __future__ import annotations

import argparse
import sys

from prospeccion.checkpoint import Checkpoint
from prospeccion.config import ConfigIncompleta, cargar_config, cargar_token
from prospeccion.logging_setup import configurar_logging
from prospeccion.pipeline import Pipeline


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Prospección B2B: Google Maps -> verificación -> Airtable.",
    )
    p.add_argument("--quota", type=int, default=80,
                   help="Leads verificados y guardados por ejecución (def. 80).")
    p.add_argument("--lote", type=int, default=20,
                   help="Tamaño de lote: escritura + checkpoint + pausa 5 min (def. 20).")
    p.add_argument("--ciudad", type=str, default=None,
                   help="Restringe a una ciudad (run filtrado; no toca el checkpoint global).")
    p.add_argument("--nicho", type=str, default=None,
                   help="Restringe a un nicho (run filtrado; no toca el checkpoint global).")
    p.add_argument("--dry-run", action="store_true",
                   help="Pipeline completo SIN escribir en Airtable.")
    p.add_argument("--visible", action="store_true",
                   help="Navegador no headless (para depurar el PASO 1).")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logger = configurar_logging()

    # 1) Config: si falta o está incompleta -> DETENERSE (no inventar IDs).
    try:
        config = cargar_config()
    except ConfigIncompleta as exc:
        logger.error("CONFIG: %s", exc)
        print(f"\n⛔ DETENGO. {exc}\n", file=sys.stderr)
        return 2

    # 2) Validaciones de argumentos con nombres exactos de targets.
    if args.ciudad and args.ciudad not in config.ciudades:
        logger.error("Ciudad '%s' no está en targets: %s", args.ciudad, config.ciudades)
        return 2
    if args.nicho and args.nicho not in config.nichos:
        logger.error("Nicho '%s' no está en targets: %s", args.nicho, config.nichos)
        return 2
    if args.quota < 1 or args.lote < 1:
        logger.error("--quota y --lote deben ser >= 1.")
        return 2

    # 3) Cliente de Airtable solo en runs reales.
    cliente = None
    if not args.dry_run:
        try:
            token = cargar_token()
        except ConfigIncompleta as exc:
            logger.error("TOKEN: %s", exc)
            print(f"\n⛔ DETENGO. {exc}\n", file=sys.stderr)
            return 2
        from prospeccion.airtable_client import AirtableClient, AirtableError

        cliente = AirtableClient(
            token=token, base_id=config.base_id,
            table_id=config.leads_table_id, field_ids=dict(config.field_ids),
        )
        try:
            cliente.asegurar_campo_puntuacion()
        except AirtableError as exc:
            logger.error("AIRTABLE: %s", exc)
            print(f"\n⛔ DETENGO. {exc}\n", file=sys.stderr)
            return 3

    checkpoint = Checkpoint.cargar()

    logger.info(
        "Arranque | quota=%d lote=%d ciudad=%s nicho=%s dry_run=%s visible=%s",
        args.quota, args.lote, args.ciudad or "*", args.nicho or "*",
        args.dry_run, args.visible,
    )

    pipeline = Pipeline(
        config=config, cliente=cliente, checkpoint=checkpoint,
        quota=args.quota, lote=args.lote, ciudad=args.ciudad, nicho=args.nicho,
        visible=args.visible, dry_run=args.dry_run,
    )

    try:
        resumen = pipeline.ejecutar()
    except KeyboardInterrupt:
        logger.warning("Interrumpido por el usuario. El checkpoint está a salvo.")
        return 130

    _imprimir_tabla_resumen(resumen)
    return 0 if resumen.cuadra() else 1


def _imprimir_tabla_resumen(resumen) -> None:
    d = resumen.como_dict()
    print("\n" + "=" * 52)
    print("  RESUMEN DE LA EJECUCIÓN" + ("  (DRY-RUN)" if d["dry_run"] else ""))
    print("=" * 52)
    print(f"  Candidatos vistos : {d['vistos']}")
    print(f"  Guardados         : {d['guardados']}")
    print(f"  Descartados       : {d['total_descartados']}")
    for motivo, n in sorted(d["descartados"].items()):
        print(f"      - {motivo:<16}: {n}")
    print(f"  Bloqueos          : {d['bloqueos']}")
    print(f"  Duración          : {d['duracion_segundos']} s")
    print(f"  Cuadra (v=g+d)    : {'sí' if d['cuadra_vistos_igual_guardados_mas_descartados'] else 'NO'}")
    if d["desglose_por_combinacion"]:
        print("  Por combinación   :")
        for combo, n in sorted(d["desglose_por_combinacion"].items()):
            print(f"      - {combo:<28}: {n}")
    print("=" * 52 + "\n")


if __name__ == "__main__":
    raise SystemExit(main())

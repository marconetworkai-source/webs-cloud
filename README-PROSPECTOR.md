# 🔎 Prospector — scraping de Google Maps → Airtable

Pipeline de prospección B2B: scrapea Google Maps, se queda con negocios **sin
página web**, los verifica, los puntúa y hace **upsert** en Airtable (tabla
`Leads`). Pensado para correr **de noche, sin supervisión, en tu máquina**.

> ⚠️ **Dónde ejecutarlo.** Córrelo en tu ordenador o en un servidor con **IP
> residencial normal**. NO lo ejecutes en cloud/CI/datacenter: Google Maps
> banea esas IPs casi al instante. (Por eso este código se construyó pero no se
> ejecutó en el entorno de Claude: la política de red bloquea Google, DuckDuckGo
> y Airtable.)

---

## 1. Instalación (una sola vez)

```bash
cd webs-cloud
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
scrapling install          # descarga el navegador stealth (Camoufox)
```

Credenciales (el token NUNCA se sube al repo — `.env` está en `.gitignore`):

```bash
cp .env.example .env
# edita .env y pon tu Personal Access Token de Airtable:
#   scopes necesarios: data.records:read/write  y  schema.bases:read/write
export $(grep -v '^#' .env | xargs)
```

`config.json` ya trae `baseId`, `tableId` y todos los `fieldIds` verificados. Si
faltara algo, el script **se detiene** en vez de inventar IDs.

---

## 2. Protocolo de arranque (obligatorio — no te lo saltes)

La validación humana entre pasos es parte del diseño. No pases al siguiente paso
sin revisar el anterior.

### PASO 1 — Prueba en seco, navegador visible, 5 leads

```bash
python prospectar.py --dry-run --quota 5 --ciudad Valencia --nicho Fontanero --visible
```

- `--dry-run`: recorre TODO el pipeline pero **no escribe en Airtable**.
- `--visible`: verás el navegador. **Mira que**: (a) acepta el consentimiento de
  Google una vez, (b) hace scroll de resultados, (c) abre fichas y saca teléfono.
- Revisa la tabla-resumen final y el log en `logs/`. Si algún campo sale vacío
  (nombre, teléfono, reseñas…), es que **el DOM de Maps cambió**: ajusta los
  selectores en `prospeccion/maps_scraper.py` (sección `SELECTORES`, todos juntos
  arriba). La extracción tiene cascada CSS → adaptativo → JSON para amortiguarlo.

👉 **No sigas hasta que los 5 leads salgan completos y correctos.**

### PASO 2 — Un lote real de 20

```bash
python prospectar.py --quota 20
```

Escribe 20 leads reales en Airtable. **Revisa la tabla `Leads`**: teléfonos en
`+34XXXXXXXXX`, `Estado = Por llamar`, `Google Maps URL` que abre, `Puntuación`
1-5, sin duplicados, ninguno con web propia.

👉 Solo con tu OK de los pasos 1 y 2 quedas habilitado para lo nocturno.

### PASO 3 — Ejecución nocturna, 80 leads

```bash
python prospectar.py --quota 80
```

Reanuda desde el checkpoint, procesa en lotes de 20 (escribe + checkpoint +
pausa 5 min entre lotes) y para al llegar a 80. Programa esto con `cron`:

```cron
# todas las noches a las 02:30
30 2 * * *  cd /ruta/webs-cloud && ./.venv/bin/python prospectar.py --quota 80 >> logs/cron.log 2>&1
```

---

## 3. Referencia del CLI

```
python prospectar.py [--quota N] [--lote N] [--ciudad X] [--nicho Y] [--dry-run] [--visible]
```

| Flag | Def. | Qué hace |
|---|---|---|
| `--quota` | 80 | Leads verificados y guardados por ejecución. |
| `--lote` | 20 | Cada lote: escribe en Airtable + checkpoint + pausa 5 min. |
| `--ciudad` | todas | Restringe a una ciudad. **Run filtrado: no toca el checkpoint global.** |
| `--nicho` | todos | Restringe a un nicho. **Run filtrado: no toca el checkpoint global.** |
| `--dry-run` | off | Pipeline completo **sin** escribir en Airtable. |
| `--visible` | off | Navegador no headless (para depurar). |

`--ciudad`/`--nicho` deben coincidir **exactos** con los valores de `config.json`
(tildes incluidas): `Valencia`, `Málaga`, `Clínica estética`…

---

## 4. Cómo funciona (fases)

1. **Scraping (Google Maps).** Una sola sesión stealth persistente (perfil en
   `state/browser_profile/` → las cookies de consentimiento sobreviven entre
   ejecuciones), una sola pestaña, secuencial. Scroll con pausas 2-4 s hasta ~40
   resultados. Los negocios que **ya muestran web en la tarjeta se descartan sin
   abrir la ficha**. De los candidatos se abre el detalle para sacar teléfono y
   URL canónica. Ritmo anti-baneo: 5-10 s entre fichas, 30-60 s entre
   combinaciones, 5 min entre lotes.
2. **Verificación.** Teléfono normalizado a `+34XXXXXXXXX` (9 dígitos, empieza
   6/7/8/9); sin teléfono válido → descarte. Confirmación «sin web» buscando
   `"{nombre}" {ciudad}` en DuckDuckGo: si un dominio propio aparece en el top 5
   → descarte. Directorios y redes (páginas amarillas, facebook, instagram…) no
   cuentan como web propia. Ante duda, **se conserva el lead y se anota en Notas**.
3. **Puntuación (1-5).** base 3 · +1 si Instagram/Facebook · +1 si Clínica
   estética/Dental/Fisioterapia · −1 si <10 reseñas · acotado a [1,5].
4. **Persistencia.** **Upsert** por teléfono (clave de merge) → **cero
   duplicados** entre ejecuciones. `Estado` y `Notas` se fijan **solo en leads
   nuevos**: si ya trabajaste un lead (p. ej. `Estado = Interesado`), una
   re-visita **no** te lo resetea; solo refresca datos objetivos (reseñas, nota,
   puntuación). Lotes de 10, ≤4 req/s, backoff exponencial ante 429/5xx.

### Protocolo de bloqueo

Si detecta captcha, `/sorry/`, o 3 fichas seguidas sin estructura: guarda
checkpoint → registra `BLOQUEO DETECTADO <timestamp>` → espera 30 min →
reintenta **una** vez → si persiste, termina limpio con resumen. Nunca martillea
una IP baneada.

---

## 5. Observabilidad

- `logs/run_YYYY-MM-DD.log` — cada lead, cada descarte con motivo, cada escritura,
  cada bloqueo.
- `logs/resumen_YYYY-MM-DD.json` — vistos, descartados por motivo, guardados,
  desglose por ciudad/nicho, bloqueos, duración, y el check `vistos = guardados +
  descartados`.
- `state/checkpoint.json` — puntero de reanudación. `state/seen_phones.json` —
  dedup local.

---

## 6. Estado / reanudación

El barrido recorre `ciudad × nicho` (Valencia→Fontanero primero). El puntero solo
avanza cuando una combinación se completa; si la cuota corta a mitad, el siguiente
run re-scrapea esa combinación (el upsert evita duplicados). Para empezar de cero,
borra `state/`.

---

## 7. Tests

```bash
pip install pytest
pytest -q          # 45 tests: teléfono, scoring, DDG, upsert, cuota, bloqueo, reconciliación,
                   #           estructura de ficha y activación del protocolo de bloqueo
```

Los tests cubren toda la lógica sin red (con scraper y DuckDuckGo simulados). La
única parte que **debes** validar con red real es la extracción de selectores del
DOM de Maps, y para eso está el PASO 1.

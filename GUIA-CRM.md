# 📗 Guía rápida — CRM Prospección Webs

> **Tu chuleta de uso diario.** Dos tablas, un flujo: **Leads** para perseguir, **Proyectos** para entregar.
> Base: `CRM Prospección Webs` · Workspace: `webs-claude`

---

## 🗺️ El flujo completo de un vistazo

```
🤖 Scraping          📞 Llamada fría        💬 Demo por WhatsApp
 (entra solo)    →    (tú llamas)      →     (si hay interés)
                                                    ↓
🌐 Web publicada  ←  🛠️ Construcción  ←   📞 Llamada 2 + cierre
   (cobro final)      (2 revisiones)        (cobro señal 50%)
```

- **Todo lo que pasa ANTES de cobrar la señal** → vive en la tabla **Leads**.
- **Todo lo que pasa DESPUÉS de cobrar la señal** → vive en la tabla **Proyectos**.
- El momento de cambio: cliente dice SÍ y paga señal → creas registro en Proyectos y lo enlazas al lead.

---

## 📋 Tabla 1 — LEADS (la caza)

Aquí entran los negocios scrapeados **automáticamente**. Tu trabajo diario es llamar y actualizar 3 campos: **Estado**, **Fecha último toque** y **Próxima acción**.

### Campos que se rellenan SOLOS (scraping) — no los toques

| Campo | Qué es | Ejemplo |
|---|---|---|
| 🏪 **Negocio** | Nombre del negocio | `Fontanería Hermanos López` |
| 📞 **Teléfono** | Clave única — así se evitan duplicados | `+34 612 345 678` |
| 🏙️ **Ciudad** | Una de las 5 ciudades objetivo | `Valencia` |
| 🔧 **Nicho** | Gremio del negocio | `Fontanero` |
| ⭐ **Reseñas** | Nº de reseñas en Google | `47` |
| 📊 **Nota Google** | Puntuación media (1 decimal) | `4.6` |
| 🗺️ **Google Maps URL** | Ficha del negocio en Maps | *(link)* |

> ⚠️ **Nunca edites el Teléfono a mano.** Es la clave con la que el scraper detecta si un negocio ya existe. Si lo cambias, entrará duplicado.

### Campos que rellenas TÚ mientras trabajas el lead

| Campo | Qué pones | Cuándo lo pones |
|---|---|---|
| 🚦 **Estado** | Fase del lead (ver semáforo abajo) | **Después de CADA llamada o mensaje**, sin excepción |
| 📅 **Fecha último toque** | La fecha de hoy | Cada vez que llamas o escribes al lead |
| ⏰ **Próxima acción** | Fecha del próximo contacto | Al colgar: decide ya cuándo insistes (ej. no contesta → +2 días) |
| 💬 **WhatsApp** | Número de WhatsApp si difiere del teléfono | Cuando lo consigas en la llamada |
| 🔗 **Link demo** | URL de la demo que le enviaste | Justo al enviar la demo por WhatsApp |
| 📝 **Notas** | Todo lo que te sirva para la próxima llamada | Siempre: quién contestó, objeciones, horarios («llamar por las tardes», «decide la mujer») |

### 🚦 El semáforo de Estado — cuándo usar cada uno

| Estado | Significa | Lo pones cuando... |
|---|---|---|
| ⚪ `Por llamar` | Lead nuevo, virgen | Entra del scraper (viene así por defecto) |
| 🔁 `No contesta` | Llamaste y nada | Colgó sin responder → pon **Próxima acción** a +1/+2 días |
| ❌ `No interesado` | Te dijo que no | Rechazo claro. No borres el lead: sirve de historial |
| 🟡 `Interesado` | Quiere ver algo | Mostró interés pero aún no le enviaste la demo |
| 💬 `Demo enviada` | Demo en su WhatsApp | Justo tras enviar el link (rellena también **Link demo**) |
| 📆 `Llamada 2 agendada` | Cita para cerrar | Acordasteis día/hora para la segunda llamada |
| ✅ `Cerrado` | ¡Vendido! | Aceptó y va a pagar señal → **crea el Proyecto ya** |
| ⚫ `Perdido` | Se enfrió después de interesarse | Vio demo o llegó a llamada 2 pero no cerró |

> 💡 **Diferencia `No interesado` vs `Perdido`:** el primero nunca quiso nada; el segundo llegó lejos y se cayó. A los `Perdido` puedes volver en 3 meses.

---

## 🛠️ Tabla 2 — PROYECTOS (la entrega)

Se abre un registro **solo cuando un lead paga la señal** (o está a punto). Uno por web vendida.

### Al crear el proyecto (día del cierre)

| Campo | Qué pones | Detalle |
|---|---|---|
| 👤 **Cliente** | Nombre del cliente o negocio | Es el campo principal |
| 🔗 **Lead** | Enlaza el registro de la tabla Leads | Así no pierdes el historial de la venta |
| 📦 **Pack** | Lo que compró | `Landing 250€` · `Web 400€` · `Web+Chatbot 600€` · `Chatbot 200€` |
| 💰 **Precio final** | Precio real acordado | Puede diferir del pack si negociaste |
| 🎙️ **Grabación Fathom** | Link de la grabación de la llamada de cierre | Nada más terminar la llamada |
| 📋 **Informe llamada** | Resumen: qué quiere, colores, secciones, referencias | Todo lo que necesitas para construir sin volver a preguntar |

### Al cobrar la señal (50%)

| Campo | Qué pones |
|---|---|
| ☑️ **Señal cobrada** | Marca el check **solo cuando el dinero esté en tu cuenta** |
| 📅 **Fecha señal** | El día que llegó el pago |

> 🚫 **Regla de oro: no empieces a construir sin el check de Señal cobrada marcado.**

### Durante la construcción — el campo Fase

Actualízalo **cada vez que el proyecto avanza**, para saber de un vistazo qué tienes entre manos:

| Fase | Significa | Sales de aquí cuando... |
|---|---|---|
| 📥 `Datos pendientes` | Esperas fotos, textos, logo del cliente | Te llega el material |
| 🏗️ `V1 en curso` | Estás construyendo la primera versión | Le envías la V1 |
| 👀 `Revisión 1` | Cliente revisa, tú aplicas cambios | Le reenvías la versión corregida |
| 👀 `Revisión 2` | Segunda (y **última**) ronda de cambios | Cliente da el OK final |
| 💶 `Pendiente cobro final` | Web lista, falta el otro 50% | El pago llega a tu cuenta |
| 🚀 `Publicada` | Web online. Proyecto cerrado 🎉 | — |

> 💡 Son **2 revisiones máximo** — está en el trato. Si pide una tercera, es extra y se cobra aparte.

### Al publicar

| Campo | Qué pones |
|---|---|
| 🌐 **Dominio** | El dominio final publicado (`fontanerialopez.es`) |
| 📅 **Fecha entrega** | Día en que la web quedó online |
| 🔄 **Mantenimiento €/mes** | Cuota mensual si contrató mantenimiento (déjalo vacío si no) |

---

## ☀️ Tu rutina diaria en 4 pasos

1. **Abre Leads** y filtra por **Próxima acción = hoy** (o anterior) → esa es tu lista de llamadas.
2. **Llama.** Tras cada llamada actualiza el trío: **Estado + Fecha último toque + Próxima acción** (y Notas).
3. **¿Interesado?** → Envía demo → `Demo enviada` + pega el **Link demo**.
4. **¿Cerrado?** → Estado `Cerrado` → crea el **Proyecto**, enlaza el **Lead** y sigue el flujo de Fases.

---

## ⚠️ Las 4 reglas que no se rompen

| # | Regla | Por qué |
|---|---|---|
| 1 | **No renombres campos ni opciones** (ni una tilde) | El scraper y los scripts escriben contra los nombres exactos: si cambias `Teléfono` por `Telefono`, se rompe todo |
| 2 | **No añadas ni borres opciones de los desplegables** | Mismo motivo: `Por llamar` ≠ `por llamar` |
| 3 | **No edites el Teléfono a mano** | Es la clave anti-duplicados del scraping |
| 4 | **Un lead nunca se borra** | Se marca `No interesado` o `Perdido`: el historial vale oro para reintentos futuros |

> ℹ️ El campo **«Proyectos»** que ves al final de la tabla Leads lo creó Airtable automáticamente (es el reverso del enlace **Lead**). Se rellena solo — ignóralo.

---

*Base creada el 03/07/2026 · IDs técnicos para scripts en `config.json`*

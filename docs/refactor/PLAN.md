# Plan de refactor incremental de IXP

Base: [auditoría](../architecture/CURRENT_STATE.md), [arquitectura propuesta](../architecture/TARGET_STATE.md), [seguridad](../SECURITY.md) y [limpieza de historial](SECURITY_CLEANUP.md). Revisado el 2026-10-18 para reflejar lo ya ejecutado.

## Condición de bloqueo

Hasta que los administradores de Graylog y LibreNMS revoquen los tokens expuestos y se rote lo indicado en [SECURITY.md](../SECURITY.md), ninguna fase reduce el riesgo real: el commit antiguo y `IXP/graylog/.env` siguen accesibles en GitHub por SHA (HTTP 200). Las fases de código pueden avanzar en paralelo, pero no se despliegan contra producción con credenciales anteriores.

## Estado y orden de ejecución

Estados: **hecho**, **en curso**, **pendiente**, **bloqueado**. Responsable por defecto: mantenedor de IXP, salvo donde se indique.

| Fase | Estado | Cambio acotado | Condición de aceptación |
|---|---|---|---|
| P0 — Contención (repo) | hecho | Secretos retirados de Skills y plantillas; `.gitignore`; historial reescrito y publicado con force-with-lease; gitleaks sin hallazgos | Ningún secreto literal en archivos distribuibles; `.env` ignorado |
| P0 — Contención (operativa) | **bloqueado** (administradores de plataformas) | Revocar tokens Graylog/LibreNMS; cambiar password admin, credenciales reutilizadas y comunidad SNMP; revisar logs de autenticación; solicitar purga a GitHub Support si la rotación no basta | Credenciales anteriores invalidadas y comprobadas como rechazadas; acceso de consulta mínimo |
| P0 — Endpoints en Skills | hecho en repo; Akvorado reactivado con cliente; gNMI sigue deshabilitado (falta `skills.entries` en la instalación) | Retirar IP/hostnames reales de Akvorado y gNMI; deshabilitar su ejecución autónoma hasta tener adaptador | Sin endpoints de infraestructura en Skills; el agente informa fuente no habilitada en lugar de ejecutar curl |
| P0 — Línea base OpenClaw | en curso | Versión fijada en la guía: 2026.8.35 (`extended-stable`); falta instalarla, registrar el digest y comprobar que la configuración de la instalación coincide; versionar `openclaw.json` saneado; documentar cómo llegan `tools/` y variables al sandbox de ejecución; restringir la herramienta de ejecución a los clientes permitidos; deshabilitar en `skills.entries` los Skills sin adaptador | Instalación reproducible con versión concreta; el agente no puede ejecutar curl/SQL arbitrario aunque el Skill lo sugiera |
| P0 — CI | hecho en repo; pendiente primera ejecución en GitHub | Workflow con `unittest discover` de `tools/` y gitleaks | Pruebas y escaneo de secretos en cada push/PR |
| P1 — Graylog | hecho (falta validar contra la versión instalada) | `graylog_query.py` + `read_api.py`; fixtures sintéticos; Skill migrado | Ver «Graylog: compatibilidad» |
| P1 — Modelo local | pendiente | Elegir modelo Qwen y backend (Ollama, vLLM u otro) y medirlo con OpenClaw instalado | Modelo, tamaño, cuantización y contexto documentados; ≥ 9/10 ejecuciones correctas de herramienta en casos A–D con fixtures; fallo explícito si el backend cae; sin fallback cloud obligatorio |
| P1 — PMACCT ingesta | hecho en repo; falta validar en laboratorio y migrar (ver `Pmacct/README.md`) | Extraer ingester del README a archivos versionados con pruebas; timeout en POST; no vaciar lotes fallidos; flush por tiempo sin nuevas líneas; checkpoint; rotación coordinada | En laboratorio: cero pérdidas en reinicio del consumidor y de ClickHouse; duplicación y lag reportados con cifras; sin `except: continue` |
| P2 — LibreNMS | hecho en repo; falta confirmar envelopes de la API contra la versión instalada | `librenms_query.py`: operaciones enumeradas (resolve, devices, ports, bgp, alerts, sensors, eventlog), allowlist `LIBRENMS_ALLOWED_DEVICES`, filtrado por ámbito vía `device_id`, unidades y horas UTC con `LIBRENMS_TIMEZONE`; Skill migrado. `read_api.py librenms` sigue disponible como CLI genérica: no instalarla en el workspace del agente | Sin rutas o parámetros libres desde el operador; pruebas de contrato con fixtures; resolución display/sysName → hostname probada |
| P2 — Evidencias | pendiente | Contrato común validado; una fuente por cambio | Fuente, alcance, fechas UTC, unidades, referencia y estado probados |
| P2 — Ópticas | hecho en repo (`librenms_query.py optics`); falta confirmar formato de `health/device_dbm` | Resolver dispositivo/interfaz y sensores; RX/TX y límites | Margen inferior = actual − mínimo; superior = máximo − actual; dBm de medición y dB de margen; distinguir umbral DOM del fabricante de límite asignado por LibreNMS; sin umbral inventado; ausencias y violaciones probadas |
| P2 — PMACCT consulta | pendiente | Consulta BGP de solo lectura | Resultados sin afirmar RIB completa; vacío distinto de colector atrasado |
| P3 — Akvorado e inventario | Akvorado hecho en repo (`akvorado_query.py`, Skill reactivado); falta confirmar esquema, retención de tablas y cuenta readonly; IXP Manager y gNMI pendientes | Cuenta SELECT, transporte protegido, consultas parametrizadas con plantillas cerradas; IXP Manager; evaluar gNMI | Tráfico sin doble muestreo; filtros y ventanas acotados; asociación miembro/ASN/puerto verificable |
| P3 — Correlación | hecho en repo (`correlate.py`, Skill Correlacion); caso D sin PMACCT (falta cliente de lectura de `bmp_events`) | Casos A–D, contradicciones y reporte con fuentes | Hipótesis separadas de observaciones; fuentes caídas explícitas; sin causalidad injustificada |
| P4 — Operación | pendiente | Instalación segura, diagnóstico, rollback y métricas; Oxidized/Zabbix solo con necesidad real | Procedimientos reproducibles; escrituras deshabilitadas por defecto |

No introducir frameworks, colas, servicios ni bases vectoriales sin necesidad demostrada. Los clientes usan Python 3 de la biblioteca estándar; confirmar el runtime del sandbox de OpenClaw antes de añadir dependencias.

Excepción registrada: LibreNMS se migró a `read_api.py` en el mismo cambio que Graylog para retirar su token del Skill. Esa migración solo cambia el transporte; su cliente estructurado sigue siendo la fase P2 — LibreNMS.

## Graylog: compatibilidad

El cambio no conserva las mismas consultas, deliberadamente:

- Ya no se acepta Lucene libre. Solo eventos enumerados (`all`, `bgp`, `interface-down`, `config`, `critical`), interfaz, vecino BGP, ventana de 1–86400 s y límite de 1–100.
- Solo equipos en `GRAYLOG_ALLOWED_SOURCES`.
- HTTPS obligatorio con certificado válido; las URLs HTTP anteriores dejan de funcionar.
- La salida es JSON con contrato (`status`, `evidence`, `coverage`, `warnings`), no la respuesta cruda de Graylog.
- Sin paginación: devuelve una muestra acotada y marca `sample_truncated` o `unknown_total_results`.

Pruebas existentes: filtros rechazados antes de red, allowlist, vacío frente a parcial, horas y referencias ausentes, contrato inválido o fuera de ámbito, instrucciones en logs como datos, 401/403/429/500, timeout, JSON inválido y respuesta sobredimensionada. Pendiente: confirmar contra la versión instalada que `search/universal/relative` y `messages[].message` siguen vigentes; probar otros 5xx con la respuesta real.

Rollback: no existe vuelta al curl sobre HTTP con token. Si el cliente falla en producción, la vuelta atrás es desactivar el Skill de Graylog e informar la fuente como no disponible mientras se corrige; si falta HTTPS, el prerrequisito es un proxy TLS o túnel, no relajar el cliente. Nunca reintroducir credenciales comprometidas. Cambios de nombres/rutas requieren alias o migración explícita. No mover `Akavorado` ni reestructurar IXP en esta fase.

## Pruebas y fixtures previstos

| Caso | Datos de prueba | Verificación |
|---|---|---|
| A: puerto down | Estado down, logs, tráfico por ventana y eventos BGP; variante con Graylog caído | Línea temporal y alcance del impacto observado; fuente caída visible |
| B: umbral óptico | RX/TX, mínimo/máximo, óptica, valores ausentes e incompatibles | Márgenes en dB y orden de riesgo; distinguir potencia alta/baja y falta de umbral |
| C: degradación UP | Interfaz UP, caída de tráfico, errores y RX; BGP sin cambios o contradictorio | Degradación sin inventar down ni causa confirmada |
| D: cambios BGP | Updates/retiros, peer, timestamps y miembro; ventana vacía y colector atrasado | PMACCT solo para rutas; vacío diferenciado de fuente sana y completa |

Añadir contratos por fuente para autenticación, timeout, paginación y respuestas incompletas; seguridad para shell/SQL, URLs fuera de allowlist, redirecciones, logs con prompt injection y consultas entre IXP/POP. Las pruebas de IA deben comprobar afirmaciones contra fixtures, no limitarse a buscar frases del prompt.

Ejecutar las pruebas desde la raíz del repositorio:

```sh
python -m unittest discover -s IXP/ai-agent/OpenClaw/tools -p "test_*.py" -v
```

## Dependencias y riesgos pendientes

- Se necesita acceso autorizado de lectura a versiones, configuración saneada y muestras para confirmar contratos; la auditoría no requiere acceso a producción.
- En el entorno de desarrollo actual Git, Docker y Bash no están en PATH; Python sí. Setup y Compose solo se han revisado estáticamente. Validarlos en un host Linux de laboratorio antes de cambios operativos. No ejecutar scripts de instalación para suplir herramientas durante una revisión.
- La ingesta BMP escribe telemetría y usa credenciales separadas de la cuenta SELECT del agente. Sus cambios requieren comparar conteos, pérdida, duplicación y recuperación en laboratorio antes de sustituir el proceso operativo.
- Las IPs y hostnames retirados de los Skills de Akvorado y gNMI siguen en el historial publicado y en la documentación de despliegue (README, Graylog, LibreNMS, PMACCT). Decidir si se sustituyen por marcadores en toda la documentación. Comprobar que ClickHouse (`:8123`) y el endpoint de métricas no son accesibles desde Internet sin autenticación; si lo son, es un riesgo inmediato independiente de este refactor.
- Toda fase termina con su comprobación y la documentación de sus limitaciones.

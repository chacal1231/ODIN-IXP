# Estado actual de IXP

Auditoría estática: 2026-10-18. Alcance: `IXP/` del checkout local ODIN, cuyo remoto declarado es `chacal1231/ODIN`. `ISP/` queda fuera. El documento ODIN_REFACTOR_CODEX.md se usa como referencia de requisitos; sus instrucciones de instalación o implementación no se han ejecutado.

Este documento conserva la línea base previa a cambios. La remediación posterior y las acciones operativas pendientes se documentan en [SECURITY.md](../SECURITY.md). En esa intervención se localizaron Python fuera de PATH y Git portátil, se ejecutaron pruebas del nuevo cliente y se confirmó que el commit con secretos ya está publicado en GitHub.

## Inventario y evidencia

| Componente | Archivos reales | Clasificación |
|---|---|---|
| Graylog | `graylog/docker-compose.yml`, dos scripts shell, README y guía de PEs | Parcial: despliegue versionado; funcionamiento remoto no verificable |
| Consulta Graylog | `ai-agent/OpenClaw/Skills/Graylog/SKILL.md` | Parcial: receta curl con credencial literal; sin cliente ni pruebas |
| LibreNMS | `LibreNMS/LibreNMS.md`, Skill LibreNMS | Parcial: instalación y consultas documentadas; sin Compose propio |
| Akvorado | `Skills/Akavorado/SKILL.md` | Parcial: SQL sobre ClickHouse; esquema y muestreo no verificados |
| gNMI | `Skills/Gnmi/SKILL.md` | Parcial: lectura de métricas Prometheus mediante curl/grep |
| PMACCT | `Pmacct/README.md` | Parcial: configuración, DDL, Compose e ingester Python incrustados en Markdown; sin ejecutables independientes ni Skill |
| OpenClaw | README, IDENTITY.md, USER.md y archivo `.openclaw` de 15 bytes no parseable como JSON | Parcial: instrucciones; versión y configuración instalada no verificables |
| Qwen local | Sin configuración reproducible encontrada | Ausente en el checkout inspeccionado |
| IXP Manager / Zabbix / Oxidized | Sin adaptadores ni Skills encontrados | Ausentes; Oxidized solo aparece como intención en README |
| Dominio, evidencias, correlación, memoria | Sin módulos o contratos encontrados | Ausentes |
| Pruebas, CI, build y lint de IXP | Sin manifiesto, suite ni pipeline encontrados | Ausentes |

Las declaraciones de «producción» de los README son antecedentes documentales, no verificaciones de esta auditoría. No se ha clasificado ninguna integración como funcional de extremo a extremo sin una ejecución comprobada.

## Recorrido de una pregunta

El recorrido descrito es operador → Telegram/Control UI → OpenClaw externo → proveedor LLM configurado externamente → selección de Skill → shell/curl o SQL HTTP → respuesta del modelo. El repositorio aporta instrucciones para ese recorrido; no contiene el gateway, un dispatcher propio ni una captura que pruebe su ejecución. El README del agente presenta cloud como opción principal y Ollama como alternativa; no acredita Qwen local.

Graylog consulta logs; LibreNMS resuelve primero display/sysName a hostname; Akvorado descubre exportadores y consulta flujos; gNMI expone contadores acumulados. No hay capa común de validación, autorización por IXP/POP/miembro, errores o auditoría. IDENTITY.md prescribe solo lectura, pero esa instrucción no demuestra una restricción efectiva en herramientas o cuentas.

El circuito BMP documentado es PE → pmbmpd → archivo JSON → Python con tail -F → ClickHouse `bmp_events` → SQL. Representa eventos BGP incrementales, no métricas de tráfico ni una RIB completa garantizada.

## Hallazgos priorizados

1. **Crítico: secretos en archivos.** Los Skills Graylog y LibreNMS contienen tokens literales; existe `graylog/.env` con variables sensibles. No se copiaron valores a estos entregables ni se verificó su vigencia. Revisar también los ejemplos SNMP de LibreNMS. Revocar/rotar credenciales expuestas, externalizarlas y revisar historial Git; borrar texto no revoca credenciales. No se pudo determinar qué archivos están rastreados.
2. **Alto: pérdida de datos BMP.** En `Pmacct/README.md:153–177`, POST no tiene timeout; los errores solo se imprimen y el llamador vacía el lote de todas formas. El temporizador se evalúa dentro del bucle bloqueante de lectura, por lo que un lote pequeño puede quedar pendiente sin más líneas. `except: continue` oculta errores. No hay checkpoint, confirmación durable ni recuperación de lotes.
3. **Alto: rotación BMP.** El cron conserva 100 líneas y reemplaza el archivo; no coordina con productor/consumidor. Hay riesgo de pérdida, relectura y escritura en inode anterior. Coexiste con copytruncate. Requiere reproducción controlada antes de elegir una estrategia.
4. **Alto: límites de consulta.** Skills con curl sin timeout explícito ni tratamiento uniforme de HTTP/JSON; SQL construido a partir de ejemplos; riesgo si se interpola entrada del operador. No hay límites comunes de tamaño, concurrencia o ámbito. No se halló protección explícita frente a instrucciones dentro de logs o resultados.
5. **Alto: seguridad de despliegue.** API y syslog publicados sin dirección de enlace específica; URLs HTTP en Skills; OpenSearch tiene seguridad deshabilitada dentro de la red Compose. La exposición efectiva depende del host y firewall, no inspeccionados. La guía OpenClaw sugiere desactivar sandbox para resolver conectividad y habilitar gateway en UFW sin restricción de origen.
6. **Medio: contrato y diagnóstico.** Sin procedencia normalizada, UTC validada, unidades ni estados de consulta. No hay separación implementada entre observación e hipótesis. La instrucción de diagnosticar causa raíz no garantiza evidencia suficiente.
7. **Medio: reproducibilidad.** README principal muestra carpetas inexistentes y clonado de otro remoto; Graylog usa rutas `syslog/`, plantilla `.env.example` y extractors ausentes. LibreNMS y PMACCT dependen de descargas/latest o código copiado manualmente. El Skill LibreNMS tiene una cerca de código sin cierre. `Akavorado` difiere del nombre `akvorado`; conservar compatibilidad al corregirlo.
8. **Medio: operación.** Setup Graylog supone `.env` existente; vuelve a añadir configuración sysctl. Instalar Docker actualiza el sistema completo y modifica permisos. Son scripts de aprovisionamiento, no comprobaciones inocuas.

## Línea base y límites

Se enumeraron los 19 archivos de IXP incluyendo ocultos, se leyeron documentación, Skills, Compose y scripts y se inspeccionaron las claves del entorno sin registrar valores. No se encontraron AGENTS.md aplicables dentro del workspace.

Git, Docker, Bash y Node no están disponibles en PATH. Python aparece como ejecutable, pero no fue necesario ejecutarlo para esta revisión. `git status` falló por herramienta ausente. Build/tests/lint de IXP no tienen comandos definidos en el repositorio; no se reportan como aprobados. No se ejecutó `docker compose config`, validación Bash, despliegue, instalación ni consulta a endpoints reales. El origen Git se leyó de `.git/config`; no se inspeccionó historial ni estado de cambios.

La compatibilidad de OpenClaw y los contratos API deberán contrastarse con versiones instaladas y documentación oficial antes de implementar. Esta auditoría no afirma que los ejemplos de endpoints, columnas, fórmulas o configuración sean contratos vigentes.

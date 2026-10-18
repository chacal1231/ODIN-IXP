# Plan de refactor incremental de IXP

Base: [auditoría](../architecture/CURRENT_STATE.md) y [arquitectura propuesta](../architecture/TARGET_STATE.md). Alcance ejecutado en esta entrega: análisis y documentación. No se modificaron Skills, secretos ni despliegues.

## Orden de ejecución

| Prioridad / fase | Cambio acotado | Condición de aceptación |
|---|---|---|
| P0 — Contención | Revocar/rotar tokens expuestos; externalizar secretos; añadir plantilla sin valores y reglas de exclusión; revisar historial y permisos efectivos | Ningún secreto literal en archivos distribuibles o trazas; credenciales anteriores revocadas por su administrador; acceso de consulta mínimo |
| P0 — Línea base | Capturar versión/configuración saneada de OpenClaw, backend local, API y esquema por fuente; corregir rutas de instalación | Inventario reproducible y comandos de build/test/lint documentados; distinguir comprobaciones locales y remotas |
| P1 — Regresión Graylog | Crear fixtures sintéticos y pruebas antes de sustituir curl; implementar un cliente acotado y adaptar solo ese Skill | Mismas consultas de logs; timeout, 401/403, 429, 5xx, vacío, JSON inválido y paginación probados; sin shell interpolado ni secretos en errores |
| P1 — Modelo local | Documentar y comprobar Qwen mediante el backend local elegido y OpenClaw instalado | Consulta y llamada a herramienta locales demostradas; fallo explícito si el backend cae; sin fallback cloud obligatorio |
| P2 — Evidencias | Validar contrato común y normalizar Graylog; después LibreNMS, una fuente por cambio | Fuente, alcance, fechas, unidades, referencia y estado probados; compatibilidad del Skill existente |
| P2 — Ópticas | Resolver dispositivo/interfaz y sensores; validar RX/TX y límites reales | Margen inferior = actual − mínimo; superior = máximo − actual; dBm de medición y dB de margen; sin umbral inventado; ausencias y violaciones probadas |
| P2 — PMACCT | Extraer ingester del README a archivos versionados con pruebas; confirmar esquema; corregir entrega y rotación; añadir consulta BGP de solo lectura | No vaciar lotes fallidos; flush sin nuevas líneas; recuperación tras reinicio; duplicación y lag medibles; resultados sin afirmar RIB completa |
| P3 — Akvorado e inventario | Verificar tablas/muestreo, consultas parametrizadas y cuenta SELECT; integrar IXP Manager; evaluar gNMI existente | Tráfico sin doble muestreo; filtros y ventanas acotados; asociación miembro/ASN/puerto verificable y ámbito obligatorio |
| P3 — Correlación | Implementar casos A–D, contradicciones y reporte con fuentes | Hipótesis separadas de observaciones; resultados parciales y fuentes caídas explícitos; sin causalidad injustificada |
| P4 — Operación | Documentar instalación segura, diagnóstico de fallos, rollback y métricas; añadir Oxidized/Zabbix solo según necesidad real | Procedimientos reproducibles y migración verificada; escrituras deshabilitadas por defecto |

No introducir frameworks, colas, servicios ni bases vectoriales sin necesidad demostrada. Python es candidato para clientes por el ingester ya documentado; confirmar runtime operativo antes de fijar stack o dependencias.

## Primer cambio de implementación recomendado

Tras la contención de secretos, comenzar por Graylog: conservar nombre del Skill, filtros, campos y formato visible; crear fixtures de la respuesta real saneada; probar comportamiento anterior esperado y fallos; añadir cliente de consulta; cambiar únicamente el mecanismo de ejecución. Configurar endpoint permitido externamente, autenticación por entorno, TLS o canal privado validado, timeout, límites de ventana/resultados y redacción de errores. La cuenta remota debe hacer cumplir solo lectura. No asumir una versión o endpoint hasta verificarlo.

Mantener el Skill anterior en el historial para rollback, nunca como copia con tokens. La vuelta atrás restaura el mecanismo compatible usando credenciales externas; no reintroduce credenciales comprometidas. Cambios de nombres/rutas requieren alias o procedimiento explícito de migración. No mover `Akavorado` ni reestructurar todo IXP en la primera fase.

## Pruebas y fixtures previstos

| Caso | Datos de prueba | Verificación |
|---|---|---|
| A: puerto down | Estado down, logs, tráfico por ventana y eventos BGP; variante con Graylog caído | Línea temporal y alcance del impacto observado; fuente caída visible |
| B: umbral óptico | RX/TX, mínimo/máximo, óptica, valores ausentes e incompatibles | Márgenes en dB y orden de riesgo; distinguir potencia alta/baja y falta de umbral |
| C: degradación UP | Interfaz UP, caída de tráfico, errores y RX; BGP sin cambios o contradictorio | Degradación sin inventar down ni causa confirmada |
| D: cambios BGP | Updates/retiros, peer, timestamps y miembro; ventana vacía y colector atrasado | PMACCT solo para rutas; vacío diferenciado de fuente sana y completa |

Añadir contratos por fuente para autenticación, timeout, paginación y respuestas incompletas; seguridad para shell/SQL, URLs fuera de allowlist, redirecciones, logs con prompt injection y consultas entre IXP/POP. Pruebas de IA deben comprobar afirmaciones contra fixtures, no limitarse a buscar frases del prompt.

## Dependencias y riesgos pendientes

Se necesita acceso autorizado de lectura a versiones/configuración saneada y muestras para confirmar contratos; la auditoría no requiere acceso a producción. Docker/Bash/Git faltan en PATH de este entorno. Antes de cualquier modificación operativa, establecer línea base ejecutable en un entorno compatible. No ejecutar los scripts de instalación para suplir estas herramientas durante una revisión.

La ingesta BMP escribe datos de telemetría y se separa de las credenciales SELECT del agente. Sus cambios requieren comparar conteos, pérdida, duplicación y recuperación en laboratorio antes de sustituir el proceso operativo. Toda fase termina con su comprobación y documentación de limitaciones; los casos y clientes aquí descritos todavía no están implementados.

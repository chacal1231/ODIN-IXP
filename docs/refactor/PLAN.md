# Plan de refactor de IXP — pendientes

Base: [estado actual](../architecture/CURRENT_STATE.md), [arquitectura objetivo](../architecture/TARGET_STATE.md) y [seguridad](../SECURITY.md). Este documento solo lista trabajo pendiente; lo terminado queda en el historial de Git.

## Condición de bloqueo

Hasta revocar los tokens expuestos y rotar lo indicado en [SECURITY.md](../SECURITY.md), nada se despliega contra producción con credenciales anteriores. El código puede avanzar en paralelo.

## Validación con las plataformas reales

Requiere acceso a las instalaciones. Cada punto confirma un contrato que hoy es provisional; si no coincide, el cliente falla cerrado (`invalid_response`) y hay que ajustarlo.

| Tema | Pendiente | Aceptación |
|---|---|---|
| Exposición | Comprobar que ClickHouse (`:8123`) y el endpoint de métricas gNMI no responden desde Internet sin autenticación | Sin acceso anónimo desde fuera de la red de gestión |
| OpenClaw | Instalar 2026.8.35 y registrar el digest; versionar `openclaw.json` saneado; llevar `tools/` y variables al contexto de ejecución del sandbox; restringir la ejecución a los clientes; desactivar gNMI en `skills.entries`; no ofrecer `read_api.py` como herramienta | Instalación reproducible; el agente no puede ejecutar curl/SQL arbitrario aunque un Skill lo sugiera |
| CI | Confirmar que el workflow `IXP` pasa en GitHub | Pruebas y gitleaks en verde en `main` |
| Graylog | Confirmar en el API browser `search/universal/relative`, el esquema `messages[].message`, permisos, nombres reales de `source` y HTTPS/CA desde el sandbox; consulta real con token nuevo de solo lectura | `graylog_query.py --device <PE> --seconds 300` devuelve `ok` o `empty` |
| LibreNMS | Ejecutar cada operación y comparar envelopes (`devices`, `ports`, `bgp_sessions`, `alerts`, `graphs`, `logs`); formato de `health/device_dbm` con y sin `sensor_id`; si las descripciones de sensor indican Rx/Tx | Todas las operaciones sin `invalid_response`; `optics` sin `direction_unresolved` |
| Akvorado | `DESCRIBE` de `flows`, `flows_1m0s`, `flows_5m0s`, `flows_1h0m0s` y `exporters`; confirmar que `Bytes × SamplingRate` aplica también en tablas agregadas; retención de cada tabla; cuenta readonly con perfil (`max_execution_time`, `max_rows_to_read`) | Tráfico sin doble muestreo; ventanas dentro de la retención real |
| IXP Manager | Revisar una exportación IX-F real; comprobar que la API key ve los nombres de miembro; anotar los `ixp_id` | `members` y `ips` coinciden con el inventario |
| Modelo local | Elegir Qwen y backend (Ollama, vLLM u otro) y documentar modelo, tamaño, cuantización y contexto | ≥ 9/10 llamadas correctas a herramientas en casos A–D; fallo explícito si el backend cae; sin fallback cloud obligatorio |
| PMACCT | Migración según `Pmacct/README.md` (cuenta INSERT, `BMP_INITIAL_POSITION=end`, retirar `truncate-bmp`, logrotate horario); medir la ventana de `copytruncate` o comprobar si pmbmpd reabre el archivo | Cero pérdidas en reinicio del ingester y de ClickHouse; duplicación y lag con cifras |

Para Graylog y el modelo local: probar primero en un workspace aislado. Preguntar por una interfaz de un equipo autorizado en los últimos cinco minutos; la traza debe mostrar la ejecución del cliente y una respuesta con fuente y hora. Repetir con una fuente no autorizada y con datos ausentes o contradictorios. Si el modelo no llama a la herramienta o el backend falla, la validación falla aunque la respuesta parezca convincente. No cortar servicios reales para simular fallos.

## Código

| Orden | Pendiente | Aceptación |
|---|---|---|
| 1 | Pasar a `test_*.py` las pruebas de `librenms_query` (incluida `optics`), `akvorado_query`, `ixpmanager_query`, `correlate` y el ingester BMP | El CI cubre todos los clientes |
| 2 | Cliente de lectura de PMACCT sobre `bmp_events` e integración en el caso D | Updates/retiros por peer y ventana; vacío distinto de colector atrasado; sin afirmar RIB completa |
| 3 | Mapa de nombres entre sistemas (equipo → hostname LibreNMS, source Graylog, exporter Akvorado, switch IXP Manager, IXP/POP) | `correlate.py` sin nombres pasados a mano; nombres sin mapa marcados como hueco |
| 4 | Auditoría: `query_id` en cada resultado y registro de solicitante, ámbito, fuente, duración y estado | Toda consulta trazable sin registrar secretos |
| 5 | Restricción de ejecución: lista de comandos permitidos o servidor MCP, según lo que soporte la versión instalada | El agente solo puede invocar las operaciones definidas |
| 6 | Asociación puerto físico ↔ miembro (endpoints adicionales de IXP Manager o convención en `ifAlias`) | Impacto por miembro de un puerto caído como observación, no hipótesis |
| 7 | gNMI: cliente con contadores convertidos en tasas, o retirar el Skill | Sin Skill deshabilitado indefinidamente |
| 8 | Identidad y alcance por usuario (IXP/POP por operador) | Un operador no consulta ámbitos ajenos |
| 9 | Límites de concurrencia y caché corta en correlación | Sin ráfagas de llamadas por pregunta |
| 10 | Evaluación del modelo contra fixtures: no inventar caídas, no convertir hipótesis en causa, ignorar instrucciones en logs | Afirmaciones comprobadas contra los datos, no por frases del prompt |

## Documentación y operación

- Guía única de instalación de los clientes en OpenClaw: archivos, variables, sandbox y verificación.
- README principal de IXP: estructura inexistente (`syslog/`, `monitoring/`, …), clonado de otro remoto y estados desactualizados.
- Graylog: el README usa rutas `syslog/` y un archivo de extractors que no está en el repositorio.
- Decidir si se sustituyen por marcadores las IPs y hostnames reales de la documentación de despliegue.
- Runbooks por fuente caída, rollback por componente y métricas de salud del agente.
- Oxidized y Zabbix solo con necesidad demostrada.

## Principios

No introducir frameworks, colas, servicios ni bases vectoriales sin necesidad demostrada. Los clientes usan Python 3 de la biblioteca estándar; confirmar el runtime del sandbox antes de añadir dependencias. Escrituras y cambios de configuración desde el agente, deshabilitados por defecto.

# Estado actual de IXP

Actualizado: 2026-10-18. Alcance: repositorio `chacal1231/ODIN-IXP`; el proyecto ISP (`chacal1231/ODIN-ISP`) queda fuera. Lo pendiente está en el [plan](../refactor/PLAN.md).

## Inventario

| Componente | Archivos | Estado |
|---|---|---|
| Graylog | `graylog/docker-compose.yml`, scripts de setup, README, guía de PEs | Despliegue versionado; Web/API en `127.0.0.1` por defecto |
| Consulta Graylog | `tools/graylog_query.py`, Skill Graylog | Cliente estructurado con allowlist; contrato `search/universal/relative` sin confirmar contra la instalación |
| LibreNMS | `LibreNMS/LibreNMS.md` (versión 26.9.1.1 fijada), `tools/librenms_query.py`, Skill LibreNMS | Cliente con operaciones enumeradas, ópticas con márgenes en dB; envelopes sin confirmar |
| Akvorado | `tools/akvorado_query.py`, Skill Akavorado | Plantillas SQL cerradas; esquema, retención y cuenta readonly sin confirmar |
| IXP Manager | `tools/ixpmanager_query.py`, Skill IXPManager | Inventario desde IX-F 1.0; sin nombres de puerto físico |
| Correlación | `tools/correlate.py`, Skill Correlacion | Casos A–D sobre LibreNMS, Graylog, Akvorado e IXP Manager; caso D sin PMACCT |
| PMACCT | `Pmacct/` (Compose, ingester, configuración, logrotate) | Ingesta at-least-once con checkpoint; sin migrar ni validar en laboratorio; sin cliente de lectura |
| gNMI | Skill Gnmi | Deshabilitado; sin cliente |
| OpenClaw | README (versión 2026.8.35 e instalación de Skills y clientes), IDENTITY.md, USER.md, `.openclaw` (solo contiene la ruta `/root/.openclaw`) | Configuración instalada no versionada; ejecución de comandos sin restringir |
| Qwen local | — | Sin configuración |
| Zabbix / Oxidized | — | Ausentes; Oxidized solo como intención en el README |
| CI | `.github/workflows/ixp.yml` | Pruebas de `read_api` y `graylog_query`, y gitleaks |

Las afirmaciones de «producción» de los README son antecedentes documentales. Ninguna integración se ha verificado de extremo a extremo.

## Recorrido de una pregunta

Operador → Telegram/Control UI → OpenClaw → modelo → Skill → `python3 tools/<cliente>.py …` → `read_api.py` → fuente → JSON con contrato (`status`, `evidence`, `warnings`) → respuesta del modelo. Los clientes validan argumentos, aplican allowlists y normalizan unidades y horas antes de que el modelo vea los datos.

El circuito BMP es PE → pmbmpd → archivo JSON → `bmp_ingester.py` → ClickHouse `bmp_events`. Son eventos BGP incrementales, no una RIB completa.

## Hallazgos abiertos

1. **Crítico: credenciales expuestas.** Siguen en el historial publicado y accesibles por SHA en GitHub hasta su revocación y purga. Ver [SECURITY.md](../SECURITY.md).
2. **Alto: ejecución sin restringir.** El agente necesita ejecución de comandos para lanzar los clientes; mientras no se limite, podría usar curl u otras herramientas aunque los Skills lo prohíban.
3. **Alto: contratos provisionales.** Formatos de Graylog, LibreNMS, ClickHouse e IXP Manager tomados de documentación pública, sin contrastar con las instalaciones.
4. **Alto: exposición de servicios.** ClickHouse por HTTP en una IP pública y el endpoint de métricas gNMI, a verificar desde fuera. OpenSearch sin autenticación en la red interna de Compose. La exposición efectiva depende del host y del firewall, no inspeccionados.
5. **Medio: sin auditoría ni identidad.** Las consultas no llevan `query_id` ni registro de solicitante; las allowlists son por herramienta, no por usuario.
6. **Medio: reproducibilidad.** Extractors, streams y alertas de Graylog se configuran en la UI y no están versionados; las expresiones documentadas no se han probado con mensajes reales. La configuración instalada de OpenClaw (`openclaw.json`) no está versionada. La carpeta `Akavorado` difiere de `akvorado`; conservar compatibilidad al corregirlo.
7. **Medio: operación.** Instalar Docker actualiza el sistema completo y añade el usuario al grupo docker; son scripts de aprovisionamiento, no comprobaciones inocuas. Setup y Compose solo se han revisado estáticamente.
8. **Medio: cobertura de pruebas.** El CI no cubre LibreNMS, Akvorado, IXP Manager, la correlación ni el ingester BMP.

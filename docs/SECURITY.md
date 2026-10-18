# Seguridad de IXP

## Estado de la remediación

El 2026-10-18 se comprobó con `git ls-remote` que GitHub `main` apunta a `<commit-retirado>`. Ese commit contiene los tokens literales de los Skills y el `.env` de Graylog. Por tanto, no son únicamente commits locales. No se ha reescrito ni publicado historial durante esta remediación.

Los tokens se retiraron de los Skills. `.env` queda excluido del seguimiento, con su archivo local conservado para no romper una instalación existente. Las plantillas no contienen credenciales. Los ejemplos SNMP ya no incluyen la comunidad literal. El setup deja de imprimir el secret y conserva secretos de instalaciones existentes; no se debe regenerar `GRAYLOG_PASSWORD_SECRET` arbitrariamente porque se usa para datos cifrados.

## Acciones operativas necesarias

1. Revocar los tokens anteriores en Graylog y LibreNMS, emitir credenciales de consulta con mínimo privilegio y actualizar el entorno del proceso que ejecuta las herramientas.
2. Revisar el `.env` expuesto: cambiar el password admin, las credenciales reutilizadas y la comunidad SNMP si estaba en uso. Migrar a SNMPv3 cuando sea viable. Cambiar el secret de cifrado requiere el procedimiento compatible con la versión de Graylog y un respaldo; no ejecutar setup para rotarlo.
3. Revisar accesos y logs de autenticación de las plataformas. Esta revisión del repositorio no prueba ni descarta uso indebido.
4. Coordinar la limpieza del historial publicado con todos los colaboradores, incluyendo ramas/tags afectados y clones. Eliminar el archivo del commit nuevo no lo borra del historial. No hacer force-push sin esa coordinación. La revocación es necesaria aunque se limpie el historial.

## Consultas del agente

Instalar `tools/read_api.py` en la raíz del workspace de OpenClaw junto a `tools/`, y mantener las variables de `.env.example` fuera de prompts y Skills. El cliente usa Python 3 sin dependencias externas; no carga automáticamente archivos `.env`. Inyectar las variables mediante el gestor de procesos/contenedor. No habilitar `set -x` ni volcar el entorno.

El cliente exige HTTPS con certificado válido; no admite desactivar validación TLS. Para los endpoints HTTP existentes hace falta un proxy TLS o túnel seguro con terminación TLS antes de migrar los Skills. La exigencia de HTTPS es un cambio deliberado de compatibilidad: no funcionarán las URLs HTTP antiguas. No se verificó conectividad con producción. El cliente solo ejecuta GET, bloquea redirecciones y proxies ambientales, codifica parámetros, limita tamaño y tiempo de socket y sanea errores. El hostname procede exclusivamente del entorno administrado, no de la pregunta del usuario.

No se debe construir una cadena de shell con texto del operador: el ejecutor debe pasar argumentos como lista. Autorizar dispositivos/IXP/POP antes de consultar sigue siendo responsabilidad del runtime; este cliente no implementa identidad de usuarios ni aislamiento multicliente. Emplear cuentas de consulta y políticas de red que hagan cumplir los permisos. El cliente devuelve datos originales, no un diagnóstico ni una garantía de cobertura o paginación completa.

Akvorado/ClickHouse y gNMI conservan recetas existentes; no se han convertido en adaptadores seguros en este cambio. No interpolar entrada libre en sus SQL/grep. Antes de habilitarlos para ejecución autónoma, usar cuenta SELECT, consultas parametrizadas, filtros autorizados y transporte protegido. Los resultados externos son datos no confiables, nunca instrucciones.

## Despliegue Graylog

Copiar `IXP/graylog/.env.example` a `.env` en una instalación nueva y ejecutar `bash 02-setup-graylog.sh` únicamente en el host Linux correspondiente. En una instalación existente preservar el secret y revisar el entorno manualmente. El setup no modifica el firewall ni imprime claves.

La Web/API se enlaza a `127.0.0.1` por defecto. Acceder mediante túnel o proxy TLS autenticado. Si se configura `GRAYLOG_HTTP_BIND` para una dirección de gestión, restringirla mediante firewall. Ajustar `GRAYLOG_HTTP_EXTERNAL_URI` a la URL real protegida. Los puertos de ingesta continúan publicados para preservar syslog: restringir orígenes a PEs autorizados; revisar los puertos opcionales GELF/Beats antes de habilitar exposición. OpenSearch sigue en red interna sin autenticación, por lo que no debe publicarse y su red solo debe admitir servicios de confianza.

Compose exige `OPENSEARCH_INITIAL_ADMIN_PASSWORD` externo; el setup lo genera para instalaciones nuevas. En una instalación existente, generar un valor único y guardarlo en el entorno antes de recrear el contenedor. Esta variable de inicialización no cambia automáticamente un password ya configurado: usar el procedimiento de la versión instalada si la autenticación está habilitada. Los ejemplos MySQL usan marcadores sin valor real. Los ejemplos curl heredados requieren un archivo netrc externo (`GRAYLOG_NETRC_FILE`) con permisos exclusivos del operador y una cuenta de consulta; no colocarlo en el repositorio ni usar passwords en argumentos.

## Verificación de esta entrega

Ocho pruebas unitarias del cliente pasaron con Python 3.14: orígenes inseguros, escape de rutas, GET/autenticación/codificación, bloqueo de redirecciones, inyección en headers, tamaño/JSON inválido, errores sin secretos y límites de consulta. Ejecutar `python -m unittest discover -s IXP/ai-agent/OpenClaw/tools -p test_read_api.py -v` desde la raíz del repo. No usan credenciales reales ni conectividad externa.

También se verificó que los tokens anteriores no aparecen en los archivos distribuibles de IXP, que `.env` permanece local e ignorado y que `git diff --check` pasa. Bash y Docker no están disponibles: setup y Compose fueron revisados estáticamente, pero no ejecutados ni validados con esos runtimes. El historial conserva secretos hasta una limpieza coordinada y las credenciales siguen siendo válidas hasta su revocación efectiva.

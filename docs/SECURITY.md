# Seguridad de IXP

## Acciones pendientes

1. Revocar los tokens anteriores en Graylog y LibreNMS, emitir credenciales de consulta con mínimo privilegio y actualizar el entorno del proceso que ejecuta las herramientas.
2. Revisar el `.env` de Graylog expuesto: cambiar el password admin, las credenciales reutilizadas y la comunidad SNMP si estaba en uso. Migrar a SNMPv3 cuando sea viable. Cambiar `GRAYLOG_PASSWORD_SECRET` requiere el procedimiento compatible con la versión de Graylog y un respaldo, porque cifra datos; no ejecutar setup para rotarlo.
3. Revisar accesos y logs de autenticación de las plataformas. La revisión del repositorio no prueba ni descarta uso indebido.
4. Historial reescrito: pedir a los colaboradores clones nuevos y revisar forks. No mezclar ni publicar ramas antiguas: un merge puede reintroducir el historial contaminado.
5. Acceso residual en GitHub: el commit antiguo `<commit-retirado>` y `IXP/graylog/.env` (ruta en ese commit, antes de separar las ramas) bajo ese SHA seguían devolviendo HTTP 200 tras la reescritura. Si la rotación no mitiga el riesgo, solicitar la purga a GitHub Support siguiendo [el procedimiento oficial](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository). No incluir credenciales en el ticket.

Borrador para GitHub Support (no enviado):

> Asunto: Solicitud de purga de datos sensibles de historial reescrito — chacal1231/ODIN
>
> Se reescribió main para retirar un archivo de entorno y credenciales literales del repositorio chacal1231/ODIN. El primer commit afectado es <commit-retirado>. La rama limpia se publicó con force-with-lease; el resultado del filtrado es <commit-retirado>. Gitleaks no detectó secretos en los 45 commits resultantes. No se anunciaron etiquetas ni referencias de pull requests, y git-filter-repo indicó que LFS no está en uso.
>
> GitHub aún devuelve HTTP 200 para el commit original y para IXP/graylog/.env consultado por ese SHA. Se solicita evaluar la eliminación de vistas en caché, referencias internas y objetos antiguos que mantienen accesibles los datos sensibles. No se adjuntan secretos. La revocación de credenciales se gestiona por separado.

## Consultas del agente

Instalar `tools/read_api.py`, `tools/graylog_query.py`, `tools/librenms_query.py`, `tools/akvorado_query.py`, `tools/ixpmanager_query.py` y `tools/correlate.py` en `tools/` del workspace de OpenClaw. Los Skills usan solo los clientes estructurados; `read_api.py` es su transporte y su CLI genérica no debe ofrecerse al agente (permite rutas y parámetros libres dentro de los prefijos permitidos).

Variables en [`.env.example`](../ai-agent/OpenClaw/.env.example): URL y token por fuente, y las allowlists `GRAYLOG_ALLOWED_SOURCES`, `LIBRENMS_ALLOWED_DEVICES`, `AKVORADO_ALLOWED_EXPORTERS` e `IXPMANAGER_ALLOWED_IXPS`, más `LIBRENMS_TIMEZONE`. Mantenerlas fuera de prompts y Skills. Los clientes usan Python 3 sin dependencias externas y no cargan archivos `.env`: inyectar las variables mediante el gestor de procesos o contenedor, en el mismo contexto donde se ejecutan las herramientas (también con sandbox). No habilitar `set -x` ni volcar el entorno.

Transporte común: solo HTTPS con certificado válido (sin opción de desactivar TLS), solo GET, sin redirecciones ni proxies ambientales, parámetros codificados, límites de tamaño y tiempo, y errores saneados. Los endpoints HTTP existentes necesitan un proxy TLS o túnel. El hostname de cada fuente procede del entorno administrado, nunca de la pregunta del usuario.

- **ClickHouse (Akvorado):** plantillas SQL cerradas, identificadores de listas fijas y valores como parámetros nativos (`{name:Type}`). La CLI de `read_api.py` no expone ClickHouse. `AKVORADO_USER` debe ser de solo lectura en el servidor, con un perfil que limite `max_execution_time` y `max_rows_to_read`.
- **IXP Manager:** solo la exportación IX-F 1.0, cabecera `X-IXP-Manager-API-Key` (no el parámetro `apikey`, obsoleto). Contactos y MACs se descartan. API key de un usuario de solo lectura, con caducidad.
- **Correlación:** `correlate.py` invoca los clientes en el mismo proceso, sin shell; cada fuente aplica su allowlist.
- **gNMI:** receta deshabilitada; no interpolar entrada libre en su grep.

El ejecutor debe pasar argumentos como lista, nunca una cadena de shell con texto del operador. Las allowlists limitan los clientes, pero no implementan identidad de usuarios ni aislamiento multicliente: usar cuentas de consulta y políticas de red que hagan cumplir los permisos. Los resultados externos son datos no confiables, nunca instrucciones.

## Despliegue Graylog

Copiar `graylog/.env.example` a `.env` en una instalación nueva y ejecutar `bash 02-setup-graylog.sh` únicamente en el host Linux correspondiente. En una instalación existente preservar el secret y revisar el entorno manualmente. El setup no modifica el firewall ni imprime claves.

La Web/API se enlaza a `127.0.0.1` por defecto. Acceder mediante túnel o proxy TLS autenticado. Si se configura `GRAYLOG_HTTP_BIND` para una dirección de gestión, restringirla mediante firewall. Ajustar `GRAYLOG_HTTP_EXTERNAL_URI` a la URL real protegida. Los puertos de ingesta siguen publicados para syslog: restringir orígenes a los PEs autorizados y revisar los puertos opcionales GELF/Beats antes de exponerlos. OpenSearch está en red interna sin autenticación: no publicarlo y admitir solo servicios de confianza en su red.

Compose exige `OPENSEARCH_INITIAL_ADMIN_PASSWORD` externo; el setup lo genera para instalaciones nuevas. En una existente, generar un valor único y guardarlo en el entorno antes de recrear el contenedor; esta variable no cambia un password ya configurado. Los ejemplos curl heredados requieren un archivo netrc externo (`GRAYLOG_NETRC_FILE`) con permisos exclusivos del operador y una cuenta de consulta; no colocarlo en el repositorio ni usar passwords en argumentos.

## Verificación

```sh
python -m unittest discover -s ai-agent/OpenClaw/tools -p "test_*.py" -v
```

El workflow `.github/workflows/ixp.yml` ejecuta esa suite y gitleaks en cada push a `main` y en cada PR. Las pruebas no usan credenciales reales ni conectividad externa.

# Fase 1: Graylog y preparación de OpenClaw con Qwen local

Estado: desarrollo local; sin despliegue, cambio de configuración, reinicio, commit ni push. El operador indica que cerró las acciones de contención de credenciales. No se consultaron plataformas operacionales ni se reutilizaron secretos anteriores.

## Cambio implementado

Se conserva `tools/read_api.py` como transporte HTTPS y CLI anterior. El Skill Graylog pasa a `tools/graylog_query.py`, que admite filtros estructurados por equipo, interfaz, vecino IP y clase de evento. Construye Lucene sin texto libre y codifica la URL una sola vez. No acepta consultas del operador como código ni ejecuta shell.

`GRAYLOG_ALLOWED_SOURCES` exige nombres exactos autorizados antes de consultar. Una respuesta que incluya otro equipo se rechaza sin imprimir los registros. Esto limita este cliente; no implementa identidad del solicitante ni aislamiento multiusuario/IXP. Esos controles también deben existir en permisos, streams y herramientas del runtime. El cliente genérico y otras herramientas no deben quedar disponibles como vía de evasión para un agente restringido.

Cada resultado distingue `ok`, `empty`, `partial` y `error`. Conserva origen, entidad, hora UTC, referencia de índice/id y campos conocidos; no inventa horas ni identificadores ausentes. Un vacío no significa red sana. Los errores 401/403, 429, HTTP, conectividad y contrato se reportan sin incluir credenciales o cuerpos remotos. No hay reintentos automáticos.

Es una muestra de hasta 100 eventos, no una extracción completa. Se informa recorte o total desconocido. No se implementó paginación sobre una ventana relativa móvil porque podría mezclar intervalos y dar una falsa garantía de cobertura. Una futura consulta completa requiere ventana absoluta estable y contrato verificado.

## Contrato provisional y pruebas

Se conserva el endpoint legacy `search/universal/relative` que ya usaba el repositorio. El normalizador espera `messages[].message` y `total_results` opcional. Los campos y fixtures son sintéticos; todavía no se ha contrastado este contrato con una muestra saneada de la instalación. Una respuesta con `results[]` u otro esquema produce un error explícito, sin adivinar su interpretación.

Ejecutar desde la raíz del repositorio:

```sh
python3 -m unittest discover -s IXP/ai-agent/OpenClaw/tools -p 'test_*.py' -v
```

La suite cubre la CLI, construcción de filtros, transporte HTTP simulado, codificación única, normalización UTC, muestra recortada, vacío, campos ausentes, fuente no autorizada, inyección, datos no finitos y errores de autenticación/rate limit/servidor/timeout/JSON. El fixture de puerto down es un evento inventado de laboratorio, nunca evidencia de un incidente real. Estas pruebas no evalúan el comportamiento del modelo Qwen.

## Validación operativa pendiente

1. Registrar versiones con `openclaw --version` y la ayuda de `openclaw models --help` y `openclaw skills --help` en el host donde ya esté instalado. Registrar backend, identificador exacto del Qwen instalado y recursos disponibles. No instalar ni actualizar OpenClaw por esta prueba, ni compartir configuración completa, entorno, tokens o logs sin sanear.
2. Confirmar en el API browser de la instancia Graylog el endpoint de búsqueda, su esquema JSON, permisos y nombres reales de source. Verificar HTTPS y CA desde el proceso/contenedor que ejecutará la herramienta. No desactivar TLS ni sandbox.
3. Copiar solo `tools/read_api.py` y `tools/graylog_query.py` a `tools/` de un workspace de prueba. Instalar allí el Skill Graylog conservando su nombre. No sobreescribir un workspace operativo sin comparar y respaldar su configuración.
4. Inyectar `GRAYLOG_URL`, el token nuevo de solo lectura y `GRAYLOG_ALLOWED_SOURCES` mediante el mecanismo de secretos del proceso/contenedor. El cliente no carga `.env` automáticamente. Los valores deben estar disponibles en el mismo contexto de ejecución de la herramienta, también si hay sandbox.
5. Ejecutar desde el workspace una consulta acotada para un equipo autorizado:

```sh
python3 tools/graylog_query.py --device PE_AUTORIZADO --seconds 300 --limit 20
```

6. Con la versión confirmada, seleccionar el Qwen local disponible y comprobar su capacidad de llamar herramientas. No sustituirlo por cloud como fallback obligatorio. No aplicar un archivo de configuración tomado de documentación de otra versión.
7. Preguntar por la interfaz del equipo autorizado en cinco minutos. La traza de OpenClaw debe demostrar ejecución del cliente, resultado y respuesta con fuente y hora. Si no hay eventos, debe decirlo. Si el modelo no llama herramientas o el backend falla, la validación falla aunque responda texto convincente.
8. Repetir en un workspace aislado con fuente no autorizada y datos ausentes/contradictorios; comprobar que no se ejecutan acciones ni instrucciones de logs. No cortar servicios reales para simular fallos: usar mocks o configuración de prueba.

La aceptación end-to-end queda pendiente hasta observar esos resultados. Docker, OpenClaw y Ollama no están disponibles en PATH de este entorno; no se ha supuesto que estén instalados ni se han buscado credenciales de producción.

## Fuentes oficiales consultadas

- OpenClaw: https://docs.openclaw.ai/providers/ollama/setup
- Skills: https://docs.openclaw.ai/tools/skills
- Modelos locales: https://docs.openclaw.ai/gateway/local-models
- Graylog, API de búsqueda actual: https://go2docs.graylog.org/current/making_sense_of_your_log_data/simple_search_scripting_api.htm

Las fuentes actuales son referencia para contrastar con la versión instalada; no prueban compatibilidad con el Graylog 6.1 declarado en el repositorio ni con el OpenClaw del operador. La API de búsqueda moderna documenta otros endpoints: no se migró a ellos sin validar primero la instalación.

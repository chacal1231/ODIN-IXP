# OpenClaw para IXP — instalación del agente y de los Skills

Guía para desplegar OpenClaw con Docker y Telegram, e instalar los Skills y clientes de consulta de IXP. Antes de empezar, leer [docs/SECURITY.md](../../docs/SECURITY.md).

## Requisitos previos

- **Sistema operativo:** Ubuntu 22.04 / 24.04 (o cualquier Linux con Docker)
- **RAM:** mínimo 2 GB para OpenClaw; el modelo local necesita aparte la memoria de su backend
- **Disco:** 10 GB libres más el tamaño del modelo
- **Docker y Docker Compose**
- **Backend de modelo local** (Ollama u otro) con un modelo Qwen. Un proveedor cloud solo si se decide explícitamente; no es fallback obligatorio
- **Cuenta de Telegram** para el bot
- **Python 3** en el contexto de ejecución de herramientas de OpenClaw (los clientes no tienen otras dependencias)

---

## 1. Instalar Docker (si no está instalado)

```bash
sudo apt update && sudo apt upgrade -y      # actualiza todo el sistema
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER               # equivale a acceso root vía Docker
docker --version && docker compose version
```

Cerrar sesión y volver a entrar para que aplique el grupo `docker`.

---

## 2. Clonar OpenClaw en la versión fijada

Versión para IXP: **2026.8.35** (línea `extended-stable`, el equivalente a LTS de OpenClaw; publicada el 2026-10-02). Clonar ese tag, no `main`:

```bash
cd /opt
git clone --branch v2026.8.35 --depth 1 https://github.com/openclaw/openclaw.git
cd openclaw
```

---

## 3. Setup

### Opción A: imagen pre-construida (recomendada)

```bash
export OPENCLAW_IMAGE="ghcr.io/openclaw/openclaw:2026.8.35"
./scripts/docker/setup.sh
```

No usar los tags `main`, `latest` ni `extended-stable`: se mueven, y los Skills y el sandbox se validan contra una versión concreta. Tras el primer pull, registrar el digest junto a la configuración saneada:

```bash
docker image inspect --format '{{index .RepoDigests 0}}' ghcr.io/openclaw/openclaw:2026.8.35
```

### Opción B: build local desde el tag clonado

```bash
./scripts/docker/setup.sh
```

El script construye la imagen, ejecuta el onboarding, genera un token de gateway en `.env` e inicia el gateway con Docker Compose.

### Actualizar

Pasar al siguiente parche de la línea `extended-stable` (por ejemplo 2026.9.33) con al menos dos semanas de publicación, validarlo en laboratorio con los casos A–D y solo después cambiar `OPENCLAW_IMAGE` en producción.

---

## 4. Onboarding

El wizard pide:

- **Proveedor de modelo:** elegir el backend local (Ollama u otro). La configuración del modelo se detalla en la sección 6.
- **Canal:** Telegram.

---

## 5. Telegram

### 5.1 Crear el bot

1. En Telegram, abrir `@BotFather` y enviar `/newbot`.
2. Elegir nombre y un username terminado en `bot`.
3. Guardar el token en el gestor de secretos.

### 5.2 Añadir el token

```bash
docker compose run --rm openclaw-cli channels add --channel telegram --token "<TU_BOT_TOKEN>"
```

O en `~/.openclaw/openclaw.json`:

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "botToken": "<TU_BOT_TOKEN>",
      "dmPolicy": "pairing",
      "streaming": "partial"
    }
  }
}
```

No versionar `openclaw.json` con el token; para el repositorio, guardar una copia saneada.

### 5.3 Parear la cuenta

1. Escribir al bot; responde con un código de pairing.
2. Aprobarlo:

```bash
docker compose run --rm openclaw-cli pairing approve telegram <CODIGO>
```

`dmPolicy: "pairing"` exige aprobación manual de cada cuenta.

---

## 6. Modelo local (Qwen)

El modelo principal es un Qwen servido localmente. Configurarlo según la documentación de proveedores de la versión instalada (https://docs.openclaw.ai/gateway/local-models y https://docs.openclaw.ai/providers/ollama/setup); no copiar configuración de otra versión. Esquema orientativo en `~/.openclaw/openclaw.json`:

```json
{
  "agents": {
    "defaults": {
      "model": {
        "primary": "ollama/<MODELO_QWEN>"
      }
    }
  }
}
```

Documentar en el plan el modelo exacto, tamaño, cuantización, contexto y backend. Criterio de aceptación: al menos 9 de 10 llamadas correctas a herramientas en los casos A–D, y error explícito si el backend cae. El gateway recarga el JSON automáticamente en la mayoría de cambios.

---

## 7. Skills y clientes de IXP

### 7.1 Copiar al workspace

Desde la raíz del repositorio ODIN:

```bash
WS=~/.openclaw/workspace
mkdir -p "$WS/skills" "$WS/tools"
cp -r ai-agent/OpenClaw/Skills/{Graylog,LibreNMS,Akavorado,IXPManager,Correlacion} "$WS/skills/"
cp ai-agent/OpenClaw/tools/{read_api,graylog_query,librenms_query,akvorado_query,ixpmanager_query,correlate}.py "$WS/tools/"
cp ai-agent/OpenClaw/IDENTITY.md ai-agent/OpenClaw/USER.md "$WS/"
```

No copiar el Skill `Gnmi` (deshabilitado), las pruebas ni `fixtures/`. Los comandos de los Skills se ejecutan desde la raíz del workspace (`python3 tools/...`).

### 7.2 Variables de entorno

Partir de [`.env.example`](.env.example) y definir, por fuente, URL (HTTPS), token y allowlist:

| Fuente | Variables |
|---|---|
| Graylog | `GRAYLOG_URL`, `GRAYLOG_TOKEN`, `GRAYLOG_ALLOWED_SOURCES` |
| LibreNMS | `LIBRENMS_URL`, `LIBRENMS_TOKEN`, `LIBRENMS_ALLOWED_DEVICES`, `LIBRENMS_TIMEZONE` |
| Akvorado (ClickHouse) | `AKVORADO_URL`, `AKVORADO_USER`, `AKVORADO_TOKEN`, `AKVORADO_ALLOWED_EXPORTERS` |
| IXP Manager | `IXPMANAGER_URL`, `IXPMANAGER_TOKEN`, `IXPMANAGER_ALLOWED_IXPS` |

Los clientes no leen archivos `.env`: inyectar las variables con el mecanismo de secretos del contenedor, en el mismo contexto donde OpenClaw ejecuta las herramientas (también si hay sandbox). Las credenciales deben ser de solo lectura. Una fuente sin configurar devuelve `error` y el agente la reporta como no disponible.

### 7.3 Habilitar en `openclaw.json`

```json
{
  "skills": {
    "entries": {
      "graylog": { "enabled": true },
      "librenms": { "enabled": true },
      "akvorado": { "enabled": true },
      "ixpmanager": { "enabled": true },
      "correlacion": { "enabled": true },
      "gnmic_metrics": { "enabled": false }
    }
  }
}
```

### 7.4 Restringir la ejecución

Los clientes solo protegen si son la única vía: limitar la herramienta de ejecución de OpenClaw a `python3 tools/<cliente>.py` (sin `read_api.py`), según las opciones de la versión instalada. Mantener el sandbox activo y autorizar en la política de red solo los endpoints de las fuentes.

### 7.5 Verificar

Desde la raíz del workspace, con las variables cargadas:

```bash
python3 tools/librenms_query.py devices --limit 5
python3 tools/graylog_query.py --device <PE_AUTORIZADO> --seconds 300 --limit 5
python3 tools/akvorado_query.py exporters
python3 tools/ixpmanager_query.py members --limit 5
```

Cada comando imprime un único JSON; `status: error` indica configuración o conectividad pendiente. Después, preguntar al bot por una interfaz de un equipo autorizado y comprobar en la traza que ejecutó el cliente y citó fuente y hora.

### 7.6 Escribir o modificar Skills

Formato de `SKILL.md`:

```markdown
---
name: mi-skill
description: Cuándo usar este skill. El agente decide con esta descripción.
---

# Título

REGLA: ejecutar el cliente ANTES de responder. Nunca inventar datos.

## Comando
python3 tools/<cliente>.py OPERACION [argumentos]

## Resultados
Cómo interpretar status, evidence y warnings.
```

Reglas para Skills de IXP: invocar solo clientes de `tools/` con argumentos estructurados; nunca curl, SQL o Lucene escritos por el modelo; ningún token, IP de servidor ni hostname de infraestructura en el Skill; explicar qué significan `empty`, `partial` y `error`.

---

## 8. Estructura del workspace

```
~/.openclaw/
├── openclaw.json          # Configuración principal (no versionar con secretos)
├── .env                   # Token del gateway (generado por el setup)
├── workspace/
│   ├── IDENTITY.md        # Instrucciones del agente ODIN
│   ├── USER.md            # Perfil del usuario
│   ├── skills/
│   │   ├── Graylog/SKILL.md
│   │   ├── LibreNMS/SKILL.md
│   │   ├── Akavorado/SKILL.md
│   │   ├── IXPManager/SKILL.md
│   │   └── Correlacion/SKILL.md
│   └── tools/             # Clientes de consulta
└── agents/main/sessions/  # Historial de sesiones
```

---

## 9. Comandos útiles

```bash
docker compose ps                                  # estado
docker compose logs -f openclaw-gateway            # logs
docker compose restart openclaw-gateway            # reiniciar
docker compose run --rm openclaw-cli <comando>     # CLI
docker compose run --rm openclaw-cli config get    # configuración actual
docker compose run --rm openclaw-cli doctor        # diagnóstico
docker compose down                                # detener
```

Para actualizar, cambiar `OPENCLAW_IMAGE` a la nueva versión fijada, validarla en laboratorio y luego `docker compose pull && docker compose up -d`.

### ClawDock helpers (opcional)

Descargar los helpers del mismo tag que la versión instalada, no de `main`, y revisarlos antes de cargarlos:

```bash
mkdir -p ~/.clawdock
curl -fsSL -o ~/.clawdock/clawdock-helpers.sh \
  https://raw.githubusercontent.com/openclaw/openclaw/v2026.8.35/scripts/shell-helpers/clawdock-helpers.sh
less ~/.clawdock/clawdock-helpers.sh
echo 'source ~/.clawdock/clawdock-helpers.sh' >> ~/.bashrc
```

---

## 10. Seguridad

- No exponer el gateway sin autenticación; el token de `.env` protege el Control UI (`http://127.0.0.1:18789/`).
- Control UI y health checks (`/healthz`, `/readyz`) solo en localhost o por túnel.
- En un VPS, firewall con origen restringido:

```bash
sudo ufw allow 22
sudo ufw allow from <IP_ADMINISTRACION> to any port 18789 proto tcp
sudo ufw enable
```

- Revisar la configuración:

```bash
docker compose run --rm openclaw-cli security audit
docker compose run --rm openclaw-cli doctor
```

---

## 11. Troubleshooting

| Problema | Solución |
|---|---|
| Bot no responde en Telegram | Verificar `botToken`, reiniciar el gateway y revisar logs |
| Pairing no funciona | `docker compose run --rm openclaw-cli pairing list` para ver pendientes |
| Polling stall en Telegram | Se recupera solo; si persiste, reiniciar el gateway |
| «tools.profile (coding) allowlist contains unknown entries» | Aviso conocido con algunos modelos; no afecta |
| El agente responde sin ejecutar el cliente | Revisar que el Skill esté habilitado y la descripción encaje con la pregunta; medir el modelo local con los casos A–D; si no llama herramientas de forma fiable, cambiar de modelo, no relajar las reglas |
| Un cliente devuelve `invalid_configuration_or_filter` | Falta una variable, la URL no es HTTPS o el equipo no está en la allowlist |
| Un cliente devuelve `connection_or_timeout` | Política de red del sandbox o firewall: autorizar solo ese endpoint; mantener el sandbox activo |
| Un cliente devuelve `invalid_response` | El formato de la fuente no coincide con el contrato; revisar con el plan antes de ajustar el cliente |
| Se agota el contexto | Reducir `--limit` y la ventana de consulta; usar `correlate.py` en lugar de varias consultas sueltas |

---

## Referencias

- Documentación oficial: https://docs.openclaw.ai
- Docker: https://docs.openclaw.ai/install/docker
- Configuración: https://docs.openclaw.ai/gateway/configuration
- Modelos locales: https://docs.openclaw.ai/gateway/local-models
- Skills: https://docs.openclaw.ai/tools/skills
- GitHub: https://github.com/openclaw/openclaw

# Guía de Instalación — OpenClaw con Docker + Telegram + Skills Personalizados

> Seguridad: para los Skills de IXP, seguir [SECURITY.md](../../docs/SECURITY.md). Instalar `tools/` en la raíz del workspace y suministrar secretos por entorno. Las recetas curl de esta guía son ejemplos históricos; no usarlas para introducir credenciales ni texto del operador en shell. El cliente de consulta nuevo requiere HTTPS y Python 3.

## Requisitos Previos

- **Sistema operativo**: Ubuntu 22.04 / 24.04 (o cualquier Linux con Docker)
- **RAM**: mínimo 2 GB (recomendado 4 GB)
- **Disco**: 10 GB+ libres
- **Docker y Docker Compose** instalados
- **API Key de OpenAI** (u otro proveedor LLM)
- **Cuenta de Telegram** para crear un bot

---

## 1. Instalar Docker (si no lo tienes)

```bash
# Actualizar paquetes
sudo apt update && sudo apt upgrade -y

# Instalar Docker
curl -fsSL https://get.docker.com | sh

# Agregar tu usuario al grupo docker
sudo usermod -aG docker $USER

# Verificar instalación
docker --version
docker compose version
```

> Cierra sesión y vuelve a entrar para que el grupo docker aplique.

---

## 2. Clonar el repositorio de OpenClaw

```bash
cd /opt
git clone https://github.com/openclaw/openclaw.git
cd openclaw
```

---

## 3. Ejecutar el script de setup

### Opción A: Build local (recomendado)

```bash
./scripts/docker/setup.sh
```

Esto hace automáticamente:
- Construye la imagen Docker desde el Dockerfile
- Ejecuta el wizard de onboarding
- Genera un token de gateway y lo escribe en `.env`
- Inicia el gateway via Docker Compose

### Opción B: Usar imagen pre-construida

```bash
export OPENCLAW_IMAGE="ghcr.io/openclaw/openclaw:latest"
./scripts/docker/setup.sh
```

Las imágenes pre-construidas están en GitHub Container Registry con tags: `main`, `latest`, o versión específica (ej: `2026.3.13`).

### Opción C: Build manual paso a paso

```bash
docker build -t openclaw:local -f Dockerfile .
docker compose run --rm openclaw-cli onboard
docker compose up -d openclaw-gateway
```

---

## 4. Wizard de Onboarding

El script lanza un wizard interactivo que te pedirá:

### 4.1 Proveedor de modelo (LLM)

Selecciona tu proveedor y pega tu API Key:

| Proveedor | Variable | Modelos recomendados |
|---|---|---|
| OpenAI | `OPENAI_API_KEY` | `gpt-4.1`, `gpt-4.1-mini` |
| Anthropic | `ANTHROPIC_API_KEY` | `claude-sonnet-4-6`, `claude-opus-4-6` |
| Ollama (local) | No requiere key | `llama3`, `mistral` |
| Google | `GOOGLE_API_KEY` | `gemini-2.5-pro` |

> **Recomendación**: Si usas OpenAI, usa `gpt-4.1` — tiene 1M de contexto, es más barato que gpt-4o y excelente para tool calling.

### 4.2 Canal de comunicación

El wizard pregunta por qué canal quieres comunicarte. Selecciona **Telegram**.

---

## 5. Configurar Telegram

### 5.1 Crear un bot en Telegram

1. Abre Telegram y busca `@BotFather`
2. Envía `/newbot`
3. Elige un nombre para tu bot (ej: "Mi Asistente AI")
4. Elige un username que termine en `bot` (ej: `mi_asistente_ai_bot`)
5. BotFather te dará un **token** — guárdalo

### 5.2 Agregar el token a OpenClaw

Si ya pasaste el wizard, puedes agregar Telegram manualmente:

```bash
docker compose run --rm openclaw-cli channels add --channel telegram --token "<TU_BOT_TOKEN>"
```

O editar directamente `~/.openclaw/openclaw.json`:

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

### 5.3 Parear tu cuenta de Telegram

1. Busca tu bot en Telegram y envíale un mensaje
2. El bot te responderá con un código de pairing
3. Aprueba el pairing desde la terminal:

```bash
docker compose run --rm openclaw-cli pairing approve telegram <CODIGO>
```

Ahora tu bot debería responder mensajes desde Telegram.

---

## 6. Verificar que funciona

### Acceder al Control UI

Abre en tu navegador:

```
http://127.0.0.1:18789/
```

Pega el token de gateway (se generó durante el setup y está en `.env`).

### Verificar salud del contenedor

```bash
# Liveness
curl -fsS http://127.0.0.1:18789/healthz

# Readiness
curl -fsS http://127.0.0.1:18789/readyz

# Ver logs
docker compose logs -f openclaw-gateway
```

---

## 7. Configuración del Modelo

Edita `~/.openclaw/openclaw.json` para cambiar el modelo:

```json
{
  "agents": {
    "defaults": {
      "model": {
        "primary": "openai/gpt-4.1"
      }
    }
  }
}
```

### Modelos recomendados por caso de uso

| Caso de uso | Modelo | Contexto | Costo/1M input |
|---|---|---|---|
| General + Skills con tools | `openai/gpt-4.1` | 1M | $2.00 |
| Económico con buen contexto | `openai/gpt-4.1-mini` | 1M | $0.40 |
| Razonamiento complejo | `openai/gpt-5.4` | 1M | $2.50 |
| Máximo ahorro | `openai/gpt-4o-mini` | 128K | $0.15 |

> El gateway detecta cambios en el JSON automáticamente (hot reload), no siempre necesitas reiniciar.

---

## 8. Crear Skills Personalizados

Los skills son archivos markdown que le enseñan al agente cómo usar herramientas. Se guardan en el workspace.

### 8.1 Estructura de un skill

```
~/.openclaw/workspace/skills/<nombre-del-skill>/SKILL.md
```

### 8.2 Formato del SKILL.md

```markdown
---
name: mi-skill
description: Descripción clara de cuándo usar este skill. El agente usa esta descripción para decidir si activarlo.
---

# Título del Skill

## REGLA OBLIGATORIA
Instrucciones claras y explícitas de lo que el agente DEBE hacer.

## Comandos
Bloques de código con los comandos exactos que el agente debe ejecutar.

## Campos en los resultados
Tabla o lista de los campos que devuelve la herramienta.

## Cómo formatear la respuesta
Instrucciones de cómo presentar los datos al usuario.
```

### 8.3 Ejemplo: Skill de Graylog

```
~/.openclaw/workspace/skills/graylog/SKILL.md
```

```markdown
---
name: graylog
description: Consultar logs de PEs Arista EOS via API REST de Graylog. Usar cuando pregunten sobre estado de la red, eventos BGP, interfaces, cambios de config o cualquier log de los equipos.
---

# Graylog — Logs centralizados de PEs

## REGLA OBLIGATORIA
SIEMPRE ejecutar curl antes de responder preguntas sobre la red. NUNCA inventar datos.

## Comando base
curl -s -u <TOKEN>:token \
  -H "Accept: application/json" \
  -H "X-Requested-By: ODIN" \
  "http://<GRAYLOG_IP>:9000/api/search/universal/relative?query=QUERY&range=SECONDS&limit=20"
```

### 8.4 Habilitar el skill en la configuración

Agrega el skill a `openclaw.json`:

```json
{
  "skills": {
    "entries": {
      "graylog": {
        "enabled": true
      }
    }
  }
}
```

### 8.5 Tips para skills efectivos

- **Sé explícito**: di "DEBES ejecutar el curl" no "puedes consultar"
- **Agrega "Cuándo usar"**: para cada comando, lista frases que el usuario diría
- **Incluye manejo de errores**: qué hacer si el comando falla o devuelve vacío
- **Formatea la respuesta**: dile al agente cómo presentar los resultados
- **Nunca confíes en el modelo**: asume que el modelo intentará responder sin ejecutar el comando y bloquea ese comportamiento

---

## 9. Estructura de directorios

```
~/.openclaw/
├── openclaw.json          # Configuración principal
├── .env                   # Variables de entorno (tokens, keys)
├── workspace/
│   ├── skills/
│   │   ├── graylog/
│   │   │   └── SKILL.md
│   │   └── otro-skill/
│   │       └── SKILL.md
│   ├── AGENTS.md          # Instrucciones del agente
│   ├── SOUL.md            # Personalidad del agente
│   └── USER.md            # Info sobre el usuario
└── agents/
    └── main/
        └── sessions/      # Historial de sesiones
```

---

## 10. Comandos útiles de Docker

```bash
# Ver estado
docker compose ps

# Ver logs en tiempo real
docker compose logs -f openclaw-gateway

# Reiniciar el gateway
docker compose restart openclaw-gateway

# Ejecutar comandos CLI
docker compose run --rm openclaw-cli <comando>

# Actualizar a última versión
docker compose pull && docker compose up -d

# Detener todo
docker compose down

# Ver configuración actual
docker compose run --rm openclaw-cli config get

# Diagnóstico
docker compose run --rm openclaw-cli doctor
```

---

## 11. ClawDock Helpers (opcional)

Para comandos más cortos en el día a día:

```bash
mkdir -p ~/.clawdock && curl -sL \
  https://raw.githubusercontent.com/openclaw/openclaw/main/scripts/shell-helpers/clawdock-helpers.sh \
  -o ~/.clawdock/clawdock-helpers.sh

echo 'source ~/.clawdock/clawdock-helpers.sh' >> ~/.bashrc && source ~/.bashrc
```

Después puedes usar: `clawdock-start`, `clawdock-stop`, `clawdock-dashboard`, etc.

---

## 12. Seguridad

- **Nunca expongas el gateway sin autenticación** a redes públicas
- El token de gateway en `.env` protege el acceso al dashboard
- Configura `dmPolicy: "pairing"` para Telegram (requiere aprobación manual)
- Revisa la configuración de seguridad:

```bash
docker compose run --rm openclaw-cli security audit
docker compose run --rm openclaw-cli doctor
```

- Si estás en un VPS público, configura firewall:

```bash
# Solo permitir SSH y el puerto del gateway
sudo ufw allow 22
sudo ufw allow from <IP_ADMINISTRACION> to any port 18789 proto tcp
sudo ufw enable
```

---

## 13. Troubleshooting

| Problema | Solución |
|---|---|
| Bot no responde en Telegram | Verificar `botToken`, reiniciar gateway, revisar logs |
| "tools.profile (coding) allowlist contains unknown entries" | Normal con algunos modelos, no afecta funcionalidad |
| Skill no ejecuta comandos | Cambiar a un modelo más capaz (gpt-4.1 mínimo) |
| Error de red en skills con curl | Autorizar únicamente los endpoints necesarios en la política de red; conservar el sandbox activo |
| Polling stall en Telegram | Se recupera automáticamente; si persiste, reiniciar gateway |
| Pairing no funciona | `docker compose run --rm openclaw-cli pairing list` para ver pendientes |
| Alcanza límite de tokens rápido | Cambiar a modelo con más contexto (gpt-4.1 = 1M tokens) |

---

## Referencias

- Documentación oficial: https://docs.openclaw.ai
- Docker setup: https://docs.openclaw.ai/install/docker
- Configuración: https://docs.openclaw.ai/gateway/configuration
- Telegram: https://github.com/openclaw/openclaw/blob/main/docs/channels/telegram.md
- GitHub: https://github.com/openclaw/openclaw

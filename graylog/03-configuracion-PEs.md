## ============================================================
## Guía de configuración post-instalación
## Graylog Stack - odin.example.net
## ============================================================

## ============================================
## PASO 1: Crear el Input de Syslog en Graylog
## ============================================
##
## 1. Ir a http://odin.example.net:9000
## 2. System → Inputs
## 3. Seleccionar "Syslog UDP" → Launch new input
##    - Title: Syslog UDP - PEs
##    - Bind address: 0.0.0.0
##    - Port: 1514
##    - [x] Store full message
##    - Click "Launch"
##
## 4. Repetir con "Syslog TCP" → Launch new input
##    - Title: Syslog TCP - PEs
##    - Bind address: 0.0.0.0
##    - Port: 1514
##    - [x] Store full message
##    - Click "Launch"


## ============================================
## PASO 2: Configurar los PEs Arista EOS
## ============================================

## --- Configuración básica de syslog ---
## Aplicar en cada PE:

# configure terminal
# logging host odin.example.net 1514 protocol tcp
# logging trap informational
# logging facility local7
# logging source-interface Loopback0
# logging buffered 1000000
# logging format hostname fqdn
# logging format timestamp high-resolution
# end
# write memory


## ============================================
## PASO 3: Configurar PEs Cisco IOS-XR
## ============================================

## --- Si tienes PEs Cisco ---

# configure terminal
# logging odin.example.net vrf MGMT port 1514
# logging source-interface Loopback0
# logging trap informational
# logging facility local7
# logging hostnameprefix PE-NOMBRE
# commit
# end


## ============================================
## PASO 4: Configurar PEs Juniper JunOS
## ============================================

## --- Si tienes PEs Juniper ---

# set system syslog host odin.example.net port 1514
# set system syslog host odin.example.net any info
# set system syslog host odin.example.net facility-override local7
# set system syslog host odin.example.net source-address <loopback-ip>
# commit


## ============================================
## PASO 5: Crear Extractors en Graylog
## ============================================
##
## Extractors recomendados para logs de red:
##
## 1. System → Inputs → tu input → Manage extractors
##
## 2. Extractor: Hostname del PE
##    - Type: Regular expression
##    - Regex: ^(\S+)\s
##    - Store as: pe_hostname
##
## 3. Extractor: Facility de Arista
##    - Type: Regular expression
##    - Regex: %(\w+)-\d-(\w+)
##    - Store as: arista_facility, arista_mnemonic
##
## Esto te permite buscar logs por PE y por tipo de evento.


## ============================================
## PASO 6: Crear Streams en Graylog
## ============================================
##
## Streams recomendados:
##
## 1. "BGP Events"
##    - Rule: message contains "BGP" OR message contains "ADJ"
##
## 2. "Interface Events"
##    - Rule: message contains "LINEPROTO" OR message contains "LINK"
##
## 3. "OSPF/ISIS Events"
##    - Rule: message contains "OSPF" OR message contains "ISIS"
##
## 4. "Hardware Alerts"
##    - Rule: message contains "HARDWARE" OR message contains "FAN"
##           OR message contains "POWER" OR message contains "TEMPERATURE"
##
## 5. "Security Events"
##    - Rule: message contains "SEC" OR message contains "LOGIN"
##           OR message contains "SSH"
##
## Cada stream puede tener sus propias alertas y retención.


## ============================================
## PASO 7: Configurar Alertas
## ============================================
##
## Alertas críticas recomendadas:
##
## 1. "BGP Session Down"
##    - Condition: Stream "BGP Events" has more than 0
##      messages matching "Down" in the last 1 minute
##    - Notification: Email / Slack / Telegram
##
## 2. "Interface Down"
##    - Condition: Stream "Interface Events" has more than 0
##      messages matching "changed state to down" in 1 minute
##    - Notification: Email / Slack / Telegram
##
## 3. "High Error Rate"
##    - Condition: More than 50 messages with severity
##      "error" or "critical" in 5 minutes from any PE
##    - Notification: Email / Slack / Telegram


## ============================================
## PASO 8: Verificar que todo funciona
## ============================================
##
## Desde un PE Arista, generar un log de prueba:
##
## PE-01# send log level informational message "Test syslog to Graylog"
##
## En Graylog → Search → buscar "Test syslog"
## Deberías ver el mensaje en segundos.
##
## También puedes verificar desde el servidor:
##
## docker compose logs -f graylog | grep "1514"
##
## Para ver el conteo de mensajes recibidos:
## curl --fail --silent --show-error --connect-timeout 5 --max-time 20 --netrc-file "$GRAYLOG_NETRC_FILE" http://localhost:9000/api/count/total

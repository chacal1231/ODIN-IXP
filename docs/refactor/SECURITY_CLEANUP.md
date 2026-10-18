# Limpieza del historial de credenciales

Estado: historial limpio publicado en GitHub y main local sincronizado.

- Repositorio: chacal1231/ODIN, rama main; el remoto solo anunció esa rama y ninguna etiqueta o ref de PR.
- Commit remoto esperado antes del reemplazo: <commit-retirado>.
- Historial preparado: <commit-retirado>.
- 45 commits revisados; 3 reescritos; 42 anteriores conservados.
- Eliminado IXP/graylog/.env de todas las revisiones.
- Sustituidos tokens de Graylog/LibreNMS, valores sensibles del entorno, comunidad SNMP, passwords MySQL/OpenSearch y ejemplos de autenticación literal.
- Gitleaks 8.30.1: cero hallazgos sobre main.
- Búsqueda exacta de valores retirados: cero coincidencias en objetos alcanzables.
- Ocho pruebas del cliente aprobadas; Git fsck del clon aislado aprobado.

La publicación debe usar force-with-lease contra el commit remoto esperado. Si hay cambios concurrentes, detenerse y revisar, sin forzar una referencia nueva a ciegas. El checkout principal quedó sincronizado con main limpio conservando el .env local ignorado. Los clones ajenos, reflogs y refs internas de herramientas pueden conservar objetos antiguos; no mezclar ni publicar ramas antiguas.

## Acciones que la reescritura no resuelve

Revocar/rotar todas las credenciales expuestas en sus plataformas. La reescritura no invalida tokens ni cambia passwords de servicios. La configuración local .env se conserva fuera del seguimiento; no se distribuye.

Coordinar nuevos clones para colaboradores y revisar forks. Un merge con una rama antigua puede reintroducir el historial contaminado.

Las vistas por SHA, cachés y referencias internas de GitHub pueden persistir. Si el riesgo no se mitiga con la rotación, tramitar la purga mediante GitHub Support: repositorio chacal1231/ODIN; primer commit afectado <commit-retirado>; sin refs de PR anunciadas; sin LFS en uso según git-filter-repo. No incluir credenciales en el ticket.

## Acceso residual confirmado en GitHub

Después del force-with-lease, una comprobación HEAD devolvió HTTP 200 tanto para el commit antiguo como para el archivo `.env` bajo su SHA original. No se descargaron ni imprimieron sus valores en esta comprobación. La limpieza de main no basta para eliminar ese acceso residual.

Procedimiento oficial: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository

## Borrador de solicitud a GitHub Support

Asunto: Solicitud de purga de datos sensibles de historial reescrito — chacal1231/ODIN

Se reescribió main para retirar un archivo de entorno y credenciales literales del repositorio público chacal1231/ODIN. El primer commit afectado es <commit-retirado>. La rama limpia se publicó con force-with-lease; el resultado del filtrado es <commit-retirado>. Gitleaks no detectó secretos en los 45 commits resultantes. No se anunciaron etiquetas ni referencias de pull requests, y git-filter-repo indicó que LFS no está en uso.

Sin embargo, GitHub aún devuelve HTTP 200 para el commit original y para IXP/graylog/.env consultado por ese SHA. Se solicita evaluar la eliminación de vistas en caché, referencias internas y objetos antiguos que mantienen accesibles los datos sensibles. No se adjuntan secretos ni sus valores. La revocación operativa de credenciales se debe gestionar por separado; esta solicitud no afirma que ya se haya realizado.

Este texto es un borrador: no se ha enviado ninguna solicitud ni se garantiza que GitHub apruebe una purga. GitHub Support decide la asistencia según su política y si la rotación mitiga el riesgo.

# Job Scraper

Bot de automatización para recopilar ofertas de empleo utilizando **Playwright**, almacenarlas en una base de datos **SQLite** y enviarlas automáticamente a un bot de **Telegram**.

La configuración del bot se define mediante un archivo JSON. Además, las credenciales de Telegram deben configurarse mediante variables de entorno en un archivo `.env` para mantenerlas protegidas.

## Tecnologías

- [Python](https://www.python.org/)
- [Playwright](https://playwright.dev/python/)
- SQLite
- JSON
- Telegram Bot API

## Características

- Automatización del navegador con Playwright
- Scraping de ofertas de empleo
- Persistencia de datos mediante SQLite
- Configuración del bot a través de un archivo JSON
- Envío automático de las ofertas recopiladas a Telegram
- Uso de variables de entorno para proteger las credenciales del bot

## Requisitos

- Python 3.9 o superior
- pip
- Navegador compatible con Playwright
- Un bot de Telegram creado mediante [BotFather](https://t.me/BotFather)
- El `chat_id` de Telegram donde se enviarán las ofertas

## Instalación

Clona el repositorio y accede a su directorio:

```bash
git clone https://github.com/davidG199/job_scraper.git
cd job_scraper
```

Crea y activa un entorno virtual:

```bash
python -m venv .venv
```

En Linux o macOS:

```bash
source .venv/bin/activate
```

En Windows:

```powershell
.venv\Scripts\Activate.ps1
```

Instala las dependencias del proyecto:

```bash
pip install -r requirements.txt
```

Instala los navegadores necesarios para Playwright:

```bash
playwright install
```

## Variables de entorno

Antes de ejecutar el bot, crea un archivo llamado `.env` en la raíz del proyecto:

```env
TELEGRAM_TOKEN=tu_token_del_bot
TELEGRAM_CHAT_ID=tu_chat_id
```

El archivo `.env` debe mantenerse privado y no debe subirse al repositorio. Añádelo al archivo `.gitignore` junto con cualquier base de datos local que no quieras compartir:

```gitignore
.env
*.db
```

El `TELEGRAM_TOKEN` es el token proporcionado por BotFather. El `TELEGRAM_CHAT_ID` corresponde al chat, grupo o canal donde el bot publicará las ofertas.

## Configuración JSON

El comportamiento del scraper se controla mediante un archivo JSON. En él se pueden definir los parámetros necesarios para la ejecución, como búsquedas, filtros, páginas objetivo y la configuración de Telegram.

Ejemplo:

```json
{
  "keywords": ["python", "backend"],
  "location": "Remote",
  "max_pages": 5,
  "headless": true,
  "database": "jobs.db",
  "telegram": {
    "token": "${TELEGRAM_TOKEN}",
    "chat_id": "${TELEGRAM_CHAT_ID}"
  }
}
```

> Los nombres y valores disponibles dependen de la implementación actual del bot. Utiliza el archivo de configuración JSON incluido en el proyecto como referencia.

> No escribas credenciales reales directamente en archivos que vayan a compartirse o subirse al repositorio. Utiliza las variables definidas en `.env`.

## Flujo de ejecución

El bot realiza las siguientes acciones:

1. Lee la configuración del archivo JSON.
2. Abre el navegador utilizando Playwright.
3. Busca y extrae las ofertas de empleo configuradas.
4. Guarda las ofertas en la base de datos SQLite.
5. Envía las ofertas guardadas al bot de Telegram utilizando el token y el `chat_id` configurados.

## Ejecución

Ejecuta el archivo principal del bot:

```bash
python <archivo_principal>.py
```

Reemplaza `<archivo_principal>.py` por el nombre real del archivo de entrada del proyecto.

## Base de datos

Las ofertas se almacenan en SQLite, por lo que no es necesario configurar un servidor de base de datos externo.

La base de datos puede consultarse con cualquier herramienta compatible con SQLite:

```bash
sqlite3 jobs.db
```

## Buenas prácticas

- Mantén el archivo `.env` fuera del control de versiones.
- No compartas el token del bot de Telegram.
- No sobrecargues los sitios web consultados.
- Configura pausas entre solicitudes cuando sea necesario.
- Maneja adecuadamente los errores de conexión, scraping y envío a Telegram.
- Verifica que el bot tenga permisos para enviar mensajes al `chat_id` configurado.

## Contribuir

Si quieres mejorar el proyecto:

1. Haz un fork del repositorio.
2. Crea una rama para tus cambios.
3. Implementa y prueba las mejoras.
4. Envía un pull request.

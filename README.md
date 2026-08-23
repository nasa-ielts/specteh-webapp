# SpecTech

## Project files
- `bot.py` Telegram bot and web server startup
- `database.py` SQLite access and migrations
- `webserver.py` WebApp pages + API
- `keyboards.py` Telegram keyboards
- `texts.py` bot texts
- `webapp/` Telegram WebApp pages
- `requirements.txt` Python dependencies
- `schema.sql` database schema reference

## Secrets and data
Keep `.env` and `spectech.db` OUTSIDE GitHub.
For local development, keep them in the same folder as `bot.py`.
On Render, put the `.env` values into the service Environment variables.

## Render
Use a **Web Service**, not a Static Site. The service runs `python bot.py` and serves both the Telegram WebApp and `/api/...` endpoints.
Set `MINIAPP_URL` to the Web Service URL.

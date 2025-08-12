import typer

from app.core.config import settings
from app.core.db import init_db
from app.services.accounts import AccountService
from app.services.telethon_client import ClientFactory

app = typer.Typer()


@app.command()
def login(phone: str = typer.Option(..., prompt=True)):
    """Login a Telegram account and save session."""
    factory = ClientFactory(settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH, settings.SESSIONS_DIR)
    client = factory.build(phone)
    with client:
        client.start(phone=phone)
        typer.echo(f"Session for {phone} saved.")
    # persist in DB
    import asyncio

    async def persist():
        await init_db()
        await AccountService().create(phone=phone, session_path=f"{settings.SESSIONS_DIR}/{phone}.session")

    asyncio.run(persist())


if __name__ == "__main__":
    app()

import typer
from app.core.config import settings
from app.services.telethon_client import ClientFactory
from app.services.adder import Adder
import asyncio

app = typer.Typer()

@app.command()
def add(dest: str, infile: str = "members.csv", per_account: int = 40, min_sleep: int = 3, max_sleep: int = 9):
    """Add members from CSV to a group."""
    factory = ClientFactory(settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH, settings.SESSIONS_DIR)
    client = factory.build("default")
    async def run():
        await client.start()
        with open(infile, "r", encoding="utf-8") as f:
            usernames = [line.strip() for line in f if line.strip()]
        adder = Adder(client, min_sleep, max_sleep, per_account)
        report = await adder.add_usernames(dest, usernames)
        print(f"Add report: {report}")
        await client.disconnect()
    asyncio.run(run())

if __name__ == "__main__":
    app()

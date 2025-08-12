import typer
from app.core.config import settings
from app.services.telethon_client import ClientFactory
from app.services.scraper import Scraper
import asyncio

app = typer.Typer()

@app.command()
def scrape(source: str, limit: int = 1000, query: str = "", out: str = "members.csv"):
    """Scrape members from a group and save to CSV."""
    factory = ClientFactory(settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH, settings.SESSIONS_DIR)
    client = factory.build("default")
    async def run():
        await client.start()
        scraper = Scraper(client)
        usernames = await scraper.scrape_usernames(source, limit, query)
        with open(out, "w", encoding="utf-8") as f:
            for u in usernames:
                f.write(u + "\n")
        print(f"Saved {len(usernames)} usernames to {out}")
        await client.disconnect()
    asyncio.run(run())

if __name__ == "__main__":
    app()

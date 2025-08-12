import asyncio

import typer

from app.core.db import init_db
from app.services.accounts import AccountService

app = typer.Typer()


@app.command()
def list():
    async def run():
        await init_db()
        accs = await AccountService().list()
        for a in accs:
            print(f"{a.id}\t{a.phone}\tcooldown_until={a.cooldown_until}\tlast_error={a.last_error}")

    asyncio.run(run())


if __name__ == "__main__":
    app()

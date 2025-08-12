import typer
import asyncio
from app.core.db import init_db
from app.services.admins import AdminService

app = typer.Typer()

@app.command()
def create(username: str, password: str):
    async def run():
        await init_db()
        try:
            user = await AdminService().create(username, password)
            print(f"created admin id={user.id} username={user.username}")
        except ValueError as e:
            # Likely duplicate username
            print(f"error: {e}\nTip: use 'python -m app.cli.admins change_password {username} NEW_PASSWORD' or choose a different username.")
    asyncio.run(run())

@app.command()
def list():
    async def run():
        await init_db()
        svc = AdminService()
        users = await svc.list()
        for u in users:
            print(f"{u.id}\t{u.username}\tactive={u.is_active}")
    asyncio.run(run())

@app.command()
def deactivate(username: str):
    async def run():
        await init_db()
        ok = await AdminService().deactivate(username, active=False)
        print("deactivated" if ok else "not found")
    asyncio.run(run())

@app.command()
def activate(username: str):
    async def run():
        await init_db()
        ok = await AdminService().deactivate(username, active=True)
        print("activated" if ok else "not found")
    asyncio.run(run())

@app.command()
def change_password(username: str, new_password: str):
    async def run():
        await init_db()
        ok = await AdminService().change_password(username, new_password)
        print("changed" if ok else "not found")
    asyncio.run(run())

if __name__ == "__main__":
    app()

import asyncio
import random
from typing import Iterable, Optional, Sequence
from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    UserPrivacyRestrictedError,
    PeerFloodError,
    ChatAdminRequiredError,
    UserAlreadyParticipantError,
)
from telethon.tl.functions.channels import InviteToChannelRequest, JoinChannelRequest
from telethon.tl.functions.messages import SendMessageRequest
from telethon.errors.rpcbaseerrors import ServerError

class Adder:
    def __init__(self, client: TelegramClient, min_sleep: int = 3, max_sleep: int = 9, per_account_limit: int = 40):
        self.client = client
        self.min_sleep = min_sleep
        self.max_sleep = max_sleep
        self.per_account_limit = per_account_limit

    async def add_usernames(self, dest: str, usernames: Iterable[str]) -> dict:
        entity = await self.client.get_entity(dest)
        report = {"success": 0, "skipped": 0, "failed": 0, "error": None}
        count = 0
        for username in usernames:
            if count >= self.per_account_limit:
                break
            try:
                # ensure account joined destination if it's a public link
                try:
                    await self.client(JoinChannelRequest(entity))
                except Exception:
                    pass
                # Send with small retry on transient server errors
                attempts = 0
                while True:
                    try:
                        await self.client(InviteToChannelRequest(entity, [username]))
                        break
                    except ServerError:
                        attempts += 1
                        if attempts >= 3:
                            raise
                        await asyncio.sleep(2 * attempts)
                report["success"] += 1
                count += 1
            except (UserPrivacyRestrictedError, UserAlreadyParticipantError) as e:
                report["skipped"] += 1
                report["error"] = type(e).__name__
            except (FloodWaitError, PeerFloodError) as e:
                # backoff and stop using this account for now
                report["failed"] += 1
                report["error"] = type(e).__name__
                break
            except (ChatAdminRequiredError) as e:
                report["failed"] += 1
                report["error"] = type(e).__name__
                break
            except Exception as e:
                report["failed"] += 1
                report["error"] = str(e)
            await asyncio.sleep(random.randint(self.min_sleep, self.max_sleep))
        return report

    async def add_phones(self, dest: str, phones: Sequence[str]) -> dict:
        """Add users by phone numbers. Resolves phones into users via import_contacts then invites them."""
        entity = await self.client.get_entity(dest)
        report = {"success": 0, "skipped": 0, "failed": 0, "error": None}
        count = 0
        for phone in phones:
            if count >= self.per_account_limit:
                break
            try:
                try:
                    await self.client(JoinChannelRequest(entity))
                except Exception:
                    pass
                # Resolve phone to entity (may require the account to have the number as a contact)
                try:
                    user_entity = await self.client.get_entity(phone)
                except Exception:
                    # fallback: try importing as a contact to resolve, then get_entity
                    from telethon.tl.functions.contacts import ImportContactsRequest
                    from telethon.tl.types import InputPhoneContact
                    contacts = [InputPhoneContact(client_id=0, phone=phone, first_name="", last_name="")]
                    await self.client(ImportContactsRequest(contacts=contacts))
                    try:
                        user_entity = await self.client.get_entity(phone)
                    except Exception as e:
                        report["skipped"] += 1
                        report["error"] = str(e)
                        continue
                try:
                    attempts = 0
                    while True:
                        try:
                            await self.client(InviteToChannelRequest(entity, [user_entity]))
                            break
                        except ServerError:
                            attempts += 1
                            if attempts >= 3:
                                raise
                            await asyncio.sleep(2 * attempts)
                    report["success"] += 1
                    count += 1
                except UserAlreadyParticipantError as e:
                    report["skipped"] += 1
                    report["error"] = type(e).__name__
                except ChatAdminRequiredError as e:
                    report["failed"] += 1
                    report["error"] = type(e).__name__
                    break
                except (FloodWaitError, PeerFloodError) as e:
                    report["failed"] += 1
                    report["error"] = type(e).__name__
                    break
                except Exception as e:
                    report["failed"] += 1
                    report["error"] = str(e)
                await asyncio.sleep(random.randint(self.min_sleep, self.max_sleep))
            except Exception:
                report["failed"] += 1
        return report

    async def send_messages_to_phones(self, phones: Sequence[str], messages: Sequence[str]) -> dict:
        report = {"success": 0, "failed": 0, "skipped": 0, "error": None}
        for phone in phones:
            try:
                # resolve contact
                try:
                    peer = await self.client.get_entity(phone)
                except Exception:
                    from telethon.tl.functions.contacts import ImportContactsRequest
                    from telethon.tl.types import InputPhoneContact
                    await self.client(ImportContactsRequest(contacts=[InputPhoneContact(client_id=0, phone=phone, first_name="", last_name="")]))
                    try:
                        peer = await self.client.get_entity(phone)
                    except Exception as e:
                        report["skipped"] += 1
                        report["error"] = str(e)
                        continue
                text = random.choice(messages)
                # Retry a couple of times on transient server errors
                attempts = 0
                while True:
                    try:
                        await self.client.send_message(peer, text)
                        break
                    except ServerError as e:
                        attempts += 1
                        if attempts >= 3:
                            raise
                        await asyncio.sleep(2 * attempts)
                report["success"] += 1
            except Exception as e:
                report["failed"] += 1
                report["error"] = str(e)
            await asyncio.sleep(random.randint(self.min_sleep, self.max_sleep))
        return report

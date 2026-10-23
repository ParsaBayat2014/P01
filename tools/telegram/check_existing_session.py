"""Check an existing Pyrogram session in memory, with no new login or session file."""
import argparse
import asyncio
import base64
from getpass import getpass
import json
import logging
import struct
import sys


def session_api_id(value):
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if len(raw) != 271:
        raise ValueError("Expected a Pyrogram v2 string; do not guess another format.")
    dc, api_id, test_mode, auth_key, account_id, is_bot = struct.unpack(">BI?256sQ?", raw)
    if dc not in (1, 2, 3, 4, 5) or api_id <= 0 or not account_id:
        raise ValueError("Invalid session metadata.")
    return api_id


async def check(value):
    from pyrogram import Client
    api_id = session_api_id(value)
    client = Client("money_existing_session_check", api_id=api_id,
                    session_string=value, in_memory=True, no_updates=True,
                    workers=1, sleep_threshold=0,
                    device_model="Money local account check", app_version="1.0")
    try:
        authorized = await asyncio.wait_for(client.connect(), timeout=25)
        if not authorized:
            raise RuntimeError("Existing session is not authorized; no login code requested.")
        me = await asyncio.wait_for(client.get_me(), timeout=15)
        print(json.dumps({"connected": True, "account_id": me.id,
                          "first_name": me.first_name, "username": me.username,
                          "permanent_chatgpt_connection": False},
                         ensure_ascii=False, indent=2))
    finally:
        if client.is_connected:
            await asyncio.wait_for(client.disconnect(), timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.disable(logging.CRITICAL)
    value = getpass("Existing Pyrogram session (hidden; stays in memory): ").strip()
    try:
        asyncio.run(check(value))
        return 0
    except ModuleNotFoundError:
        print("Install Pyrogram==2.0.106 in the local virtual environment.", file=sys.stderr)
        return 2
    except Exception as error:
        print("Connection not confirmed: " + type(error).__name__
              + ". Credential details were not printed.", file=sys.stderr)
        return 1
    finally:
        value = ""


if __name__ == "__main__":
    raise SystemExit(main())

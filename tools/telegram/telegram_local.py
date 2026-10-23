"""Local Telegram client for an explicitly authorized account.

Login is interactive on the owner's Windows machine. Session credentials are
encrypted with Windows DPAPI and never printed. No automatic AI replies,
background scheduler, bulk sending, deletion, or payment verification is included.
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
from ctypes import wintypes
from getpass import getpass
import json
from pathlib import Path
import re
import sys

DEFAULT_STATE = Path(__file__).resolve().parents[2] / ".money-private"
STATE_FILE = "telegram-dpapi.bin"


class Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def dpapi(data: bytes, decrypt: bool = False) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError("WindowsRequired")
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    protect = crypt.CryptProtectData
    protect.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR,
                        ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                        wintypes.DWORD, ctypes.POINTER(Blob)]
    protect.restype = wintypes.BOOL
    unprotect = crypt.CryptUnprotectData
    unprotect.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p,
                          ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                          wintypes.DWORD, ctypes.POINTER(Blob)]
    unprotect.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    raw = ctypes.create_string_buffer(data)
    incoming = Blob(len(data), ctypes.cast(raw, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = Blob()
    if decrypt:
        ok = unprotect(ctypes.byref(incoming), None, None, None, None,
                       1, ctypes.byref(outgoing))
    else:
        ok = protect(ctypes.byref(incoming), "Money local Telegram session",
                     None, None, None, 1, ctypes.byref(outgoing))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        kernel.LocalFree(ctypes.cast(outgoing.pbData, ctypes.c_void_p))


def write_state(folder: Path, state: dict) -> None:
    encrypted = dpapi(json.dumps(state).encode("utf-8"))
    folder.mkdir(parents=True, exist_ok=True)
    temp = folder / (STATE_FILE + ".tmp")
    temp.write_bytes(encrypted)
    temp.replace(folder / STATE_FILE)


def read_state(folder: Path) -> dict:
    return json.loads(dpapi((folder / STATE_FILE).read_bytes(), decrypt=True))


def emit(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def client_from_state(state: dict):
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    return TelegramClient(StringSession(state["session"]),
                          state["api_id"], state["api_hash"])


async def login(folder: Path) -> None:
    # Fail before requesting any login data if secure local storage is unavailable.
    probe = b"money-local-encryption-preflight"
    if dpapi(dpapi(probe), decrypt=True) != probe:
        raise RuntimeError("SessionEncryptionPreflightFailed")
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    if (folder / STATE_FILE).exists():
        raise RuntimeError("SessionAlreadyExistsUseStatus")
    api_id = int(input("Your registered api_id: ").strip())
    api_hash = getpass("Your api_hash (hidden): ").strip()
    if api_id <= 0 or not re.fullmatch(r"[0-9a-fA-F]{32}", api_hash):
        raise ValueError("InvalidApiConfiguration")
    phone = getpass("Your phone number with country code (hidden): ").strip()
    client = TelegramClient(StringSession(), api_id, api_hash)
    try:
        await client.start(phone=lambda: phone,
                           code_callback=lambda: getpass("Telegram login code (hidden): "),
                           password=lambda: getpass("Telegram 2FA password (hidden): "))
        me = await client.get_me()
        write_state(folder, {"schema": 1, "api_id": api_id,
                             "api_hash": api_hash,
                             "session": client.session.save(),
                             "account_id": me.id})
        emit({"ready": True, "account_id": me.id, "username": me.username,
              "session_storage": "Windows DPAPI, local user",
              "automatic_management_running": False})
    finally:
        await client.disconnect()


async def existing_dialog(client, chat_id: int):
    # Only address a verified existing dialog; do not resolve guessed names.
    async for dialog in client.iter_dialogs(limit=1000):
        if dialog.id == chat_id:
            return dialog.entity
    raise ValueError("ExistingDialogNotFound")


async def run(args) -> None:
    folder = args.state_dir
    if args.command == "login":
        await login(folder)
        return
    state = read_state(folder)
    client = client_from_state(state)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError("SessionUnauthorized")
        me = await client.get_me()
        if me.id != state["account_id"]:
            raise RuntimeError("AccountMismatch")
        if args.command == "status":
            emit({"authorized": True, "account_id": me.id,
                  "username": me.username,
                  "automatic_management_running": False})
        elif args.command == "dialogs":
            dialogs = await client.get_dialogs(limit=args.limit)
            emit([{"id": d.id, "title": d.name, "unread_count": d.unread_count,
                   "kind": "user" if d.is_user else "group" if d.is_group else "channel"}
                  for d in dialogs])
        elif args.command == "messages":
            entity = await existing_dialog(client, args.chat)
            messages = await client.get_messages(entity, limit=args.limit)
            emit([{"id": m.id, "date": m.date.isoformat(), "outgoing": bool(m.out),
                   "sender_id": m.sender_id, "text": m.message,
                   "has_media": bool(m.media)} for m in messages])
        elif args.command == "send":
            if args.confirm_account_id != me.id:
                raise ValueError("ConfirmAccountIdMismatch")
            text = args.text_file.read_text(encoding="utf-8-sig")
            if not text.strip() or len(text) > 3500:
                raise ValueError("TextMustContain1To3500Characters")
            entity = await existing_dialog(client, args.chat)
            sent = await client.send_message(entity, text, parse_mode=None,
                                             link_preview=False)
            emit({"sent": True, "account_id": me.id,
                  "dialog_id": args.chat, "message_id": sent.id})
    finally:
        await client.disconnect()


def bounded_limit(value):
    number = int(value)
    if not 1 <= number <= 100:
        raise argparse.ArgumentTypeError("limit must be between 1 and 100")
    return number


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("login", help="Interactive login; secrets stay on this Windows device.")
    sub.add_parser("status", help="Verify the connected account without reading chats.")
    dialogs = sub.add_parser("dialogs", help="List bounded existing dialogs.")
    dialogs.add_argument("--limit", type=bounded_limit, default=20)
    messages = sub.add_parser("messages", help="Read messages from an exact existing dialog ID.")
    messages.add_argument("--chat", required=True, type=int)
    messages.add_argument("--limit", type=bounded_limit, default=20)
    send = sub.add_parser("send", help="Send one explicit text file to an exact existing dialog ID.")
    send.add_argument("--chat", required=True, type=int)
    send.add_argument("--confirm-account-id", required=True, type=int)
    send.add_argument("--text-file", required=True, type=Path)
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
        return 0
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130
    except ModuleNotFoundError:
        print("Install tools/telegram/requirements.txt in the local virtual environment.",
              file=sys.stderr)
        return 2
    except Exception as error:
        # Do not print provider exception bodies, credentials, or message content.
        if isinstance(error, FileNotFoundError):
            print("Local session or Windows encryption profile is unavailable. "
                  "Login cannot continue without secure local storage.",
                  file=sys.stderr)
            return 1
        print("Operation failed: " + type(error).__name__
              + ". No credential details were printed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


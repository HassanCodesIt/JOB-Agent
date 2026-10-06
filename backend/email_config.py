import os
import json
from dotenv import load_dotenv

load_dotenv()

STATE_FILE = "email_state.json"
ACCOUNTS_FILE = "email_accounts.json"

# Slots 1 and 2 come from .env. Additional slots are added through the UI and
# live in ACCOUNTS_FILE, so the number of sending accounts is not capped at two.
BASE_SLOTS = (1, 2)


def _get_active_index(fallback=1):
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                index = json.load(f).get("active_index", fallback)
            return int(index)
        except Exception:
            pass
    return fallback


def _load_accounts():
    """Accounts saved through the UI, keyed by slot number as a string."""
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE, "r") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _save_accounts(data):
    with open(ACCOUNTS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _env_credentials(slot):
    if slot == 1:
        return os.getenv("EMAIL"), os.getenv("PASSWORD")
    if slot == 2:
        return os.getenv("EMAIL2"), os.getenv("PASSWORD2")
    return None, None


def _slot_credentials(slot):
    """Resolve a slot's credentials, preferring UI-saved values over .env."""
    saved = _load_accounts().get(str(slot)) or {}
    env_email, env_password = _env_credentials(slot)
    return {
        "email": saved.get("email") or env_email or "",
        "password": saved.get("password") or env_password or "",
    }


def all_slots():
    """Every configured slot: env-backed ones plus any added through the UI."""
    slots = []
    for slot in BASE_SLOTS:
        credentials = _slot_credentials(slot)
        if credentials["email"] and credentials["password"]:
            slots.append(slot)

    for key in _load_accounts():
        try:
            slot = int(key)
        except (TypeError, ValueError):
            continue
        if slot not in slots:
            slots.append(slot)

    return sorted(slots)


def get_email_credentials():
    """(email, password) for whichever slot is currently active."""
    slots = all_slots()
    active = _get_active_index(slots[0] if slots else 1)
    if active not in slots:
        active = slots[0] if slots else 1

    credentials = _slot_credentials(active)
    return credentials["email"], credentials["password"]


def get_all_emails():
    """Slot -> email address, used to populate the account switcher."""
    return {slot: _slot_credentials(slot)["email"] for slot in all_slots()}


def get_account_details():
    """Everything the account UI needs, including which slots are still free."""
    used = all_slots()
    return {
        slot: {
            "email": _slot_credentials(slot)["email"],
            "configured": slot in used,
        }
        for slot in used
    }


def free_slots():
    """The next available slot numbers, excluding everything already in use."""
    used = set(all_slots())
    candidates = []
    candidate = 1
    while len(candidates) < 2 and candidate < 100:
        if candidate not in used:
            candidates.append(candidate)
        candidate += 1
    return candidates


def add_account(email, password):
    """Store credentials in the next free slot and return that slot number."""
    available = free_slots()
    if not available:
        raise ValueError("No free sending slots available.")

    slot = available[0]
    accounts = _load_accounts()
    accounts[str(slot)] = {"email": email, "password": password}
    _save_accounts(accounts)
    return slot


def remove_account(slot):
    accounts = _load_accounts()
    if str(slot) in accounts:
        del accounts[str(slot)]
        _save_accounts(accounts)
    return _slot_credentials(slot)["email"]


def set_active_email(index):
    if index not in all_slots():
        raise ValueError("That sending account is not connected.")
    with open(STATE_FILE, "w") as f:
        json.dump({"active_index": index}, f)


def get_active_index():
    slots = all_slots()
    active = _get_active_index(slots[0] if slots else 1)
    return active if active in slots else (slots[0] if slots else 1)

import os
import json
from pathlib import Path
from cryptography.fernet import Fernet

CONFIG_FILE = Path(__file__).parent / "config.json"
KEY_FILE = Path(__file__).parent / ".secret.key"


def _get_fernet():
    if not KEY_FILE.exists():
        key = Fernet.generate_key()
        KEY_FILE.write_bytes(key)
    return Fernet(KEY_FILE.read_bytes())


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(data: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_api_key(name: str) -> str:
    cfg = load_config()
    encrypted = cfg.get("api_keys", {}).get(name, "")
    if not encrypted:
        return ""
    try:
        return _get_fernet().decrypt(encrypted.encode()).decode()
    except Exception:
        return ""


def set_api_key(name: str, value: str):
    cfg = load_config()
    if "api_keys" not in cfg:
        cfg["api_keys"] = {}
    encrypted = _get_fernet().encrypt(value.encode()).decode()
    cfg["api_keys"][name] = encrypted
    save_config(cfg)


def get_setting(name: str, default=None):
    cfg = load_config()
    return cfg.get("settings", {}).get(name, default)


def set_setting(name: str, value):
    cfg = load_config()
    if "settings" not in cfg:
        cfg["settings"] = {}
    cfg["settings"][name] = value
    save_config(cfg)

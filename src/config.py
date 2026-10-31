"""Configuration loading. All paths in config.yaml are relative to the project root."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path=None) -> dict:
    path = Path(path) if path else ROOT / "config" / "config.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve(p: str) -> Path:
    """Resolve a config path against the project root (absolute paths are kept)."""
    p = Path(p)
    return p if p.is_absolute() else ROOT / p

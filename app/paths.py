from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = PROJECT_ROOT / 'data'
STATIC_ROOT = PROJECT_ROOT / 'static'
WORK_ROOT = PROJECT_ROOT / 'work'

PAYLOAD_DIR = PROJECT_ROOT / 'app' / 'payload'

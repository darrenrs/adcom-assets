import json
from datetime import UTC, datetime
from pathlib import Path

from .paths import DATA_ROOT


def run_update(title_id: str) -> dict:
  out_dir: Path = DATA_ROOT / title_id
  out_dir.mkdir(parents=True, exist_ok=True)

  status = {
    'titleId': title_id,
    'updatedAt': datetime.now(UTC).isoformat(),
    'note': 'stub pipeline wrote this file',
  }

  (out_dir / 'status.json').write_text(json.dumps(status, indent=2), encoding='utf-8')

  return {'titleId': title_id, 'writtenTo': str(out_dir), 'updatedAt': status['updatedAt']}

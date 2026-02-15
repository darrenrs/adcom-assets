import json
from pathlib import Path
from typing import Any

import aiohttp

from .paths import PAYLOAD_DIR


def ensure_dir(path: Path) -> None:
  path.mkdir(parents=True, exist_ok=True)


async def download_file(session: aiohttp.ClientSession, url: str, destination: Path) -> None:
  async with session.get(url) as response:
    response.raise_for_status()

    with open(destination, 'wb') as f:
      while True:
        chunk = await response.content.read(1024)
        if not chunk:
          break
        f.write(chunk)


def make_http_response(
  *, ok: bool, title_id: str, data_version: str, current_step: str | None, status: str
) -> dict[str, Any]:
  return {
    'ok': ok,
    'parameters': {
      'titleId': title_id,
      'dataVersion': data_version,
    },
    'currentStep': current_step,
    'status': status,
  }


def load_payload(filename: str) -> dict[str, Any]:
  """
  Loads a PlayFab payload file from filesystem

  :param filename: Payload file name
  :type filename: str
  :return: JSON representation of payload
  :rtype: dict[str, Any]
  """
  path = PAYLOAD_DIR / filename

  if not path.exists():
    raise FileNotFoundError(f'Missing payload template: {path}')

  return json.loads(path.read_text(encoding='utf-8'))

import gzip
import json
import shutil
from pathlib import Path
from typing import Any

import aiohttp

from ..common import download_file, ensure_dir
from ..errors import AppError
from ..paths import WORK_ROOT


def _balance_code_to_name(balance_code: str):
  segments = balance_code.split('-')
  return segments[0]


def _write_balance_manifest(title_id: str, manifest: dict[str, Any]) -> None:
  balances = [
    {
      'balanceId': balance_code,
      'assetBalanceId': _balance_code_to_name(balance_code),
    }
    for balance_code in manifest['VersionSettings']['Balance']['Urls']
  ]

  manifest_path = WORK_ROOT / title_id / 'dl_json' / 'balance_manifest.json'
  manifest_path.write_text(
    json.dumps({'balances': balances}, indent=2, sort_keys=True),
    encoding='utf-8',
  )


async def download_json_files(title_id: str, manifest: dict[str, Any], language: str = 'English'):
  out_dir: Path = WORK_ROOT / title_id / 'dl_json'
  # Clean directory before running
  if out_dir.exists():
    shutil.rmtree(out_dir)
  ensure_dir(out_dir)
  _write_balance_manifest(title_id, manifest)

  # (url, file_name)
  files: list[tuple[str, str]] = []

  # Balance files
  balance_base_url = manifest['VersionSettings']['Balance']['BaseURL']
  for k, v in manifest['VersionSettings']['Balance']['Urls'].items():
    files.append((f'{balance_base_url}{v}', _balance_code_to_name(k)))

  # LTE schedule
  files.append((manifest['VersionSettings']['LTESchedule']['Url'], 'LTESchedule'))

  # Leaderboard names (if adcom)
  if title_id == '6bf5':
    files.append((manifest['VersionSettings']['LeaderBoardNames']['Url'], 'LeaderBoardNames'))

  # Localization
  files.append(
    (
      manifest['VersionSettings']['Localization']['BaseURL']
      + manifest['VersionSettings']['Localization']['Urls'][language],
      'Localization',
    )
  )

  async with aiohttp.ClientSession() as session:
    tasks = [
      download_file(session, url, WORK_ROOT / title_id / 'dl_json' / f'{name}.gz')
      for (url, name) in files
    ]
    for f in tasks:
      await f


def gunzip_json_files(title_id: str):
  out_dir: Path = WORK_ROOT / title_id / 'dl_json'

  for gz_file in out_dir.glob('*.gz'):
    base_file_name = gz_file.name[:-3]

    # write Localization file as txt; all others json
    if base_file_name == 'Localization':
      file_name = base_file_name + '.txt'
    else:
      file_name = base_file_name + '.json'

    file_path = out_dir / file_name

    try:
      with gzip.open(gz_file, 'rb') as f:
        raw = f.read()

      if base_file_name == 'Localization':
        # write raw content if localization file
        file_path.write_text(raw.decode('utf-8'), encoding='utf-8')
      else:
        # validate JSON by parsing, then re-write
        parsed = json.loads(raw.decode('utf-8'))
        file_path.write_text(json.dumps(parsed), encoding='utf-8')

    except Exception as e:
      raise AppError(
        code='GUNZIP_PARSE_FAILED',
        message='Failed to gunzip or parse a downloaded file.',
        status_code=502,
        details={'file': str(gz_file)},
      ) from e

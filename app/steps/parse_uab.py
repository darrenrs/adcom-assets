from pathlib import Path
from typing import Any

import aiohttp
import UnityPy

from ..common import download_file
from ..errors import AppError
from ..paths import WORK_ROOT


def _balance_code_to_name(balance_code: str):
  first_segment = balance_code.split('/')[0].split('_')[0]
  return first_segment


async def download_uab_manifest(title_id: str, manifest: dict[str, Any]):
  out_dir: Path = WORK_ROOT / title_id / 'dl_uab'
  out_dir.mkdir(parents=True, exist_ok=True)

  uab_manifest_url = (
    manifest['VersionSettings']['AssetBundle']['BaseURL']
    + 'ios/'
    + manifest['VersionSettings']['AssetBundle']['ManifestID']
  )

  async with aiohttp.ClientSession() as session:
    await download_file(session, uab_manifest_url, WORK_ROOT / title_id / 'dl_uab' / 'uab_manifest')


async def download_uab_all(title_id: str, asset_bundle_base_url: str):
  uab_manifest_path: Path = WORK_ROOT / title_id / 'dl_uab' / 'uab_manifest'

  files: list[tuple[str, str]] = []

  with open(uab_manifest_path, 'rb') as f:
    uab_manifest: UnityPy.Environment = UnityPy.load(f)

  for obj in uab_manifest.objects:
    if obj.type.name == 'AssetBundleManifest':
      uab_manifest_obj = obj.read()
      names = [name for _, name in uab_manifest_obj.AssetBundleNames]

      files: list[tuple[str, str]] = [
        (asset_bundle_base_url + 'ios/' + name, _balance_code_to_name(name)) for name in names
      ]

  async with aiohttp.ClientSession() as session:
    tasks = [
      download_file(session, url, WORK_ROOT / title_id / 'dl_uab' / name) for (url, name) in files
    ]
    for f in tasks:
      await f

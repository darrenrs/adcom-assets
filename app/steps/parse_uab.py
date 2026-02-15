import re
import shutil
from pathlib import Path
from typing import Any

import aiohttp
import UnityPy

from ..common import download_file, ensure_dir
from ..errors import AppError
from ..paths import WORK_ROOT

UAB_MANIFEST_FILE_NAME = 'uab_manifest.unity3d'
REGEX_RESEARCHER_IMAGE = re.compile(r'[A-Z]{2,}\d{2,}')


def _balance_code_to_name(balance_code: str):
  first_segment = balance_code.split('/')[0].split('_')[0]
  return first_segment


async def download_uab_manifest(title_id: str, manifest: dict[str, Any]):
  out_dir: Path = WORK_ROOT / title_id / 'dl_uab'
  # Clean directory before running
  if out_dir.exists():
    shutil.rmtree(out_dir)
  ensure_dir(out_dir)

  uab_manifest_url = (
    manifest['VersionSettings']['AssetBundle']['BaseURL']
    + 'ios/'
    + manifest['VersionSettings']['AssetBundle']['ManifestID']
  )

  async with aiohttp.ClientSession() as session:
    await download_file(
      session, uab_manifest_url, WORK_ROOT / title_id / 'dl_uab' / UAB_MANIFEST_FILE_NAME
    )


async def download_uab_all(title_id: str, asset_bundle_base_url: str):
  uab_manifest_path: Path = WORK_ROOT / title_id / 'dl_uab' / UAB_MANIFEST_FILE_NAME

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
      download_file(session, url, WORK_ROOT / title_id / 'dl_uab' / f'{name}.unity3d')
      for (url, name) in files
    ]
    for f in tasks:
      await f


def extract_uab_all(title_id: str):
  """
  Extract icons from Unity3D asset bundles to organized subdirectories.

  Args:
      directory: Directory containing .unity3d files
      title_id: Title ID for organizing output
      work_root: Root directory for output (default: current directory)
  """
  uab_path: Path = WORK_ROOT / title_id / 'dl_uab'

  for specific_uab_path in uab_path.glob('*.unity3d'):
    # ignore manifest at this point
    if specific_uab_path.name == UAB_MANIFEST_FILE_NAME:
      continue

    specific_uab_file = UnityPy.load(str(specific_uab_path))
    bundle_name = specific_uab_path.stem  # filename without extension

    output_dir = uab_path / bundle_name
    ensure_dir(output_dir)

    # Iterate through all objects in the bundle
    for obj in specific_uab_file.objects:
      if obj.type.name == 'MonoBehaviour':
        try:
          # Read the typetree to access IconSet
          tree = obj.read_typetree()

          # Check if this has an Icons field (IconSet)
          icon_set = tree.get('Icons', {})
          keys = icon_set.get('m_keys', [])
          vals = icon_set.get('m_values', [])

          # Need owner serialized file to resolve fileID==0 references
          owner_sf = obj.assets_file

          # Export local sprites only (m_FileID == 0)
          for key, v in zip(keys, vals):
            if not isinstance(v, dict):
              continue

            pid = int(v.get('m_PathID', 0))

            # Resolve within same serialized file
            target = owner_sf.objects.get(pid)

            spr = target.parse_as_object()
            img = getattr(spr, 'image', None)
            if img is None:
              continue

            out_path = output_dir / f'{str(key)}.png'
            img.save(out_path)

        except AttributeError as e:
          # Does not contain an IconSet
          pass
        except Exception as e:
          # TODO: Add to log file in future
          print(e)
          pass
      elif obj.type.name in ['Texture2D', 'Sprite']:
        img = obj.parse_as_object()
        name = img.m_Name

        out_path = output_dir / f'{name}.png'

        # save all in certain special bundles or if it is a researcher/core image
        if (
          bundle_name in ['ltehistory', 'avatars']
          or REGEX_RESEARCHER_IMAGE.match(name)
          or (name.startswith('icon-rank') and bundle_name == 'evergreen')
          or name == 'science'
          or name == 'LeavingLteScreenGeneral'
          or name == 'WelcomeBack [BG]'
        ):
          img.image.save(out_path)

import json
import re
import shutil
from pathlib import Path

from ..common import ensure_dir
from ..errors import AppError
from ..paths import DATA_ROOT, STATIC_ROOT, WORK_ROOT

REGEX_RESEARCHER_IMAGE_FILENAME = re.compile(r'[A-Z]{2,}\d{2,}\.png')
EFFECT_ICON_IMAGE_FILENAMES = [
  'cards.png',
  'crit.png',
  'flag.png',
  'output.png',
  'power.png',
  'price.png',
  'science.png',
  'speed.png',
]


def _normalize_balance_name(title_id: str, balance_name: str) -> str:
  if title_id == 'dc4bb' and balance_name.startswith('fusion') and balance_name != 'fusion':
    remapped = balance_name[len('fusion') :]
    if remapped:
      return remapped
  return balance_name


def _ltehistory_source_name(title_id: str, balance_name: str) -> str:
  # Bundle aliases can differ from ltehistory stem names.
  if title_id == 'dc4bb' and balance_name == 'monster':
    return 'halloween'
  return balance_name


def _copy_file(src: Path, dst: Path) -> None:
  ensure_dir(dst.parent)
  if not src.exists():
    raise AppError(
      code='FINALIZE_SOURCE_MISSING',
      message='Expected source asset was missing during finalize.',
      status_code=500,
      details={'src': str(src), 'dst': str(dst)},
    )
  shutil.copyfile(src, dst)


def _copy_tree(src: Path, dst: Path) -> None:
  if not src.exists():
    return
  ensure_dir(dst)
  shutil.copytree(src, dst, dirs_exist_ok=True)


def _copy_file_if_exists(src: Path, dst: Path) -> bool:
  if not src.exists():
    return False
  _copy_file(src, dst)
  return True


def _replace_common_prefixed_assets(
  src_dir: Path, dst_dir: Path, filename_prefixes: list[str]
) -> None:
  files = sorted(
    file
    for filename_prefix in filename_prefixes
    for file in src_dir.glob(f'{filename_prefix}_*.png')
  )
  if not files:
    return

  if dst_dir.exists():
    shutil.rmtree(dst_dir)
  ensure_dir(dst_dir)

  for file in files:
    _copy_file(file, dst_dir / file.name)


def arrange_assets(title_id: str) -> None:
  """Finalize extracted assets into a normalized staging directory.

  Input:
    work/<title_id>/dl_uab/<asset_bundle_name>/...

  Output:
    work/<title_id>/staging/<normalized tree>

  Notes:
  - This step is intentionally “rules-heavy” and mirrors the known-good 2024 behavior.
  - Later pipeline steps can promote staging -> public data directory atomically.
  """

  src_dir = WORK_ROOT / title_id / 'dl_uab'
  out_dir = WORK_ROOT / title_id / 'staging'
  # Clean directory before running
  if out_dir.exists():
    shutil.rmtree(out_dir)
  ensure_dir(out_dir)
  # Static resources are fallbacks. Extracted deterministic assets below can overwrite them.
  _copy_tree(STATIC_ROOT / title_id, out_dir)

  uab_path_evergreen = src_dir / 'evergreen'
  uab_path_common = src_dir / 'common'
  uab_path_ltehistory = src_dir / 'ltehistory'

  # Copy all avatars
  _copy_tree(src_dir / 'avatars', out_dir / 'avatars')

  # Shared icons from evergreen -> common
  shared_dir = out_dir / 'common'
  ensure_dir(shared_dir)

  # Upgrade icons
  src_upg_evg = uab_path_evergreen / 'mission-upgrade.png'
  dst_upg_evg = shared_dir / 'upgrade.png'
  _copy_file(src_upg_evg, dst_upg_evg)

  src_upg_lte = uab_path_common / 'mission-upgrade.png'
  dst_upg_lte = shared_dir / 'upgrade_lte.png'
  _copy_file(src_upg_lte, dst_upg_lte)

  # dc4bb common timehacks are shared assets served from /common/timehack/*
  if title_id == 'dc4bb':
    for file in uab_path_common.iterdir():
      if not file.is_file():
        continue
      if not file.name.startswith('timehack_') or not file.name.endswith('.png'):
        continue
      _copy_file(file, shared_dir / 'timehack' / file.name)
  elif title_id == '6bf5':
    _replace_common_prefixed_assets(
      src_dir=uab_path_common,
      dst_dir=shared_dir / 'experiments',
      filename_prefixes=['blitz', 'surge'],
    )

  # Prepare balance directories
  def ensure_balance_dirs(balance_name: str) -> dict[str, Path]:
    bal_dir = out_dir / balance_name
    ensure_dir(bal_dir)
    ensure_dir(bal_dir / 'effects')
    ensure_dir(bal_dir / 'icon')
    ensure_dir(bal_dir / 'researcher')
    if title_id == '6bf5':
      ensure_dir(bal_dir / 'rank')
    return {
      'root': bal_dir,
      'effects': bal_dir / 'effects',
      'icon': bal_dir / 'icon',
      'researcher': bal_dir / 'researcher',
      'rank': bal_dir / 'rank',
    }

  # Researcher images + resource icons per bundle
  for bundle_dir in [p for p in src_dir.iterdir() if p.is_dir()]:
    source_balance_name = bundle_dir.name

    # Skip non-balance or handled elsewhere
    if source_balance_name in ['common', 'ltehistory', 'fusion', 'avatars']:
      continue

    balance_name = _normalize_balance_name(title_id=title_id, balance_name=source_balance_name)
    bal_paths = ensure_balance_dirs(balance_name)
    effect_name_by_variant_filename = {
      f'{effect_file[:-4]}_effect.png': effect_file
      for effect_file in EFFECT_ICON_IMAGE_FILENAMES
      if (bundle_dir / f'{effect_file[:-4]}_effect.png').exists()
    }
    icon_effect_conflict_filenames = set(effect_name_by_variant_filename.values())

    # Handle resource and researcher images
    for file in bundle_dir.iterdir():
      if REGEX_RESEARCHER_IMAGE_FILENAME.match(file.name):
        _copy_file(file, bal_paths['researcher'] / file.name)
      elif file.name == 'WelcomeBack [BG].png':
        # Special-case banner art; handled via evergreen -> banner.png mapping only.
        continue
      elif file.name in effect_name_by_variant_filename:
        _copy_file(file, bal_paths['effects'] / effect_name_by_variant_filename[file.name])
      elif file.name in EFFECT_ICON_IMAGE_FILENAMES:
        if file.name in icon_effect_conflict_filenames:
          _copy_file(file, bal_paths['icon'] / file.name)
        else:
          _copy_file(file, bal_paths['effects'] / file.name)
      elif file.name == 'propaganda_boost_on.png':
        _copy_file(file, bal_paths['root'] / 'propaganda' / 'propaganda_boost_on.png')
      elif not file.name.startswith('icon-rank-'):
        _copy_file(file, bal_paths['icon'] / file.name)

    # Copy "icon" and "image" from ltehistory or evergreen into balance root
    if balance_name != 'evergreen':
      ltehistory_balance_name = _ltehistory_source_name(
        title_id=title_id,
        balance_name=source_balance_name,
      )
      ltehistory_icon_file = f'{ltehistory_balance_name}icon.png'
      ltehistory_banner_file = f'{ltehistory_balance_name}image.png'
      _copy_file(uab_path_ltehistory / ltehistory_icon_file, bal_paths['root'] / 'icon.png')
      _copy_file(uab_path_ltehistory / ltehistory_banner_file, bal_paths['root'] / 'banner.png')
    else:
      evergreen_icon_file = 'multi-industry.png'
      _copy_file(uab_path_evergreen / evergreen_icon_file, bal_paths['root'] / 'icon.png')

      if title_id == '6bf5':
        evergreen_banner_file = 'LeavingLteScreenGeneral.png'
        _copy_file(uab_path_common / evergreen_banner_file, bal_paths['root'] / 'banner.png')
      elif title_id == 'dc4bb':
        evergreen_banner_file = 'WelcomeBack [BG].png'
        _copy_file(uab_path_evergreen / evergreen_banner_file, bal_paths['root'] / 'banner.png')

    # Evergreen uses a custom alias for science effect icon.
    if balance_name == 'evergreen':
      _copy_file_if_exists(
        bal_paths['effects'] / 'science.png',
        bal_paths['icon'] / 'scientist.png',
      )

    # AdCom only: copy darkscience from common into each balance
    if title_id == '6bf5':
      src = uab_path_common / 'darkscience.png'
      dst = bal_paths['icon'] / 'darkscience.png'
      _copy_file(src, dst)

    # Common folder for fusions (only AdCom)
    shared_fusion_dir = src_dir / 'fusion'
    if shared_fusion_dir.exists() and balance_name.startswith('fus'):
      _copy_tree(shared_fusion_dir, bal_paths['icon'])
      if title_id == '6bf5':
        _copy_file_if_exists(
          shared_fusion_dir / 'propaganda_boost_on.png',
          bal_paths['root'] / 'propaganda' / 'propaganda_boost_on.png',
        )

  # Global icon.png (copy from evergreen/multi-industry.png -> staging/icon.png)
  _copy_file(out_dir / 'evergreen' / 'icon.png', out_dir / 'icon.png')

  # Rank icons (AdCom only)
  if title_id == '6bf5':
    # evergreen rank icons -> evergreen/rank/<num>.png
    bal_paths = ensure_balance_dirs('evergreen')
    for file in uab_path_evergreen.iterdir():
      if not file.is_file():
        continue
      if 'icon-rank-' not in file.name.lower():
        continue
      nums = re.findall(r'\d+', file.name)
      if not nums:
        continue
      rank_num = nums[0]
      _copy_file(file, bal_paths['rank'] / f'{rank_num}.png')

    # ltehistory rank icons -> <balance>/rank/<num>.png (fusion propagated)
    for file in uab_path_ltehistory.iterdir():
      if not file.is_file():
        continue
      filename_lower = file.name.lower()
      if 'rank' not in filename_lower:
        continue
      nums = re.findall(r'\d+', file.name)
      if not nums:
        continue
      rank_num = nums[0]

      # balance id is the prefix up to 'rank'
      idx = filename_lower.index('rank')
      balance_id = filename_lower[:idx]
      balance_id = balance_id.replace('-', '').replace('_', '').strip()

      if not balance_id:
        continue

      if balance_id == 'fusion':
        for fusion_name in [
          str(p)
          for p in out_dir.iterdir()
          if p.is_dir() and 'fus' in str(p) and 'fusion' not in str(p)
        ]:
          bal_paths = ensure_balance_dirs(fusion_name)
          _copy_file(file, bal_paths['rank'] / f'{rank_num}.png')
      else:
        bal_paths = ensure_balance_dirs(balance_id)
        _copy_file(file, bal_paths['rank'] / f'{rank_num}.png')


def arrange_json(title_id: str) -> None:
  json_dir: Path = WORK_ROOT / title_id / 'dl_json'

  for json_file in json_dir.glob('*.json'):
    base_file_name = json_file.name[:-5]
    out_dir: Path = WORK_ROOT / title_id / 'staging' / base_file_name

    if base_file_name in ['LeaderBoardNames', 'LTESchedule', 'common']:
      continue

    _copy_file(json_file, out_dir / 'balance.json')

  _copy_file(json_dir / 'common.json', WORK_ROOT / title_id / 'staging' / 'common.json')
  _copy_file(json_dir / 'LTESchedule.json', WORK_ROOT / title_id / 'staging' / 'schedule.json')
  _copy_file(json_dir / 'Localization.txt', WORK_ROOT / title_id / 'staging' / 'localization.txt')

  if title_id == '6bf5':
    _copy_file(
      json_dir / 'LeaderBoardNames.json', WORK_ROOT / title_id / 'staging' / 'leaderboardnames.json'
    )


def move_staging_to_data(title_id: str, data_version: str, current_time_str: str) -> None:
  src_dir = WORK_ROOT / title_id / 'staging'
  dst_dir = DATA_ROOT / title_id

  # Clean directory before running
  if dst_dir.exists():
    shutil.rmtree(dst_dir)

  _copy_tree(src_dir, dst_dir)

  (dst_dir / 'status.json').write_text(
    json.dumps(
      {'titleId': title_id, 'dataVersion': data_version, 'jobCompleteAt': current_time_str}
    ),
    encoding='utf-8',
  )

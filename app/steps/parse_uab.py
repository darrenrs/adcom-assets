import re
import shutil
from math import ceil
from pathlib import Path
from typing import Any

import aiohttp
import UnityPy
from PIL import Image

from ..common import download_file, ensure_dir
from ..paths import WORK_ROOT

UAB_MANIFEST_FILE_NAME = 'uab_manifest.unity3d'
REGEX_RESEARCHER_IMAGE = re.compile(r'[A-Z]{2,}\d{2,}')
EFFECT_ICON_NAMES = [
  'cards',
  'crit',
  'flag',
  'output',
  'power',
  'price',
  'science',
  'speed',
]
RESEARCHER_EFFECTS_ASSET_NAME = 'Researcher Effects'


def _balance_code_to_name(title_id: str, balance_code: str):
  first_segment = balance_code.split('/')[0].split('_')[0]
  # Manual title-specific bundle aliases
  if title_id == 'dc4bb' and first_segment == 'halloween':
    return 'monster'
  return first_segment


def _effect_conflict_output_path(output_dir: Path, name: str, has_icon_key_conflict: bool) -> Path:
  """When IconSet and raw sprite names collide, preserve both assets."""
  default_path = output_dir / f'{name}.png'
  if name in EFFECT_ICON_NAMES and has_icon_key_conflict:
    return output_dir / f'{name}_effect.png'
  return default_path


def _extract_bundle_dependencies(title_id: str, uab_path: Path) -> dict[str, list[str]]:
  uab_manifest_path = uab_path / UAB_MANIFEST_FILE_NAME
  if not uab_manifest_path.exists():
    return {}

  with open(uab_manifest_path, 'rb') as f:
    uab_manifest: UnityPy.Environment = UnityPy.load(f)

  for obj in uab_manifest.objects:
    if obj.type.name != 'AssetBundleManifest':
      continue

    manifest = obj.read()
    name_by_index = {
      index: _balance_code_to_name(title_id, bundle_name)
      for index, bundle_name in manifest.AssetBundleNames
    }
    return {
      name_by_index[index]: [
        name_by_index[dependency_index]
        for dependency_index in bundle_info.AssetBundleDependencies
        if dependency_index in name_by_index
      ]
      for index, bundle_info in manifest.AssetBundleInfos
      if index in name_by_index
    }

  return {}


def _dependency_paths_for_bundle(
  uab_path: Path, bundle_name: str, dependencies_by_bundle: dict[str, list[str]]
) -> list[Path]:
  return [
    dependency_path
    for dependency_name in dependencies_by_bundle.get(bundle_name, [])
    if (dependency_path := uab_path / f'{dependency_name}.unity3d').exists()
  ]


def _external_objects_by_file_id(
  owner_assets_file: Any, dependency_envs: list[Any]
) -> dict[int, Any]:
  dependency_assets_by_name = {
    dependency_asset.name: dependency_asset
    for dependency_env in dependency_envs
    for dependency_asset in dependency_env.assets
    if getattr(dependency_asset, 'name', None)
  }

  return {
    file_id: dependency_assets_by_name[external.name].objects
    for file_id, external in enumerate(getattr(owner_assets_file, 'externals', []), start=1)
    if external.name in dependency_assets_by_name
  }


def _resolve_pptr_object(
  owner_assets_file: Any, pointer: dict[str, Any], external_objects_by_id: dict[int, Any]
) -> Any | None:
  file_id = int(pointer.get('m_FileID', 0))
  path_id = int(pointer.get('m_PathID', 0))

  if file_id == 0:
    return owner_assets_file.objects.get(path_id)

  external_objects = external_objects_by_id.get(file_id)
  if external_objects is None:
    return None
  return external_objects.get(path_id)


def _matching_sprite_atlas_names(sprite: Any) -> list[str]:
  assets_file = getattr(sprite, 'assets_file', None)
  render_data_key = getattr(sprite, 'm_RenderDataKey', None)
  if assets_file is None or render_data_key is None:
    return []

  atlas_names: list[str] = []
  for obj in assets_file.objects.values():
    if obj.type.name != 'SpriteAtlas':
      continue
    atlas = obj.read()
    if any(key == render_data_key for key, _value in atlas.m_RenderDataMap):
      atlas_names.append(atlas.m_Name)

  return atlas_names


def _image_from_sprite(sprite: Any) -> Image.Image | None:
  try:
    return sprite.image
  except Exception:
    pass

  original_atlas_tags = list(getattr(sprite, 'm_AtlasTags', []) or [])
  try:
    for atlas_name in _matching_sprite_atlas_names(sprite):
      sprite.m_AtlasTags = [atlas_name]
      try:
        return sprite.image
      except Exception:
        continue
  finally:
    sprite.m_AtlasTags = original_atlas_tags

  return None


def _image_from_asset(asset: Any) -> Image.Image | None:
  if asset.type.name == 'Texture2D':
    data = asset.parse_as_object()
    return getattr(data, 'image', None)

  if asset.type.name == 'Sprite':
    data = asset.parse_as_object()
    return _image_from_sprite(data)

  return None


def _save_missing_researcher_effects(
  *,
  objects: list[Any],
  objects_by_path_id: dict[int, Any],
  output_dir: Path,
  icon_keys_exported: set[str],
) -> None:
  missing_effect_names = [
    name
    for name in EFFECT_ICON_NAMES
    if not _effect_conflict_output_path(
      output_dir=output_dir,
      name=name,
      has_icon_key_conflict=name in icon_keys_exported,
    ).exists()
  ]
  if not missing_effect_names:
    return

  researcher_effects_tree: dict[str, Any] | None = None
  owner_assets_file: Any | None = None
  for obj in objects:
    if obj.type.name != 'MonoBehaviour':
      continue
    try:
      tree = obj.read_typetree()
    except Exception:
      continue
    if tree.get('m_Name') != RESEARCHER_EFFECTS_ASSET_NAME:
      continue
    researcher_effects_tree = tree
    owner_assets_file = obj.assets_file
    break

  if researcher_effects_tree is None or owner_assets_file is None:
    return

  sprite_sheet_pointer = researcher_effects_tree.get('spriteSheet', {})
  if not isinstance(sprite_sheet_pointer, dict):
    return
  if int(sprite_sheet_pointer.get('m_FileID', 0)) != 0:
    return

  sprite_sheet_path_id = int(sprite_sheet_pointer.get('m_PathID', 0))
  sprite_sheet_obj = objects_by_path_id.get(sprite_sheet_path_id)
  if sprite_sheet_obj is None or sprite_sheet_obj.type.name != 'Texture2D':
    return

  sprite_sheet = sprite_sheet_obj.parse_as_object().image.convert('RGBA')
  name_by_glyph_index = {
    entry.get('m_GlyphIndex'): entry.get('m_Name')
    for entry in researcher_effects_tree.get('m_SpriteCharacterTable', [])
    if entry.get('m_Name') in missing_effect_names
  }

  for glyph in researcher_effects_tree.get('m_GlyphTable', []):
    effect_name = name_by_glyph_index.get(glyph.get('m_Index'))
    if effect_name is None:
      continue

    glyph_rect = glyph.get('m_GlyphRect', {})
    x = int(round(float(glyph_rect.get('m_X', 0))))
    y = int(round(float(glyph_rect.get('m_Y', 0))))
    width = int(round(float(glyph_rect.get('m_Width', 0))))
    height = int(round(float(glyph_rect.get('m_Height', 0))))
    if width <= 0 or height <= 0:
      continue

    effect = sprite_sheet.crop(
      (x, sprite_sheet.height - y - height, x + width, sprite_sheet.height - y)
    )
    out_path = _effect_conflict_output_path(
      output_dir=output_dir,
      name=effect_name,
      has_icon_key_conflict=effect_name in icon_keys_exported,
    )
    effect.save(out_path)


def _select_propaganda_material_tree(
  objects: list[Any], material_name: str = 'Propaganda Active'
) -> dict[str, Any] | None:
  for obj in objects:
    if obj.type.name != 'Material':
      continue
    data = obj.parse_as_object()
    if getattr(data, 'm_Name', '') != material_name:
      continue
    return obj.read_typetree()
  return None


def _select_texture_from_material(
  objects_by_path_id: dict[int, Any], material_tree: dict[str, Any]
) -> Any | None:
  saved = material_tree.get('m_SavedProperties', {})
  tex_envs = saved.get('m_TexEnvs', [])
  for key, value in tex_envs:
    if key != '_MainTex' or not isinstance(value, dict):
      continue
    texture_ptr = value.get('m_Texture', {})
    if not isinstance(texture_ptr, dict):
      continue
    if texture_ptr.get('m_FileID') != 0:
      continue
    path_id = texture_ptr.get('m_PathID')
    if not isinstance(path_id, int):
      continue
    local_obj = objects_by_path_id.get(path_id)
    if local_obj is None or local_obj.type.name != 'Texture2D':
      continue
    return local_obj.parse_as_object()
  return None


def _select_named_texture(objects: list[Any], texture_name: str) -> Any | None:
  for obj in objects:
    if obj.type.name != 'Texture2D':
      continue
    texture = obj.parse_as_object()
    if getattr(texture, 'm_Name', '') == texture_name:
      return texture
  return None


def _select_named_sprite(objects: list[Any], sprite_name: str) -> Any | None:
  for obj in objects:
    if obj.type.name != 'Sprite':
      continue
    sprite = obj.parse_as_object()
    if getattr(sprite, 'm_Name', '') == sprite_name:
      return sprite
  return None


def _extract_propaganda_frames(
  texture_image: Image.Image,
  frame_width: int,
  frame_height: int,
  frame_count: int,
  columns: int,
  left_offset_px: int = 0,
  bottom_offset_px: int = 0,
) -> list[Image.Image]:
  if frame_width <= 0 or frame_height <= 0 or frame_count <= 0:
    return []
  if columns <= 0:
    return []

  rows = ceil(frame_count / columns)
  if (
    left_offset_px < 0
    or bottom_offset_px < 0
    or left_offset_px + frame_width * columns > texture_image.width
    or bottom_offset_px + frame_height * rows > texture_image.height
  ):
    return []

  frames: list[Image.Image] = []
  for frame_idx in range(frame_count):
    col = frame_idx % columns
    row = frame_idx // columns
    left = left_offset_px + col * frame_width
    # Unity UV space is bottom-left origin, so frame row 0 starts from the texture bottom.
    upper = texture_image.height - bottom_offset_px - (row + 1) * frame_height
    right = left + frame_width
    lower = upper + frame_height
    frames.append(texture_image.crop((left, upper, right, lower)))
  return frames


def _save_propaganda_on_asset(
  *,
  title_id: str,
  objects: list[Any],
  objects_by_path_id: dict[int, Any],
  output_dir: Path,
) -> None:
  propaganda_output_path = output_dir / 'propaganda_boost_on.png'

  if title_id == 'dc4bb':
    # dc4bb on-state is a single static sprite.
    for obj in objects:
      if obj.type.name != 'Sprite':
        continue
      sprite = obj.parse_as_object()
      if getattr(sprite, 'm_Name', '') != 'AdWatch [Character]':
        continue
      sprite.image.save(propaganda_output_path)
      return

    texture = _select_named_texture(objects, 'AdWatch [Character]')
    if texture is not None:
      texture.image.save(propaganda_output_path)
    return

  if title_id != '6bf5':
    return

  # 6bf5 on-state is an animated flipbook texture.
  material_tree = _select_propaganda_material_tree(objects)
  if material_tree is None:
    # Fallback for bundles that only expose a plain propaganda texture/sprite.
    sprite = _select_named_sprite(objects, 'Propaganda Active')
    if sprite is not None:
      sprite.image.save(propaganda_output_path)
      return
    texture = _select_named_texture(objects, 'Propaganda Active')
    if texture is not None:
      texture.image.save(propaganda_output_path)
    return

  saved = material_tree.get('m_SavedProperties', {})
  floats = dict(saved.get('m_Floats', []))

  frame_width = int(round(float(floats.get('_Atlas0FrameSizeX', 0))))
  frame_height = int(round(float(floats.get('_Atlas0FrameSizeY', 0))))
  frame_count = int(round(float(floats.get('_Atlas0FramesInSheet', 0))))
  fps = max(float(floats.get('_Atlas0FPS', 15.0)), 1.0)
  columns = int(round(float(floats.get('_Atlas0ScaleX', 0))))

  texture = _select_texture_from_material(objects_by_path_id, material_tree)
  if texture is None:
    texture = _select_named_texture(objects, 'Propaganda Active')
  if texture is None:
    return

  left_offset_px = max(0, int(round(float(floats.get('_Atlas0Left', 0.0)) * texture.image.width)))
  bottom_offset_px = max(
    0, int(round(float(floats.get('_Atlas0Bottom', 0.0)) * texture.image.height))
  )

  frames = _extract_propaganda_frames(
    texture_image=texture.image.convert('RGBA'),
    frame_width=frame_width,
    frame_height=frame_height,
    frame_count=frame_count,
    columns=columns,
    left_offset_px=left_offset_px,
    bottom_offset_px=bottom_offset_px,
  )
  if not frames:
    # Some bundles expose atlas offsets that don't map cleanly to pixel bounds.
    # Retry from origin before giving up on animation.
    frames = _extract_propaganda_frames(
      texture_image=texture.image.convert('RGBA'),
      frame_width=frame_width,
      frame_height=frame_height,
      frame_count=frame_count,
      columns=columns,
      left_offset_px=0,
      bottom_offset_px=0,
    )
  if not frames:
    # Fallback to a static output if frame slicing metadata is unusable.
    texture.image.save(propaganda_output_path)
    return

  frame_duration_ms = max(1, int(round(1000 / fps)))
  frames[0].save(
    propaganda_output_path,
    format='PNG',
    save_all=True,
    append_images=frames[1:],
    duration=frame_duration_ms,
    loop=0,
  )


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
        (asset_bundle_base_url + 'ios/' + name, _balance_code_to_name(title_id, name))
        for name in names
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
  dependencies_by_bundle = _extract_bundle_dependencies(title_id=title_id, uab_path=uab_path)

  for specific_uab_path in uab_path.glob('*.unity3d'):
    # ignore manifest at this point
    if specific_uab_path.name == UAB_MANIFEST_FILE_NAME:
      continue

    specific_uab_file = UnityPy.load(str(specific_uab_path))
    bundle_name = specific_uab_path.stem  # filename without extension
    dependency_files = [
      UnityPy.load(str(dependency_path))
      for dependency_path in _dependency_paths_for_bundle(
        uab_path=uab_path,
        bundle_name=bundle_name,
        dependencies_by_bundle=dependencies_by_bundle,
      )
    ]
    bundle_objects = list(specific_uab_file.objects)
    objects_by_path_id: dict[int, Any] = {
      obj.path_id: obj for obj in bundle_objects if hasattr(obj, 'path_id')
    }

    output_dir = uab_path / bundle_name
    if output_dir.exists():
      shutil.rmtree(output_dir)
    ensure_dir(output_dir)

    _save_propaganda_on_asset(
      title_id=title_id,
      objects=bundle_objects,
      objects_by_path_id=objects_by_path_id,
      output_dir=output_dir,
    )

    icon_keys_exported: set[str] = set()

    # Pass 1: export IconSet key->sprite mappings.
    for obj in bundle_objects:
      if obj.type.name != 'MonoBehaviour':
        continue

      try:
        # Read the typetree to access IconSet
        tree = obj.read_typetree()

        # Check if this has an Icons field (IconSet)
        icon_set = tree.get('Icons', {})
        keys = icon_set.get('m_keys', [])
        vals = icon_set.get('m_values', [])

        owner_sf = obj.assets_file
        external_objects_by_id = _external_objects_by_file_id(
          owner_assets_file=owner_sf,
          dependency_envs=dependency_files,
        )

        for key, v in zip(keys, vals, strict=False):
          if not isinstance(v, dict):
            continue

          target = _resolve_pptr_object(
            owner_assets_file=owner_sf,
            pointer=v,
            external_objects_by_id=external_objects_by_id,
          )
          if target is None:
            continue

          try:
            spr = target.parse_as_object()
          except Exception:
            continue

          img = _image_from_sprite(spr)
          if img is None:
            continue

          key_name = str(key)
          out_path = output_dir / f'{key_name}.png'
          img.save(out_path)
          icon_keys_exported.add(key_name)

      except AttributeError as e:
        # Does not contain an IconSet
        print('AttributeError:', e)
        pass
      except Exception as e:
        # TODO: Add to log file in future
        print('Exception', e)
        pass

    # Pass 2: export direct sprite/texture names.
    for obj in bundle_objects:
      if obj.type.name in ['Texture2D', 'Sprite']:
        img = obj.parse_as_object()
        name = img.m_Name

        out_path = _effect_conflict_output_path(
          output_dir=output_dir,
          name=name,
          has_icon_key_conflict=name in icon_keys_exported,
        )

        # save all in certain special bundles or if it is a researcher/core image
        if (
          bundle_name in ['ltehistory', 'avatars']
          or REGEX_RESEARCHER_IMAGE.match(name)
          or (name.startswith('icon-rank') and bundle_name == 'evergreen')
          or name == 'science'
          or name == 'LeavingLteScreenGeneral'
          or name == 'WelcomeBack [BG]'
          or name in EFFECT_ICON_NAMES
        ):
          asset_image = _image_from_asset(obj)
          if asset_image is not None:
            asset_image.save(out_path)

    _save_missing_researcher_effects(
      objects=bundle_objects,
      objects_by_path_id=objects_by_path_id,
      output_dir=output_dir,
      icon_keys_exported=icon_keys_exported,
    )

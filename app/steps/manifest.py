import json
from typing import Any

import requests

from app.errors import AppError, InvalidVersionError, ManifestSchemaError

from ..common import load_payload
from ..paths import WORK_ROOT


def _require_dict(obj: Any, path: str) -> dict[str, Any]:
  if not isinstance(obj, dict):
    raise ManifestSchemaError(path=path, expected='object/dict', got=obj)
  return obj


def _require_str(obj: Any, path: str) -> str:
  if not isinstance(obj, str) or not obj.strip():
    raise ManifestSchemaError(path=path, expected='non-empty string', got=obj)
  return obj


def _require_key(d: dict[str, Any], key: str, path: str) -> Any:
  if key not in d:
    raise ManifestSchemaError(path=f'{path}.{key}', expected='key to be present', got=None)
  return d[key]


def _validate_manifest_schema(manifest: Any) -> None:
  """
  Schema validation for Manifest

  :param manifest: Manifest JSON
  :type manifest: Any
  """
  m = _require_dict(manifest, 'manifest')

  vs = _require_dict(_require_key(m, 'VersionSettings', 'manifest'), 'manifest.VersionSettings')

  # AssetBundle
  ab = _require_dict(
    _require_key(vs, 'AssetBundle', 'manifest.VersionSettings'),
    'manifest.VersionSettings.AssetBundle',
  )
  _require_str(
    _require_key(ab, 'BaseURL', 'manifest.VersionSettings.AssetBundle'),
    'manifest.VersionSettings.AssetBundle.BaseURL',
  )
  _require_str(
    _require_key(ab, 'ManifestID', 'manifest.VersionSettings.AssetBundle'),
    'manifest.VersionSettings.AssetBundle.ManifestID',
  )

  # Balance
  bal = _require_dict(
    _require_key(vs, 'Balance', 'manifest.VersionSettings'), 'manifest.VersionSettings.Balance'
  )
  _require_str(
    _require_key(bal, 'BaseURL', 'manifest.VersionSettings.Balance'),
    'manifest.VersionSettings.Balance.BaseURL',
  )
  bal_urls = _require_key(bal, 'Urls', 'manifest.VersionSettings.Balance')
  if not isinstance(bal_urls, dict) or not bal_urls:
    raise ManifestSchemaError(
      path='manifest.VersionSettings.Balance.Urls', expected='non-empty object/dict', got=bal_urls
    )

  # Localization
  loc = _require_dict(
    _require_key(vs, 'Localization', 'manifest.VersionSettings'),
    'manifest.VersionSettings.Localization',
  )
  _require_str(
    _require_key(loc, 'BaseURL', 'manifest.VersionSettings.Localization'),
    'manifest.VersionSettings.Localization.BaseURL',
  )
  loc_urls = _require_key(loc, 'Urls', 'manifest.VersionSettings.Localization')
  if not isinstance(loc_urls, dict) or not loc_urls:
    raise ManifestSchemaError(
      path='manifest.VersionSettings.Localization.Urls',
      expected='non-empty object/dict',
      got=loc_urls,
    )

  # LTESchedule
  lte = _require_dict(
    _require_key(vs, 'LTESchedule', 'manifest.VersionSettings'),
    'manifest.VersionSettings.LTESchedule',
  )
  _require_str(
    _require_key(lte, 'Url', 'manifest.VersionSettings.LTESchedule'),
    'manifest.VersionSettings.LTESchedule.Url',
  )


def get_manifest(title_id: str, session_ticket: str, data_version: str) -> dict[str, Any]:
  """
  Get game manifest file from PlayFab

  :param title_id: Title ID
  :type title_id: str
  :param session_ticket: Session Ticket
  :type session_ticket: str
  :param data_version: Version of the game (typically in the format x.y)
  :type data_version: str
  :return: Manifest as a JSON object
  :rtype: dict[str, Any]
  """
  body = load_payload('ExecuteCloudScript_DataConfig.json')
  body['FunctionParameter']['DataVersion'] = data_version

  url = f'https://{title_id}.playfabapi.com/Client/ExecuteCloudScript'
  headers = {
    'Content-Type': 'application/json',
    'X-Authorization': session_ticket,
  }

  r = requests.post(url, json=body, headers=headers, timeout=30)
  r.raise_for_status()
  payload = r.json()

  # Manifest is stored as a string in the FunctionResult
  # If missing, an invalid version was likely specified
  try:
    raw_result = payload['data']['FunctionResult']
  except Exception as e:
    raise InvalidVersionError(data_version) from e

  # Parse response as JSON
  try:
    manifest = json.loads(raw_result)
  except Exception as e:
    snippet = raw_result
    if isinstance(snippet, str) and len(snippet) > 500:
      snippet = snippet[:500] + '...'
    raise AppError(
      code='MANIFEST_PARSE_ERROR',
      message='Failed to parse manifest response from PlayFab.',
      status_code=502,
      details={'rawSnippet': snippet},
    ) from e

  _validate_manifest_schema(manifest)
  return manifest


def write_manifest_to_disk(title_id: str, manifest: dict[str, Any]) -> None:
  out_dir = WORK_ROOT / title_id
  out_dir.mkdir(parents=True, exist_ok=True)
  (out_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')

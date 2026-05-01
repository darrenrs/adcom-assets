import json  # noqa: I001
import re
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .common import ensure_dir, make_http_response
from .errors import AppError, VersionDowngradeError
from .paths import DATA_ROOT, WORK_ROOT
from .steps.auth import login_session_ticket
from .steps.manifest import get_manifest, write_manifest_to_disk
from .steps.parse_json import download_json_files, gunzip_json_files
from .steps.parse_uab import download_uab_manifest, download_uab_all, extract_uab_all
from .steps.finalize import arrange_assets, arrange_json, move_staging_to_data


def _now() -> str:
  return datetime.now(UTC).isoformat()


def _add_step(steps: list[dict[str, Any]], step_name: str, ok: bool) -> None:
  steps.append({'step': step_name, 'ok': ok, 'completeAt': _now()})


_VERSION_PATTERN = re.compile(r'^\d+(?:\.\d+)*$')


def _parse_version(version: str) -> tuple[int, ...]:
  if not _VERSION_PATTERN.fullmatch(version):
    raise AppError(
      code='INVALID_DATA_VERSION_FORMAT',
      message=f'Invalid dataVersion {version}. Expected digits separated by dots.',
      status_code=400,
      details={'dataVersion': version},
    )
  return tuple(int(part) for part in version.split('.'))


def _read_current_data_version(title_id: str) -> str | None:
  status_path = DATA_ROOT / title_id / 'status.json'
  if not status_path.exists():
    return None

  try:
    payload = json.loads(status_path.read_text(encoding='utf-8'))
  except Exception as e:
    raise AppError(
      code='DATA_STATUS_PARSE_ERROR',
      message='Failed to parse current data status for version checks.',
      status_code=500,
      details={'path': str(status_path)},
    ) from e

  current_version = payload.get('dataVersion')
  if current_version is None:
    return None
  if not isinstance(current_version, str) or not current_version.strip():
    raise AppError(
      code='DATA_STATUS_INVALID_VERSION',
      message='Current data status contains an invalid dataVersion value.',
      status_code=500,
      details={'path': str(status_path), 'dataVersion': current_version},
    )

  return current_version.strip()


def _validate_version_change(title_id: str, requested_version: str, allow_downgrade: bool) -> None:
  current_version = _read_current_data_version(title_id)
  if current_version is None:
    return

  requested = _parse_version(requested_version)
  current = _parse_version(current_version)

  if requested < current and not allow_downgrade:
    raise VersionDowngradeError(requested=requested_version, current=current_version)


async def run_pipeline(
  title_id: str, data_version: str, allow_downgrade: bool = False
) -> tuple[int, dict[str, Any]]:
  """Run the update pipeline for a Title ID and DataVersion.

  Returns:
    (http_status_code, http_body)

  Admin status:
  - Always written to WORK_ROOT/<title_id>/status.json
  - Includes the same top-level keys as the HTTP body plus:
      jobChrono, steps, details
  """
  out_dir: Path = WORK_ROOT / title_id
  ensure_dir(out_dir)

  steps: list[dict[str, Any]] = []
  current_step: str | None = None

  # Default HTTP response (used for unexpected errors).
  http_status: int = 500
  http_body: dict[str, Any] = make_http_response(
    ok=False,
    title_id=title_id,
    data_version=data_version,
    current_step=None,
    status='Internal server error. See status.json for details.',
  )

  # Admin status is a superset of the HTTP response.
  admin_status: dict[str, Any] = {
    **http_body,
    'jobChrono': {'startAt': _now(), 'completeAt': None},
    'steps': steps,
    'details': None,
  }

  try:
    # Preflight: verify requested dataVersion change policy
    current_step = 'preflight'
    admin_status['currentStep'] = current_step
    _validate_version_change(
      title_id=title_id, requested_version=data_version, allow_downgrade=allow_downgrade
    )
    _add_step(steps, 'preflight', True)

    # Step 1: PlayFab authentication
    current_step = 'auth'
    admin_status['currentStep'] = current_step
    session_ticket = login_session_ticket(title_id)
    _add_step(steps, 'auth', True)

    # Step 2: fetch, validate, and parse manifest
    current_step = 'manifest'
    admin_status['currentStep'] = current_step
    manifest = get_manifest(title_id, session_ticket, data_version)
    write_manifest_to_disk(title_id, manifest)
    _add_step(steps, 'manifest', True)

    # Step 3: download + gunzip json/txt files (balance, schedule, localization, leaderboard names)
    current_step = 'parse_json'
    admin_status['currentStep'] = current_step
    await download_json_files(title_id, manifest)
    gunzip_json_files(title_id)
    _add_step(steps, 'parse_json', True)

    # Step 4: download AssetBundle manifest and all other AssetBundles
    current_step = 'parse_uab'
    admin_status['currentStep'] = current_step
    await download_uab_manifest(title_id, manifest)
    await download_uab_all(title_id, manifest['VersionSettings']['AssetBundle']['BaseURL'])
    _add_step(steps, 'parse_uab', True)

    # Step 5: extract all AssetBundles
    current_step = 'extract_uab'
    admin_status['currentStep'] = current_step
    extract_uab_all(title_id)
    _add_step(steps, 'extract_uab', True)

    # Step 6: create data directory
    current_step = 'finalize'
    admin_status['currentStep'] = current_step
    arrange_assets(title_id)
    arrange_json(title_id)
    move_staging_to_data(title_id, data_version, _now())
    _add_step(steps, 'finalize', True)

    http_status = 200
    http_body = make_http_response(
      ok=True,
      title_id=title_id,
      data_version=data_version,
      current_step=current_step,
      status='The operation completed successfully.',
    )

    admin_status.update(http_body)

  except AppError as e:
    # Expected/handled errors: return the message to the caller; store full details in status.json
    http_status = e.status_code
    http_body = make_http_response(
      ok=False,
      title_id=title_id,
      data_version=data_version,
      current_step=current_step,
      status=e.message,
    )

    admin_status.update(http_body)
    admin_status['details'] = {
      'code': e.code,
      'details': e.details,
    }

    if current_step:
      _add_step(steps, current_step, False)

  except Exception as e:
    # Unexpected errors: keep the client message generic, record traceback for admin
    http_status = 500
    http_body = make_http_response(
      ok=False,
      title_id=title_id,
      data_version=data_version,
      current_step=current_step,
      status='Internal server error. Please see log file for details.',
    )

    admin_status.update(http_body)
    admin_status['details'] = {
      'code': type(e).__name__,
      'details': {'message': str(e), 'traceback': traceback.format_exc()},
    }

    if current_step:
      _add_step(steps, current_step, False)

  finally:
    admin_status['jobChrono']['completeAt'] = _now()
    (out_dir / 'status.json').write_text(json.dumps(admin_status, indent=2), encoding='utf-8')

  return http_status, http_body

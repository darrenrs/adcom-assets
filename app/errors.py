from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AppError(Exception):
  """
  Base class for expected/handled errors.
  """

  code: str = 'APP_ERROR'
  message: str = 'Unspecified application error.'
  status_code: int = 400
  details: dict[str, Any] | None = None

  def __str__(self) -> str:
    return f'{self.code} {self.status_code} {self.message}'


class PlayFabAuthError(AppError):
  def __init__(
    self,
    message: str = 'Missing PlayFab authentication ID. Set PLAYFAB_AUTH_ID in .env.',
    details: dict[str, Any] | None = None,
  ):
    super().__init__(code='PLAYFAB_AUTH_ERROR', message=message, status_code=401, details=details)


class InvalidVersionError(AppError):
  def __init__(self, version: str, details: dict[str, Any] | None = None):
    super().__init__(
      code='INVALID_VERSION_ERROR',
      message=f'No data found for version {version}',
      status_code=404,
      details={'requested': version},
    )


class VersionDowngradeError(AppError):
  def __init__(self, requested: str, current: str):
    super().__init__(
      code='VERSION_DOWNGRADE_ERROR',
      message=f'Requested version {requested} is older than current {current}.',
      status_code=409,
      details={'requested': requested, 'current': current},
    )


class ManifestSchemaError(AppError):
  def __init__(self, path: str, expected: str, got: Any = None):
    details = {'path': path, 'expected': expected}
    if got is not None:
      details['gotType'] = type(got).__name__
    super().__init__(
      code='MANIFEST_SCHEMA_ERROR',
      message=f'Manifest schema missing/invalid at {path} (expected {expected}).',
      status_code=502,
      details=details,
    )

import hashlib
import json
import os
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .common import make_http_response
from .errors import AppError, InvalidPasswordError, InvalidTitleIdError, JobInProgressError
from .locks import lock_for
from .paths import DATA_ROOT
from .pipeline import run_pipeline

load_dotenv()

app = FastAPI()

VALID_TITLE_IDS = ('6bf5', 'dc4bb')
VALID_TITLE_ID_SET = set(VALID_TITLE_IDS)


class CaseInsensitiveStaticFiles(StaticFiles):
  def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
    full_path, stat_result = super().lookup_path(path)
    if stat_result is not None:
      return full_path, stat_result

    for directory in self.all_directories:
      resolved_path = self._lookup_case_insensitive_path(directory, path)
      if resolved_path is None:
        continue

      if self.follow_symlink:
        full_path = os.path.abspath(resolved_path)
      else:
        full_path = os.path.realpath(resolved_path)

      root_path = os.path.realpath(directory)
      if os.path.commonpath([full_path, root_path]) != root_path:
        continue

      try:
        return full_path, os.stat(full_path)
      except (FileNotFoundError, NotADirectoryError):
        continue

    return '', None

  @staticmethod
  def _lookup_case_insensitive_path(directory: str, path: str) -> str | None:
    current_path = directory
    for part in path.split(os.path.sep):
      if part in ('', '.'):
        continue
      if part == '..':
        return None
      try:
        entries = os.listdir(current_path)
      except (FileNotFoundError, NotADirectoryError, PermissionError):
        return None

      match = next((entry for entry in entries if entry.casefold() == part.casefold()), None)
      if match is None:
        return None
      current_path = os.path.join(current_path, match)

    return current_path


class UpdateBody(BaseModel):
  titleId: str
  dataVersion: str
  password: str
  allowDowngrade: bool = False


def _read_title_status(title_id: str) -> dict[str, Any] | None:
  status_file = DATA_ROOT / title_id / 'status.json'
  if not status_file.exists():
    return None

  try:
    return json.loads(status_file.read_text(encoding='utf-8'))
  except Exception:
    return None


def _error_response(
  err: AppError, *, title_id: str, data_version: str, current_step: str | None
) -> JSONResponse:
  return JSONResponse(
    status_code=err.status_code,
    content=make_http_response(
      ok=False,
      title_id=title_id,
      data_version=data_version,
      current_step=current_step,
      status=err.message,
    ),
  )


@app.get('/')
async def main():
  """
  GET / - Server status page
  """
  titles = {title_id: _read_title_status(title_id) for title_id in VALID_TITLE_IDS}
  return {'ok': True, 'titles': titles}


@app.post('/update')
async def update(req: UpdateBody):
  """
  POST /update - Initiate update request

  :param body: Body must contain titleId, version, and password(FUTURE) parameters
  :type body: UpdateBody
  """
  title_id = req.titleId.strip().lower()
  data_version = req.dataVersion.strip()
  allow_downgrade = req.allowDowngrade
  password = req.password
  password_hash = hashlib.sha1(password.encode()).hexdigest()

  # if one of these parameters is missing, the server will respond with a 422 Unprocessable Entity
  # error. This must be handled by the client.

  try:
    if password_hash != os.environ.get('ADMIN_PASSWORD'):
      raise InvalidPasswordError()

    if title_id not in VALID_TITLE_ID_SET:
      raise InvalidTitleIdError(title_id=title_id, allowed_title_ids=list(VALID_TITLE_IDS))

    lock = lock_for(title_id)
    if lock.locked():
      raise JobInProgressError(title_id=title_id)

    async with lock:
      status_code, body = await run_pipeline(
        title_id=title_id,
        data_version=data_version,
        allow_downgrade=allow_downgrade,
      )
      return JSONResponse(status_code=status_code, content=body)

  except AppError as err:
    current_step = 'lock' if isinstance(err, JobInProgressError) else None
    return _error_response(
      err, title_id=title_id, data_version=data_version, current_step=current_step
    )


app.mount('/assets', CaseInsensitiveStaticFiles(directory=DATA_ROOT, check_dir=False), name='data')

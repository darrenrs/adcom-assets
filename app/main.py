from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .common import make_http_response
from .locks import lock_for
from .pipeline import run_pipeline

load_dotenv()

app = FastAPI()

VALID_TITLE_IDS = {'6bf5', 'dc4bb'}


class UpdateBody(BaseModel):
  titleId: str
  dataVersion: str
  # TODO: Uncomment this when ready to add hash-based password authentication
  # password: str


@app.get('/')
async def main():
  """
  GET / - Server status page
  """
  return {'ok': True, 'titles': VALID_TITLE_IDS}


@app.post('/update')
async def update(req: UpdateBody):
  """
  POST /update - Initiate update request

  :param body: Body must contain titleId, version, and password(FUTURE) parameters
  :type body: UpdateBody
  """
  title_id = req.titleId.strip().lower()
  data_version = req.dataVersion.strip()
  # TODO: Uncomment this when ready to add hash-based password authentication
  # password = req.password.strip()

  # if one of these parameters is missing, the server will respond with a 422 Unprocessable Entity
  # error. This must be handled by the client.

  # if PASSWORD_INCORRECT:
  #   return JSONResponse(
  #     status_code=400,
  #     content=make_response(
  #       ok=False,
  #       title_id=title_id,
  #       data_version=data_version,
  #       current_step=None,
  #       status='Password incorrect.',
  #     ),
  #   )

  if title_id not in VALID_TITLE_IDS:
    return JSONResponse(
      status_code=400,
      content=make_http_response(
        ok=False,
        title_id=title_id,
        data_version=data_version,
        current_step=None,
        status=f'Invalid titleId {title_id}. Must be in {VALID_TITLE_IDS}.',
      ),
    )

  lock = lock_for(title_id)
  if lock.locked():
    return JSONResponse(
      status_code=409,
      content=make_http_response(
        ok=False,
        title_id=title_id,
        data_version=data_version,
        current_step='lock',
        status=f'Job already in progress for titleId {title_id}.',
      ),
    )

  async with lock:
    status_code, body = await run_pipeline(title_id, data_version)
    return JSONResponse(status_code=status_code, content=body)

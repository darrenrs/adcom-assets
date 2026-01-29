from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .locks import lock_for
from .pipeline import run_update

app = FastAPI()

VALID_TITLE_IDS = {'6bf5', 'dc4bb'}


class UpdateBody(BaseModel):
  titleId: str


@app.get('/')
async def main():
  return 'alive'


@app.post('/update')
async def update(body: UpdateBody):
  title_id = body.titleId.strip().lower()

  if title_id not in VALID_TITLE_IDS:
    raise HTTPException(status_code=400, detail=f'Invalid title {title_id}')

  lock = lock_for(title_id)
  if lock.locked():
    raise HTTPException(status_code=409, detail=f'Job already in progress for title {title_id}')

  async with lock:
    result = run_update(title_id)
    return {'status': True, **result}

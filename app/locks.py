import asyncio

_lock_by_title: dict[str, asyncio.Lock] = {}


def lock_for(title_id: str) -> asyncio.Lock:
  """
  Lock Title ID if in progress

  :param title_id: Title ID
  :type title_id: str
  :return: Asyncio Lock
  :rtype: Lock
  """
  if title_id not in _lock_by_title:
    _lock_by_title[title_id] = asyncio.Lock()

  return _lock_by_title[title_id]

import os
from typing import Any

import requests

from app.errors import PlayFabAuthError

from ..common import load_payload


def _get_playfab_auth_id() -> str:
  """
  Get PlayFab Authentication ID from .env

  :return: Value of PLAYFAB_AUTH_ID
  :rtype: str
  """
  playfab_auth_id = os.environ.get('PLAYFAB_AUTH_ID')

  if not playfab_auth_id:
    raise PlayFabAuthError()

  return playfab_auth_id.strip()


def _get_playfab_auth_method() -> str:
  """
  Get PlayFab Authentication Method from .env

  :return: Value of PLAYFAB_AUTH_METHOD
  :rtype: str
  """
  playfab_auth_method = os.environ.get('PLAYFAB_AUTH_METHOD')

  if not playfab_auth_method:
    raise RuntimeError(
      'Missing PlayFab authentication method name. Set PLAYFAB_AUTH_METHOD in .env.'
    )

  return playfab_auth_method.strip()


def _apply_playfab_auth_id(payload: dict[str, Any], playfab_auth_id: str) -> dict[str, Any]:
  """
  Update payload with PlayFab authentication ID

  :param payload: JSON representation of payload
  :type payload: dict[str, Any]
  :param playfab_auth_id: PlayFab authentication ID
  :type playfab_auth_id: str
  :return: Updated payload
  :rtype: dict[str, Any]
  """
  # key name varies depending on login method
  if 'PlayerId' in payload:
    payload['PlayerId'] = playfab_auth_id
    return payload

  raise KeyError('Login payload template must contain PlayFab ID.')


def login_session_ticket(title_id: str) -> str:
  """
  Log in to PlayFab and get a session ticket

  :param title_id: Title ID
  :type title_id: str
  :return: PlayFab Session Ticket
  :rtype: str
  """
  playfab_auth_id = _get_playfab_auth_id()
  playfab_auth_method = _get_playfab_auth_method()

  body = load_payload(playfab_auth_method + '.json')
  body = _apply_playfab_auth_id(body, playfab_auth_id)
  body['TitleId'] = title_id.upper()

  url = f'https://{title_id}.playfabapi.com/Client/{playfab_auth_method}'
  r = requests.post(url, json=body, timeout=30)
  r.raise_for_status()
  payload = r.json()

  # Return session ticket on successful login
  try:
    return payload['data']['SessionTicket']
  except Exception as e:
    raise PlayFabAuthError(str(e)) from e

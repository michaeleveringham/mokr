import json
import logging
from abc import ABC
from typing import Awaitable

from mokr.constants import TARGET_DETACHED, TARGET_RECV_MSG


LOGGER = logging.getLogger(__name__)


class RemoteConnection(ABC):
    @staticmethod
    def _rewrite_exception(error: Exception, message: str) -> Exception:
        error.args = (message, )
        return error

    def _create_protocol_exception(
        self,
        error: Exception,
        method: str,
        obj: dict
    ) -> Exception:
        message = f'Protocol error ({method}): {obj["error"]["message"]}'
        if 'data' in obj['error']:
            message += f' {obj["error"]["data"]}'
        return self._rewrite_exception(error, message)

    def _prepare_message(self, method: str, params: dict = None) -> Awaitable:
        if params is None:
            params = {}
        self._last_id += 1
        msg = json.dumps(
            dict(
                id=self._last_id,
                method=method,
                params=params,
            )
        )
        LOGGER.debug(f'Prepared remote connection message: {msg}')
        return msg

    def _handle_detached_or_received(self, msg: dict) -> tuple[bool, dict, str]:
        # Handle message if received or detached.
        # Returns a tuple of values: result, method, and params.
        # The result is only True when an unhandled method is given.
        method = msg.get('method', '')
        params = msg.get('params', {})
        session_id = params.get('sessionId')
        session = self._sessions.get(session_id)
        if method == TARGET_RECV_MSG and session:
            session._on_message(params.get('message'))
            return True, method, params
        elif method == TARGET_DETACHED and session:
            session._on_closed()
            self._sessions.pop(session_id)
            return True, method, params
        elif method not in (TARGET_DETACHED, TARGET_RECV_MSG):
            return False, method, params
        else:
            return True, method, params

    def _on_message(self, message: str) -> None:
        LOGGER.debug(f'Loading remote connection message: {message}')
        msg = json.loads(message)
        _id = msg.get('id')
        if _id in self._callbacks:
            callback = self._callbacks.pop(_id)
            if msg.get('error'):
                callback.set_exception(
                    self._create_protocol_exception(
                        callback.error,
                        callback.method,
                        msg,
                    )
                )
            else:
                self._on_successful_response(callback, msg)
        else:
            self._on_query(msg)

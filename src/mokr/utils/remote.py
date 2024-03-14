import logging
import math
from typing import Any, Awaitable, Callable

from pyee import EventEmitter

from mokr.connection import DevtoolsConnection
from mokr.constants import RUNTIME_RELEASE_OBJECT
from mokr.exceptions import ElementHandleError


LOGGER = logging.getLogger(__name__)


def format_javascript_exception(exception_details: dict) -> str:
    """
    Get and format a JavaScript exception message.

    Args:
        exception_details (dict): An "exceptionDetails" object loaded as
            a dictionary.

    Returns:
        str: Formatted exception as string.
    """
    exception = exception_details.get('exception')
    if exception:
        return exception.get('description') or exception.get('value')
    message = exception_details.get('text', '')
    stackTrace = exception_details.get('stackTrace', dict())
    if stackTrace:
        for callframe in stackTrace.get('callFrames'):
            location = (
                f"{callframe.get('url', '')}:"
                f"{callframe.get('lineNumber', '')}:"
                f"{callframe.get('columnNumber')}"
            )
            functionName = callframe.get('functionName', '<anonymous>')
            message = message + f'\n    at {functionName} ({location})'
    return message


def add_event_listener(
    emitter: EventEmitter,
    event_name: str,
    handler: Callable,
) -> dict[str, Any]:
    """
    Add an event `handler` to an `emitter` for a given `event_name`.

    Args:
        emitter (EventEmitter): Emitter to listen on.
        event_name (str): Event name to listen for.
        handler (Callable): Handler callback to run when event is emitted.

    Returns:
        dict[str, Any]: A dictionary representation of the listener.
    """
    emitter.on(event_name, handler)
    return {'emitter': emitter, 'eventName': event_name, 'handler': handler}


def remove_event_listeners(listeners: list[dict]) -> None:
    """
    Remove all event listeners given from their emitters.

    Args:
        listeners (list[dict]): A list of listeners in dictionary form, as
            returned by `mokr.utils.remote.add_event_listener`.
    """
    for listener in listeners:
        emitter = listener['emitter']
        event_name = listener['eventName']
        handler = listener['handler']
        if event_name in emitter._events.keys():
            try:
                emitter.remove_listener(event_name, handler)
            except KeyError:
                # Ignore keyerrors, event isn't registered.
                pass
    listeners.clear()


def serialize_remote_object(remote_object: dict) -> Any:
    """
    Transform a remote JavaScript object's "value" to a Python equivalent.

    Args:
        remote_object (dict): The remote JavaScript object to serialise.

    Raises:
        ElementHandleError: Raised if the `remote_object` has an "objectId"
        (is not a primitive object) or if an unhandled case is encountered
        when checking `remote_object["unserializableValue"]`.

    Returns:
        Any: Python representation of remote object. May be str, int, dict,
            list, etc. Some `remote_object["unserializableValue"]`s will be
            transformed into equivalents including "Nan" to None, "-0" to 0,
            "Infinity" to `math.inf`, and "-Infinity" to `-math.inf`.
    """
    if remote_object.get('objectId'):
        raise ElementHandleError('Cannot extract value when objectId is given.')
    value = remote_object.get('unserializableValue')
    if value:
        if value == '-0':
            return -0
        elif value == 'NaN':
            return None
        elif value == 'Infinity':
            return math.inf
        elif value == '-Infinity':
            return -math.inf
        else:
            raise ElementHandleError(f'Unserializable value: {value}')
    return remote_object.get('value')


def release_remote_object(
    client: DevtoolsConnection,
    remote_object: dict
) -> Awaitable:
    """
    Release a given `remote_object` so that it is no longer referenced
    by the browser and can be garbage collected.

    Ignores all exceptions raised when sending request to devtools session.

    Args:
        client (DevtoolsConnection): A `mokr.connection.DevtoolsConnection`.
        remote_object (dict): A remote object as dictionary.

    Returns:
        Awaitable: Awaitable that yields None.
    """
    object_id = remote_object.get('objectId')
    fut_none = client._loop.create_future()
    fut_none.set_result(None)
    if not object_id:
        return fut_none
    try:
        return client.send(
            RUNTIME_RELEASE_OBJECT,
            {'objectId': object_id}
        )
    except Exception:
        # Harmless exceptions may happen if page navigated or closed.
        LOGGER.debug(
            "Ignoring exception releasing remote object.",
            exc_info=True,
        )
    return fut_none


def is_javascript_method(method: str) -> bool:
    """
    Casually check if string is a JavaScript method.

    Args:
        method (str): String to check.

    Returns:
        bool: True if deemed to be a method, else False.
    """
    method = method.strip()
    if (
        method.startswith('function')
        or method.startswith('async ')
        or '=>' in method
    ):
        return True
    return False

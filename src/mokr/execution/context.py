from __future__ import annotations

import logging
import math
import re
from typing import TYPE_CHECKING, Any

from mokr.connection import DevtoolsConnection
from mokr.constants import (
    RUNTIME_CALL_FUNCTION,
    RUNTIME_EVALUATE,
    RUNTIME_QUERY_OBJECTS,
)
from mokr.exceptions import ElementHandleError, NetworkError
from mokr.execution.handle.javascript import JavascriptHandle
from mokr.utils.remote import format_javascript_exception, is_javascript_method

if TYPE_CHECKING:
    from mokr.frame import Frame


LOGGER = logging.getLogger(__name__)

EVALUATION_SCRIPT_URL = '__mokr_evaluation_script__'

SOURCE_URL_REGEX = re.compile(
    r'^[\040\t]*//[@#] sourceURL=\s*(\S*?)\s*$',
    re.MULTILINE,
)


class ExecutionContext():
    def __init__(
        self,
        client: DevtoolsConnection,
        context_payload: dict,
        object_handle_factory: Any,
        frame: Frame = None,
    ) -> None:
        """
        Class to handle execution of JavaScript functions, element manipulation,
        and associated runtime error translation.

        Args:
            client (DevtoolsConnection): Remote connection from parent.
            context_payload (dict): Context from triggering event.
            object_handle_factory (Any): Factory for handling remote objects.
                Should create `mokr.execution.JavascriptHandle` based objects.
            frame (Frame, optional): The `mokr.frame.Frame` that spawned this.
                Defaults to None.
        """
        self._client = client
        self._frame = frame
        self._context_id = context_payload.get('id')
        aux_data = context_payload.get('auxData', {'isDefault': False})
        self._is_default = bool(aux_data.get('isDefault'))
        self._object_handle_factory = object_handle_factory

    @property
    def frame(self) -> Frame | None:
        """Parent `mokr.frame.Frame` that spawned this."""
        return self._frame

    @staticmethod
    def _rewrite_exception(exception: Exception) -> None:
        if exception.args[0].endswith('Cannot find context with specified id'):
            msg = 'Execution context destroyed, likely due to a navigation.'
            raise type(exception)(msg)
        raise exception

    def _convert_argument(self, arg: Any) -> dict:
        if arg == math.inf:
            return {'unserializableValue': 'Infinity'}
        if arg == -math.inf:
            return {'unserializableValue': '-Infinity'}
        object_handle = arg if isinstance(arg, JavascriptHandle) else None
        if object_handle:
            if object_handle._context != self:
                raise ElementHandleError(
                    'JavascriptHandle can only be evaluated'
                    ' in the context it was created in.'
                )
            if object_handle._disposed:
                raise ElementHandleError('JavascriptHandle is disposed!')
            if object_handle._remote_object.get('unserializableValue'):
                return {
                    'unserializableValue': object_handle._remote_object.get(
                        'unserializableValue'
                    )
                }
            if not object_handle._remote_object.get('objectId'):
                return {'value': object_handle._remote_object.get('value')}
            return {'objectId': object_handle._remote_object.get('objectId')}
        return {'value': arg}

    async def evaluate(
        self,
        page_function: str,
        *args: Any,
        force_expr: bool = False,
    ) -> Any:
        """
        Run `ExecutionContext.evaluate_handle` and try to run
        `mokr.execution.JavascriptHandle.json` on the result to return the
        object as a dictionary.

        Args:
            page_function (str): JavaScript function to run.
            force_expr (bool): If True, treat `page_function` as an expression.
                Otherwise, automatically determine if it is a function or
                an expression. Defaults to False.

        Raises:
            `mokr.exceptions.NetworkError` if an unhandled error occurs
            either evaluating the function or requesting the resulting object.

        Returns:
            dict | None: The decoded object (dict) via
                `mokr.execution.JavascriptHandle.json` or None if a known
                error occurs decoding it.
        """
        handle = await self.evaluate_handle(
            page_function,
            *args,
            force_expr=force_expr,
        )
        try:
            result = await handle.json()
        except NetworkError as e:
            if any(
                error_part in e.args[0] for error_part in [
                    'Object reference chain is too long',
                    'Object couldn\'t be returned by value',
                ]
            ):
                return None
            raise
        await handle.dispose()
        return result

    async def evaluate_handle(
        self,
        page_function: str,
        *args: Any,
        force_expr: bool = False,
        eval_script_url_suffix: str | None = None,
    ) -> JavascriptHandle:
        """
        Execute a JavaScript function with given arguments.

        Args:
            page_function (str): JavaScript function to run.

        Raises:
            ElementHandleError: Raised if execution fails.

        Returns:
            JavascriptHandle: `mokr.execution.JavascriptHandle`.
        """
        suffix = f'//# sourceURL={EVALUATION_SCRIPT_URL}'
        if eval_script_url_suffix:
            suffix += eval_script_url_suffix
        try:
            if force_expr or (
                not args and not is_javascript_method(page_function)
            ):
                if SOURCE_URL_REGEX.match(page_function):
                    expression_with_source_url = page_function
                else:
                    expression_with_source_url = f'{page_function}\n{suffix}'
                _obj = await self._client.send(
                    RUNTIME_EVALUATE,
                    {
                        'expression': expression_with_source_url,
                        'context_id': self._context_id,
                        'returnByValue': False,
                        'awaitPromise': True,
                        'userGesture': True,
                    },
                )
            else:
                _obj = await self._client.send(
                    RUNTIME_CALL_FUNCTION,
                    {
                        'functionDeclaration': f'{page_function}\n{suffix}\n',
                        'executionContextId': self._context_id,
                        'arguments': [
                            self._convert_argument(arg) for arg in args
                        ],
                        'returnByValue': False,
                        'awaitPromise': True,
                        'userGesture': True,
                    },
                )
        except Exception as e:
            self._rewrite_exception(e)
        exception_details = _obj.get('exceptionDetails')
        if exception_details:
            js_exception = format_javascript_exception(exception_details)
            raise ElementHandleError(f'Evaluation failed: {js_exception}')
        remote_object = _obj.get('result')
        return self._object_handle_factory(remote_object)

    async def query_objects(
        self,
        javascript_handle: JavascriptHandle,
    ) -> JavascriptHandle:
        """
        Query all objects with the given `mokr.execution.JavascriptHandle`'s
        `get_property("objectId")`.

        Args:
            javascript_handle (JavascriptHandle): A valid (not disposed)
                `mokr.execution.JavascriptHandle` object.

        Raises:
            ElementHandleError: Raised if the given handle is disposed, or
                does not have an "objectId" remote property (primitive type).

        Returns:
            JavascriptHandle: A `mokr.execution.JavascriptHandle` initialised
                from the remot response.
        """
        if javascript_handle._disposed:
            raise ElementHandleError('Prototype JavascriptHandle is disposed.')
        if not javascript_handle._remote_object.get('objectId'):
            raise ElementHandleError(
                'Prototype JavascriptHandle cannot reference primitive value.'
            )
        response = await self._client.send(
            RUNTIME_QUERY_OBJECTS,
            {'prototypeObjectId': javascript_handle._remote_object['objectId']}
        )
        return self._object_handle_factory(response.get('objects'))

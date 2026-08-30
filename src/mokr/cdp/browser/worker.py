import logging
from typing import Any, Callable

from pyee import EventEmitter

from mokr.cdp.connection import CdpSession
from mokr.constants import (
    RUNTIME_CONSOLE_API_CALL,
    RUNTIME_ENABLE,
    RUNTIME_EXCEPTION_THROWN,
    RUNTIME_EXECUTION_CONTEXT_CREATED,
)
from mokr.cdp.execution.context import CdpExecutionContext, CdpJavascriptHandle

LOGGER = logging.getLogger(__name__)


class CdpWebWorker(EventEmitter):
    def __init__(
        self,
        client: CdpSession,
        url: str,
        console_api_callback: Callable,
        exception_thrown: Callable,
    ) -> None:
        """
        Represents a web worker on the page. This object is created and
        destroyed by it's parent `mokr.browser.Page`.

        Args:
            client (CdpSession): A `mokr.cdp.connection.CdpSession`
                spawned by the parent `mokr.browser.Page`.
            url (str): The "url" present in the triggering event's "targetInfo".
            console_api_callback (Callable): Callback to run when the console
                is called, if no listener's are present for this on the
                `mokr.browser.Page`, will delete the handle due to given
                default callback from parent `Page`.
            exception_thrown (Callable): Callback to run if exception occurs.
        """
        super().__init__()
        self._client = client
        self._url = url
        self.console_api_callback = console_api_callback
        self._execution_context = None
        self._loop = client._loop
        self._execution_context_promise = self._loop.create_future()
        self._client.on(
            RUNTIME_EXECUTION_CONTEXT_CREATED,
            self._on_execution_context_created,
        )
        try:
            # May fail if target closed before all execution contexts received.
            self._client.send(RUNTIME_ENABLE, {})
        except Exception:
            LOGGER.error("Error enabling runtime on webworker.", exc_info=True)
        self._client.on(RUNTIME_CONSOLE_API_CALL, self._on_console_api_called)
        self._client.on(
            RUNTIME_EXCEPTION_THROWN,
            lambda exception: exception_thrown(exception["exceptionDetails"]),
        )

    @property
    def url(self) -> str:
        """URL associated with the event that triggered this worker."""
        return self._url

    def _context_js_handle_factory(
        self,
        remote_object: dict,
    ) -> CdpJavascriptHandle | None:
        if self._execution_context:
            return CdpJavascriptHandle(
                self._execution_context,
                self._client,
                remote_object,
            )
        else:
            return None

    def _execution_context_callback(self, value: CdpExecutionContext) -> None:
        self._execution_context_promise.set_result(value)

    def _on_execution_context_created(self, event: dict) -> None:
        self._execution_context = CdpExecutionContext(
            self._client,
            event["context"],
            self._context_js_handle_factory,
        )
        self._execution_context_callback(self._execution_context)

    def _on_console_api_called(self, event: dict) -> None:
        args = []
        for arg in event.get("args", []):
            args.append(self._context_js_handle_factory(arg))
        self.console_api_callback(event["type"], args)

    async def execution_context(self) -> CdpExecutionContext:
        """
        Return the newly created `mokr.cdp.execution.CdpExecutionContext`.

        Returns:
            CdpExecutionContext: `mokr.cdp.execution.CdpExecutionContext`.
        """
        return await self._execution_context_promise

    async def evaluate(self, page_function: str, *args: Any) -> dict | None:
        """
        Execute a JavaScript function with given arguments.
        Run this `CdpWebWorker`'s `mokr.cdp.execution.CdpExecutionContext.evaluate`.

        Args:
            page_function (str): JavaScript function to run.

        Raises:
            `mokr.exceptions.NetworkError` if an unhandled error occurs
            either evaluating the function or requesting the resulting object.

        Returns:
            dict | None: The decoded object (dict) via
                `mokr.cdp.execution.CdpJavascriptHandle.json` or None if a known
                error occurs decoding it.
        """
        return await (await self._execution_context_promise).evaluate(
            page_function,
            *args,
        )

    async def evaluate_handle(
        self,
        page_function: str,
        *args: Any,
    ) -> CdpJavascriptHandle:
        """
        Execute a JavaScript function with given arguments.
        Run this `CdpWebWorker`'s
        `mokr.cdp.execution.CdpExecutionContext.evaluate_handle`.

        Args:
            page_function (str): JavaScript function to run.

        Returns:
            CdpJavascriptHandle: `mokr.cdp.execution.CdpJavascriptHandle`.
        """
        return await (await self._execution_context_promise).evaluate_handle(
            page_function,
            *args,
        )

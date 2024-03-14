from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Generator, Literal

from mokr.constants import METHOD_WAIT_FOR_PREDICATE_PAGE
from mokr.exceptions import MokrTimeoutError, NetworkError, PageError
from mokr.utils.remote import is_javascript_method

if TYPE_CHECKING:
    from mokr.frame.frame import Frame


LOGGER = logging.getLogger(__name__)


class WaitTask():
    def __init__(
        self,
        frame: Frame,
        predicate_body: str,
        title: str,
        polling: Literal['raf', 'mutation'] | int | float,
        timeout: float,
        loop: asyncio.AbstractEventLoop,
        *args: Any,
    ) -> None:
        """
        Class used to monitor a remote frame for events to occur within
        a given timer interval.

        Args:
            frame (Frame): `mokr.frame.Frame` that spawned this `WaitTask`.
            predicate_body (str): JavaScript function to return from.
            title (str): Title to be used to contextualise error, if any.
            polling (Literal["raf", "mutation"] | int | float): Polling type;
                if set to "raf", executes continously in
                "requestAnimationFrame", else if set to "mutation" executes
                only on DOM mutations.
                Defaults to "raf".
            timeout (float): Time in milliseconds to wait.
            loop (asyncio.AbstractEventLoop): Running asyncio loop.

        Raises:
            ValueError: Raised if `polling_type` not "raf" or "mutation".
        """
        polling_value_error = False
        if isinstance(polling, str):
            if polling not in ['raf', 'mutation']:
                polling_value_error = True
        elif isinstance(polling, (int, float)):
            if polling <= 0:
                polling_value_error = True
        else:
            polling_value_error = True
        if polling_value_error:
            raise ValueError(
                "Unsupported polling value, must provide one of"
                '"raf", "mutation", or a positive int.'
                f" Provided: {polling}"
            )
        self._frame = frame
        self._polling = polling
        self._timeout = timeout
        self._loop = loop
        self._args = args
        self._run_count = 0
        self._terminated = False
        self._timeout_error = False
        if args or is_javascript_method(predicate_body):
            self._predicate_body = f'return ({predicate_body})(...args)'
        else:
            self._predicate_body = f'return {predicate_body}'
        frame._wait_tasks.add(self)
        self.promise = self._loop.create_future()
        if timeout:
            self._timeout_timer = self._loop.create_task(
                self._timer(title, self._timeout),
            )
        self._running_task = self._loop.create_task(self.rerun())

    def __await__(self) -> Generator:
        result = yield from self.promise
        if isinstance(result, Exception):
            raise result
        return result

    def _cleanup(self) -> None:
        if self._timeout and not self._timeout_error:
            self._timeout_timer.cancel()
        self._frame._wait_tasks.remove(self)

    async def _timer(self, title: str, timeout: int | float) -> None:
        await asyncio.sleep(timeout / 1000)
        self._timeout_error = True
        self.terminate(
            MokrTimeoutError(
                f'Waiting for {title} failed: timeout {timeout}ms exceeds.'
            )
        )

    def terminate(self, error: Exception) -> None:
        """
        Finish the task, if the promise is still not done, set the result
        with the given `error`, then remove this task from the parent
        `mokr.frame.Frame`.

        Args:
            error (Exception): Error to raise if watched promise isn't done.
        """
        self._terminated = True
        if not self.promise.done():
            self.promise.set_result(error)
        self._cleanup()

    async def rerun(self) -> None:
        """
        Start polling for the expected condition.

        Raises:
            PageError: Raised if no `mokr.execution.ExecutionContext` attached
                to the parent `mokr.frame.Frame`.
        """
        run_count = self._run_count = self._run_count + 1
        success = None
        error = None
        try:
            context = await self._frame.execution_context()
            if context is None:
                raise PageError('No execution context attached to frame.')
            success = await context.evaluate_handle(
                METHOD_WAIT_FOR_PREDICATE_PAGE,
                self._predicate_body,
                self._polling,
                self._timeout,
                *self._args,
            )
        except Exception as e:
            error = e
        if self.promise.done():
            return
        if self._terminated or run_count != self._run_count:
            if success:
                await success.dispose()
            return
        # Add try/except referring to puppeteer.
        try:
            if not error and success and (
                await self._frame.evaluate('s => !s', success)
            ):
                await success.dispose()
                return
        except NetworkError:
            if success is not None:
                await success.dispose()
            return
        # Page is navigated and context is destroyed.
        # Try again in the new execution context.
        if isinstance(error, NetworkError) and any(
            error_part in error.args[0] for error_part in [
                'Execution context was destroyed',
                'Cannot find context with specified id',
            ]
        ):
            return
        if error:
            self.promise.set_exception(error)
        else:
            self.promise.set_result(success)
        self._cleanup()

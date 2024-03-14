import asyncio
import inspect
from typing import Any, Awaitable, Callable

from pyee import EventEmitter

from mokr.exceptions import MokrTimeoutError
from mokr.utils.remote import add_event_listener, remove_event_listeners


class EventWaiter():
    def __init__(
        self,
        emitter: EventEmitter,
        event_name: str,
        predicate: Callable,
        timeout: float,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """
        Class to wait for an event to be emitted and then run a callback
        `predicate` when it is. If the callback resolves to a truthy value,
        the timer is cancelled. Otherwise, a `mokr.exceptions.MokrTimeoutError`
        is raised.

        Args:
            emitter (EventEmitter): Emitter to listen to.
            event_name (str): Event name to listen for.
            predicate (Callable): Callback to run when event is emitted.
            timeout (float): Time in milliseconds to wait for event.
            loop (asyncio.AbstractEventLoop): Running asyncio loop.
        """
        self._emitter = emitter
        self._event_name = event_name
        self._predicate = predicate
        self._timeout = timeout
        self._loop = loop
        self._event_timeout = None
        self.listener = None
        self.promise = loop.create_future()

    def _resolve_callback(self, target: Any) -> None:
        if not self.promise.done():
            self.promise.set_result(target)

    def _reject_callback(self, exception: Exception) -> None:
        self.promise.set_exception(exception)

    def _cleanup(self) -> None:
        remove_event_listeners([self.listener])
        if self._event_timeout:
            self._event_timeout.cancel()

    def _listener(self, target: Any) -> None:
        if not self._predicate(target):
            return
        self._cleanup()
        self._resolve_callback(target)

    async def _alistener(self, target: Any) -> None:
        if not await self._predicate(target):
            return
        self._cleanup()
        self._resolve_callback(target)

    async def _timeout_timer(self) -> None:
        await asyncio.sleep(self._timeout / 1000)
        self._reject_callback(
            MokrTimeoutError('Timeout exceeded while waiting for event.')
        )

    def wait(self) -> Awaitable:
        """
        Wait for the target event to be emitted and then run the target
        predicate when it is. If that resolves to a truthy value, cancel the
        timer, otherwise, raise a `mokr.exceptions.MokrTimeoutError` exception.

        Returns:
            Awaitable: Awaitable that yields result of the target callback.
        """
        self.listener = add_event_listener(
            self._emitter,
            self._event_name,
            (
                lambda target: self._loop.create_task(self._alistener(target))
                if inspect.iscoroutinefunction(self._predicate)
                else self._listener
            ),
        )
        if self._timeout:
            self._event_timeout = self._loop.create_task(self._timeout_timer())
        return self.promise

import asyncio
import concurrent.futures
from typing import Any, Awaitable

from mokr.constants import (
    FRAME_DETACHED,
    FRAME_NAVIGATED_IN_DOC,
    LIFECYCLE_EVENT,
    LIFECYCLE_EVENTS,
)
from mokr.exceptions import MokrTimeoutError
from mokr.frame import Frame, FrameManager
from mokr.utils.remote import add_event_listener, remove_event_listeners


class NavigationWaiter:
    def __init__(
        self,
        frame_manager: FrameManager,
        frame: Frame,
        timeout: int,
        wait_until: list[LIFECYCLE_EVENTS] | LIFECYCLE_EVENTS,
    ) -> None:
        """
        Class to listen to a `mokr.frame.FrameManager` for specific navigation
        event(s) (`LIFECYCLE_EVENTS`) in the target `mokr.frame.Frame` for up
        to a given `timeout`. If all events not seen before timeout, raises
        a `MokrTimeoutError` exception.

        Args:
            frame_manager (FrameManager): The `mokr.frame.FrameManager` to watch
                for lifecycle events.
            frame (Frame): The `mokr.frame.Frame` that seen events count toward.
            timeout (int): Tiem in milliseconds to wait for event.
            wait_until (list[LIFECYCLE_EVENTS] | LIFECYCLE_EVENTS): Either a
                list of events or a single event to wait for.
        """
        if isinstance(wait_until, str):
            wait_until = [wait_until]
        self._validate_wait_until(wait_until)
        self._frame_manager = frame_manager
        self._frame = frame
        self._initial_loader_id = frame._loader_id
        self._timeout = timeout
        self._timeout_timer: asyncio.Task | asyncio.Future | None = None
        self._has_same_document_navigation = False
        self._event_listeners = [
            add_event_listener(
                self._frame_manager,
                LIFECYCLE_EVENT,
                self._check_lifecycle_complete,
            ),
            add_event_listener(
                self._frame_manager,
                FRAME_NAVIGATED_IN_DOC,
                self._navigated_within_document,
            ),
            add_event_listener(
                self._frame_manager,
                FRAME_DETACHED,
                self._check_lifecycle_complete,
            ),
        ]
        self._loop = self._frame_manager._client._loop
        self._lifecycle_complete_promise = self._loop.create_future()
        self._navigation_promise = self._loop.create_task(
            asyncio.wait(
                [
                    self._lifecycle_complete_promise,
                    self._create_timeout_promise(),
                ],
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
        )
        self._navigation_promise.add_done_callback(lambda _: self._cleanup())

    def _validate_wait_until(self, wait_until: list[LIFECYCLE_EVENTS]) -> None:
        arg_name_to_lifecycle_event = {
            'load': 'load',
            'domcontentloaded': 'DOMContentLoaded',
            'documentloaded': 'DOMContentLoaded',
            'networkidle': 'networkIdle',
            'networkalmostidle': 'networkAlmostIdle',
        }
        self._expected_lifecycle = []
        for name in wait_until:
            protocol_event = arg_name_to_lifecycle_event.get(name)
            if not protocol_event:
                raise ValueError(
                    f'Unknown value(s) given for wait_until: {name}'
                )
            self._expected_lifecycle.append(protocol_event)

    async def _timeout_func(self) -> None:
        error_message = f'Navigation timeout of {self._timeout}ms exceeded.'
        await asyncio.sleep(self._timeout / 1000)
        self._maximum_timer.set_exception(MokrTimeoutError(error_message))

    def _create_timeout_promise(self) -> Awaitable[None]:
        self._maximum_timer = self._loop.create_future()
        if self._timeout:
            self._timeout_timer = self._loop.create_task(self._timeout_func())
        else:
            self._timeout_timer = self._loop.create_future()
        return self._maximum_timer

    def _navigated_within_document(self, frame: Frame = None) -> None:
        if frame != self._frame:
            return
        self._has_same_document_navigation = True
        self._check_lifecycle_complete()

    def _check_lifecycle_complete(self, *args) -> None:
        if (
            self._frame._loader_id == self._initial_loader_id
            and not self._has_same_document_navigation
        ):
            return
        elif not self._check_lifecycle(self._frame, self._expected_lifecycle):
            return
        elif not self._lifecycle_complete_promise.done():
            self._lifecycle_complete_promise.set_result(None)

    def _check_lifecycle(
        self,
        frame: Frame,
        expected_lifecycle: list[str],
    ) -> bool:
        if any(
            event not in frame._lifecycle_events for event in expected_lifecycle
        ):
            return False
        for child in frame.child_frames:
            if not self._check_lifecycle(child, expected_lifecycle):
                return False
        return True

    def _cleanup(self) -> None:
        remove_event_listeners(self._event_listeners)
        self._lifecycle_complete_promise.cancel()
        self._maximum_timer.cancel()
        self._timeout_timer.cancel()

    def navigation_promise(self) -> Any:
        """
        Return the promise so errors can be handled externally.

        Returns:
            Any: Navigation promise.
        """
        return self._navigation_promise

    def cancel(self) -> None:
        """Stop this waiter, raise no errors."""
        self._cleanup()

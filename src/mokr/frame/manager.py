from __future__ import annotations

import logging
from collections import OrderedDict
from typing import TYPE_CHECKING

from pyee import EventEmitter

from mokr.connection import DevtoolsConnection
from mokr.constants import (
    FRAME_ATTACHED,
    FRAME_DETACHED,
    FRAME_NAVIGATED,
    FRAME_NAVIGATED_IN_DOC,
    LIFECYCLE_EVENT,
    PAGE_FRAME_ATTACHED,
    PAGE_FRAME_DETACHED,
    PAGE_FRAME_NAVIGATED,
    PAGE_FRAME_NAVIGATED_IN_DOC,
    PAGE_FRAME_STOPPED_LOADING,
    PAGE_LIFECYCLE_EVENT,
    RUNTIME_EXECUTION_CONTEXT_CREATED,
    RUNTIME_EXECUTION_CONTEXT_DESTROYED,
    RUNTIME_EXECUTION_CONTEXTS_CLEARED,

)
from mokr.exceptions import ElementHandleError, PageError
from mokr.execution.context import ExecutionContext, JavascriptHandle
from mokr.execution.handle.element import ElementHandle
from mokr.frame.frame import Frame

if TYPE_CHECKING:
    from mokr.browser.page import Page


LOGGER = logging.getLogger(__name__)


class FrameManager(EventEmitter):
    def __init__(
        self,
        client: DevtoolsConnection,
        frame_tree: dict,
        page: Page,
    ) -> None:
        """
        This class is an assistant class that helps with `mokr.frame.Frame`
        management by creating them and by managing
        `mokr.execution.ExecutionContext`s.

        Args:
            client (DevtoolsConnection): `mokr.execution.ExecutionContext` of
                the `mokr.browser.Page` that spawned this.
            frame_tree (dict): A representation of the hierarchy of remote
                frames on a page.
            page (Page): The spawning `mokr.browser.Page` object.
        """
        super().__init__()
        self._client = client
        self._page = page
        self._frames: OrderedDict[str, Frame] = OrderedDict()
        self._main_frame: Frame | None = None
        self._context_id_to_context: dict[str, ExecutionContext] = dict()
        events_to_methods = {
            PAGE_FRAME_ATTACHED: lambda event: self._on_frame_attached(
                event.get('frameId', ''),
                event.get('parentFrameId', ''),
            ),
            PAGE_FRAME_NAVIGATED: lambda event: self._on_frame_navigated(
                event.get('frame'),
            ),
            PAGE_FRAME_NAVIGATED_IN_DOC: (
                lambda event: self._on_frame_navigated_within_document(
                    event.get('frameId'),
                    event.get('url'),
                )
            ),
            PAGE_FRAME_DETACHED: lambda event: self._on_frame_detached(
                event.get('frameId'),
            ),
            PAGE_FRAME_STOPPED_LOADING: (
                lambda event: self._on_frame_stopped_loading(
                    event.get('frameId'),
                )
            ),
            RUNTIME_EXECUTION_CONTEXT_CREATED: (
                lambda event: self._on_execution_context_created(
                    event.get('context'),
                )
            ),
            RUNTIME_EXECUTION_CONTEXT_DESTROYED: (
                lambda event: self._on_execution_context_destroyed(
                    event.get('executionContextId'),
                )
            ),
            RUNTIME_EXECUTION_CONTEXTS_CLEARED: (
                lambda _: self._on_execution_contexts_cleared()
            ),
            PAGE_LIFECYCLE_EVENT: lambda event: self._on_lifecycle_event(event),
        }
        for event, method in events_to_methods.items():
            client.on(event, method)
        self._handle_frame_tree(frame_tree)

    @property
    def main_frame(self) -> Frame | None:
        """The main remote frame (top of the frame tree)."""
        return self._main_frame

    def _on_lifecycle_event(self, event: dict) -> None:
        frame = self._frames.get(event['frameId'])
        if not frame:
            return
        frame._on_lifecycle_event(event['loaderId'], event['name'])
        self.emit(LIFECYCLE_EVENT, frame)

    def _on_frame_stopped_loading(self, frame_id: str) -> None:
        frame = self._frames.get(frame_id)
        if not frame:
            return
        frame._on_loading_stopped()
        self.emit(LIFECYCLE_EVENT, frame)

    def _handle_frame_tree(self, frame_tree: dict) -> None:
        frame = frame_tree['frame']
        if 'parentId' in frame:
            self._on_frame_attached(
                frame['id'],
                frame['parentId'],
            )
        self._on_frame_navigated(frame)
        if 'childFrames' not in frame_tree:
            return
        for child in frame_tree['childFrames']:
            self._handle_frame_tree(child)

    def _on_frame_attached(self, frame_id: str, parent_frame_id: str) -> None:
        if frame_id in self._frames:
            return
        parent_frame = self._frames.get(parent_frame_id)
        frame = Frame(self._client, parent_frame, frame_id)
        self._frames[frame_id] = frame
        self.emit(FRAME_ATTACHED, frame)

    def _on_frame_navigated(self, frame_payload: dict) -> None:
        is_main_frame = not frame_payload.get('parentId')
        if is_main_frame:
            frame = self._main_frame
        else:
            frame = self._frames.get(frame_payload.get('id', ''))
        if not (is_main_frame or frame):
            raise PageError(
                'Either navigated to top level or have a'
                ' stale version of the navigated frame.'
            )
        # Detach all child frames first.
        if frame:
            for child in frame.child_frames:
                self._remove_frames_recursively(child)
        # Update or create main frame.
        _id = frame_payload.get('id', '')
        if is_main_frame:
            if frame:
                # Update id to retain identity on cross-process navigation.
                self._frames.pop(frame._id, None)
                frame._id = _id
            else:
                # Initial main frame navigation.
                frame = Frame(self._client, None, _id)
            self._frames[_id] = frame
            self._main_frame = frame
        # Update frame payload.
        frame._navigated(frame_payload)
        self.emit(FRAME_NAVIGATED, frame)

    def _on_frame_navigated_within_document(
        self,
        frame_id: str,
        url: str,
    ) -> None:
        frame = self._frames.get(frame_id)
        if not frame:
            return
        frame._navigated_within_document(url)
        self.emit(FRAME_NAVIGATED_IN_DOC, frame)
        self.emit(FRAME_NAVIGATED, frame)

    def _on_frame_detached(self, frame_id: str) -> None:
        frame = self._frames.get(frame_id)
        if frame:
            self._remove_frames_recursively(frame)

    def _on_execution_context_created(self, context_payload: dict) -> None:
        aux_data = context_payload.get('auxData')
        if aux_data and aux_data.get('frameId'):
            frame_id = aux_data['frameId']
        else:
            frame_id = None
        frame = self._frames.get(frame_id)
        object_handle_factory = (
            lambda obj: self.create_javascript_handle(
                self.execution_context_by_id(context_payload['id']),
                obj,
            )
        )
        context = ExecutionContext(
            self._client,
            context_payload,
            object_handle_factory,
            frame,
        )
        self._context_id_to_context[context_payload['id']] = context
        if frame:
            frame._add_execution_context(context)

    def _on_execution_context_destroyed(
        self,
        execution_context_id: str,
    ) -> None:
        context = self._context_id_to_context.get(execution_context_id)
        if not context:
            return
        self._context_id_to_context.pop(execution_context_id)
        if context.frame:
            context.frame._remove_execution_context(context)

    def _on_execution_contexts_cleared(self) -> None:
        for context in self._context_id_to_context.values():
            if context.frame:
                context.frame._remove_execution_context(context)
        self._context_id_to_context.clear()

    def _remove_frames_recursively(self, frame: Frame) -> None:
        for child in frame.child_frames:
            self._remove_frames_recursively(child)
        frame._detach()
        self._frames.pop(frame._id, None)
        self.emit(FRAME_DETACHED, frame)

    def frames(self) -> list[Frame]:
        """
        A list of all `mokr.frame.Frame` objects under this manager.

        Returns:
            list[Frame]: All `mokr.frame.Frame`s controlled by this class.
        """
        return list(self._frames.values())

    def frame(self, frame_id: str) -> Frame | None:
        """
        Return a frame with the given `frame_id`, if any.

        Args:
            frame_id (str): Remote frame identifier.

        Returns:
            Frame | None: `mokr.frame.Frame`, if any match given `frame_id`.
        """
        return self._frames.get(frame_id)

    def execution_context_by_id(self, context_id: str) -> ExecutionContext:
        """
        Get a `mokr.execution.ExecutionContext` under this manager.

        Args:
            context_id (str): Target context identifier.

        Raises:
            ElementHandleError: Raised if no context matches `context_id`.

        Returns:
            ExecutionContext: `mokr.execution.ExecutionContext` created
                by this `FrameManager` with given `context_id`.
        """
        context = self._context_id_to_context.get(context_id)
        if not context:
            raise ElementHandleError(f'No context with id of: {context_id}')
        return context

    def create_javascript_handle(
        self,
        context: ExecutionContext,
        remote_object: dict = None,
    ) -> JavascriptHandle:
        """
        Create a `mokr.execution.JavascriptHandle` for given context.

        Args:
            context (ExecutionContext): `mokr.execution.ExecutionContext` to
                pass into initialisation.
            remote_object (dict, optional): Remote object to be represented by
                new `mokr.execution.JavascriptHandle`. Defaults to None.

        Returns:
            JavascriptHandle: _description_
        """
        if remote_object is None:
            remote_object = {}
        if remote_object.get('subtype') == 'node':
            return ElementHandle(
                context,
                self._client,
                remote_object,
                self._page,
                self,
            )
        return JavascriptHandle(context, self._client, remote_object)

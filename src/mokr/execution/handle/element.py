from __future__ import annotations

import copy
import logging
import math
import os.path
from typing import TYPE_CHECKING, Literal

from mokr.connection import DevtoolsConnection
from mokr.constants import (
    DOM_BOX_MODEL,
    DOM_CONTENT_QUADS,
    DOM_DESCRIBE_NODE,
    DOM_INPUT_FILES,
    METHOD_ELEMENT_IN_VIEW,
    METHOD_EVAL_XPATH,
    METHOD_FOCUS_ELEMENT,
    METHOD_SCROLL_INTO_VIEW,
    PAGE_GET_LAYOUT,
)
from mokr.exceptions import ElementHandleError, NetworkError
from mokr.execution.context import ExecutionContext, JavascriptHandle

if TYPE_CHECKING:
    from mokr.browser.page import Page
    from mokr.frame import Frame, FrameManager


LOGGER = logging.getLogger(__name__)


class ElementHandle(JavascriptHandle):
    def __init__(
        self,
        context: ExecutionContext,
        client: DevtoolsConnection,
        remote_object: dict,
        page: Page,
        frame_manager: FrameManager,
    ) -> None:
        """
        Representation of a DOM element.

        Creation of an `ElementHandle` blocks the remote DOM element from
        garbage collection unless it is disposed manually or the parent frame
        is navigated from.

        Args:
            context (ExecutionContext): `mokr.execution.ExecutionContext` of the
                `mokr.frame.FrameManager` that spawned this.
            client (DevtoolsConnection): Remote connection from parent.
            remote_object (dict): The raw response from the remote connection
                representing the object.
            page (Page): The `mokr.browser.Page` the element was located in.
            frame_manager (FrameManager): The parent `mokr.frame.FrameManager`
                that spawned this element.
        """
        super().__init__(context, client, remote_object)
        self._client = client
        self._remote_object = remote_object
        self._page = page
        self._frame_manager = frame_manager
        self._disposed = False

    @staticmethod
    def _compute_quad_area(quad: list[dict]) -> float:
        area = 0
        for i, _ in enumerate(quad):
            p1 = quad[i]
            p2 = quad[(i + 1) % len(quad)]
            area += (p1['x'] * p2['y'] - p2['x'] * p1['y']) / 2
        return area

    async def _scroll_into_view_if_needed(self) -> None:
        error = await self.execution_context.evaluate(
            METHOD_SCROLL_INTO_VIEW,
            self,
            self._page._javascript_enabled,
        )
        if error:
            raise ElementHandleError(error)

    async def _calculate_origin(self) -> dict[str, float]:
        result = None
        try:
            result = await self._client.send(
                DOM_CONTENT_QUADS,
                {'objectId': self._remote_object.get('objectId')}
            )
        except Exception:
            LOGGER.error(
                "Unhandled error calculating point on element.",
                exc_info=True,
            )
        if not result or not result.get('quads'):
            raise ElementHandleError
        quads = []
        for _quad in result.get('quads'):
            _q = self._from_protocol_quad(_quad)
            if self._compute_quad_area(_q) > 1:
                quads.append(_q)
        if not quads:
            raise ElementHandleError
        quad = quads[0]
        x = 0
        y = 0
        for point in quad:
            x += point['x']
            y += point['y']
        return {'x': x / 4, 'y': y / 4}

    async def _get_box_model(self) -> dict | None:
        try:
            result: dict | None = await self._client.send(
                DOM_BOX_MODEL,
                {'objectId': self._remote_object.get('objectId')},
            )
        except NetworkError:
            LOGGER.error("Error getting box model.", exc_info=True)
            result = None
        return result

    def _from_protocol_quad(self, quad: list[int]) -> list[dict[str, int]]:
        return [
            {'x': quad[0], 'y': quad[1]},
            {'x': quad[2], 'y': quad[3]},
            {'x': quad[4], 'y': quad[5]},
            {'x': quad[6], 'y': quad[7]},
        ]

    def _as_element(self) -> ElementHandle:
        # Used in parity with JavascriptHandle.
        return self

    async def content_frame(self) -> Frame | None:
        """
        Return the content frame for this element or None if not within iframe.

        Returns:
            Frame | None: Target `mokr.frame.Frame` if within iframe.
        """
        node_info = await self._client.send(
            DOM_DESCRIBE_NODE,
            {'objectId': self._remote_object.get('objectId')}
        )
        node_obj = node_info.get('node', {})
        if not isinstance(node_obj.get('frameId'), str):
            return None
        return self._frame_manager.frame(node_obj['frameId'])

    async def content(self) -> str:
        html_handle = await self.get_property("outerHTML")
        value = html_handle._remote_object.get("value")
        return value if value else ""

    async def hover(self) -> None:
        """
        Mouse hover over this element.

        Raises:
            ElementHandleError: Raised if element is detached from DOM.
        """
        await self._scroll_into_view_if_needed()
        center = await self._calculate_origin()
        x = center.get('x', 0)
        y = center.get('y', 0)
        await self._page.mouse.move(x, y)

    async def click(
        self,
        button: Literal["left", "right", "middle"] = "left",
        click_count: int = 1,
        delay: int | float | None = 1000,
    ) -> None:
        """
        Click the center of this element with the bound
        `ElementHandle._page.mouse`.

        If not in view, this will attempt to scroll the element into view.

        Args:
            button (Literal["left", "right", "middle"], optional): Mouse button
                to click with. Defaults to "left".
            click_count (int, optional): Number of clicks to run. Defaults to 1.
            delay (int | float | None, optional): Time in milliseconds to wait
                before each click. Defaults to 1000.

        Raises:
            ElementHandleError: Raised if element is detached from DOM.
        """
        await self._scroll_into_view_if_needed()
        center = await self._calculate_origin()
        x = center.get('x', 0)
        y = center.get('y', 0)
        await self._page.mouse.click(x, y, button, click_count, delay)

    async def upload_file(self, file_paths: list[str]) -> None:
        """
        Set files at given `file_paths` as upload targets for this element.

        Args:
            file_paths (list[str]): List of file paths for upload.
        """
        self._page._is_firefox(caller=self)
        files = [os.path.abspath(p) for p in file_paths]
        object_id = self._remote_object.get('objectId')
        return await self._client.send(
            DOM_INPUT_FILES,
            {'objectId': object_id, 'files': files}
        )

    async def tap(self) -> None:
        """
        Tap the center of this element with the bound
        `ElementHandle._page.touchscreen`.

        If not in view, this will attempt to scroll the element into view.

        Raises:
            ElementHandleError: Raised if element is detached from DOM.
        """
        self._page._is_firefox(caller=self)
        await self._scroll_into_view_if_needed()
        center = await self._calculate_origin()
        x = center.get('x', 0)
        y = center.get('y', 0)
        await self._page.touchscreen.tap(x, y)

    async def focus(self) -> None:
        """Focus on this element."""
        await self.execution_context.evaluate(METHOD_FOCUS_ELEMENT, self)

    async def type_text(self, text: str, delay: int | float = 0) -> None:
        """
        Focus this element and type characters into it. Uses bound
        `ElementHandle._page.keyboard`.

        Note that modifier keys do not alter text case, meaning sending
        `mokr.input.Keyboard.press("shift")` and typing
        `ElementHandle.type_text("mokr")` will not type "MOKR" into the it.

        Args:
            text (str): Text to type.
            delay (int | float, optional): Time in milliseconds to wait between
                each character typed. Defaults to 0.
        """
        await self.focus()
        await self._page.keyboard.type_text(text, delay)

    async def press(self, key: str, delay: int | float | None = None) -> None:
        """
        Focus this element and press the given `key` by sending
        `mokr.input.Keyboard.down` and `mokr.input.Keyboard.up` events, with
        the given `delay` in between.

        Modifier keys effect this method, meaning sending
        `mokr.input.Keyboard.press("shift")` and then
        `mokr.input.Keyboard.press("m")` will type an uppercase "M".

        Args:
            key (str): Name of key. See `mokr.input.Keyboard.key_definitions`.
            delay (int | float | None, optional): Time in milliseconds to "hold"
                the key down. Defaults to None.
        """
        await self.focus()
        await self._page.keyboard.press(key, delay)

    async def bounding_box(self) -> dict[str, float] | None:
        """
        Return the bounding box for this element, if visible. Othwerise,
        return None.

        Returns:
            dict[str, float] | None: Dictionary keyed with "x", "y", "width",
                and "height", if visible. Othwerwise, None.
        """
        result = await self._get_box_model()
        if not result:
            return None
        quad = result['model']['border']
        x = min(quad[0], quad[2], quad[4], quad[6])
        y = min(quad[1], quad[3], quad[5], quad[7])
        width = max(quad[0], quad[2], quad[4], quad[6]) - x
        height = max(quad[1], quad[3], quad[5], quad[7]) - y
        return {'x': x, 'y': y, 'width': width, 'height': height}

    async def box_model(self) -> dict | None:
        """
        Return the box model for this element, if visible. Otherwise, None.

        Returns:
            dict | None: If not visible, None. Othwerwise, Dictionary keyed with
                "content", "padding", "border", "margin", "width", and "height".
                Each key value will be a dictionary containing "x" and "y".
        """
        result = await self._get_box_model()
        if not result:
            return None
        model = result.get('model', {})
        return {
            'content': self._from_protocol_quad(model.get('content')),
            'padding': self._from_protocol_quad(model.get('padding')),
            'border': self._from_protocol_quad(model.get('border')),
            'margin': self._from_protocol_quad(model.get('margin')),
            'width': model.get('width'),
            'height': model.get('height'),
        }

    async def screenshot(
        self,
        file_type: Literal["png", "jpeg"] | None = None,
        file_path: str | None = None,
        jpeg_quality: int | None = None,
        omit_background: bool = False,
        encoding: Literal["binary", "base64"] = "binary",
        scale: int | float = 1,
    ) -> bytes:
        """
        Take a screenshot of the element. Will scroll element inyo the viewport,
        if needed.

        Args:
            file_type (Literal["png", "jpeg"] | None, optional): File type
                to save the image as. Defaults to "png" if None.
            file_path (str | None, optional): Path to save image to. If given
                without `file_type`,  the type will be inferred.
                Defaults to None.
            jpeg_quality (int | None, optional): JPEG quality, 0-100 (only
                applicable if type is or is inferred to be JPEG.
                Defaults to 100 if None.
            omit_background (bool, optional): Make the background transparent
                if True.
                Not supported on Firefox.
                Defaults to False.
            encoding (Literal["binary", "base64"], optional): Encoding type
                to return the image data as. Defaults to "binary".
            scale (int | float, optional): Image scale, 0-1. Defaults to 1.

        Raises:
            ValueError: Raised if `file_type` isn't given and can't be inferred
                as a supported type from `file_path`, if given.
            ElementHandleError: Raised if element is not visible (has no
                `mokr.execution.ElementHandle.bounding_box`).

        Returns:
            bytes: The image content.
        """
        needs_viewport_reset = False
        bounding_box = await self.bounding_box()
        if not bounding_box:
            raise ElementHandleError
        original_viewport = copy.deepcopy(self._page.viewport)
        if (
            bounding_box['width'] > original_viewport['width']
            or bounding_box['height'] > original_viewport['height']
        ):
            new_viewport = {
                'width': max(
                    original_viewport['width'],
                    math.ceil(bounding_box['width']),
                ),
                'height': max(
                    original_viewport['height'],
                    math.ceil(bounding_box['height']),
                ),
            }
            new_viewport = copy.deepcopy(original_viewport)
            new_viewport.update(new_viewport)
            await self._page.set_viewport(new_viewport)
            needs_viewport_reset = True
        await self._scroll_into_view_if_needed()
        bounding_box = await self.bounding_box()
        if not bounding_box:
            raise ElementHandleError
        _obj = await self._client.send(PAGE_GET_LAYOUT)
        page_x = _obj['layoutViewport']['pageX']
        page_y = _obj['layoutViewport']['pageY']
        clip = copy.deepcopy(bounding_box)
        clip['x'] = clip['x'] + page_x
        clip['y'] = clip['y'] + page_y
        buffer = await self._page.screenshot(
            file_type=file_type,
            file_path=file_path,
            jpeg_quality=jpeg_quality,
            clip=clip,
            omit_background=omit_background,
            encoding=encoding,
            scale=scale,
        )
        if needs_viewport_reset:
            await self._page.set_viewport(original_viewport)
        return buffer

    async def query_selector(self, selector: str) -> ElementHandle | None:
        """
        Return the first child element in this element that matches the
        selector, if any.

        Args:
            selector (str): Element selector to locate.

        Returns:
            ElementHandle | None: ElementHandle if found or None.
        """
        handle = await self.execution_context.evaluate_handle(
            '(element, selector) => element.querySelector(selector)',
            self,
            selector,
        )
        element = handle._as_element()
        if element:
            return element
        await handle.dispose()
        return None

    async def query_selector_all(self, selector: str) -> list[ElementHandle]:
        """
        Return all child elements in this element that match the selector,
        if any.

        Args:
            selector (str): Element selector to locate.

        Returns:
            list[ElementHandle]: List of ElementHandle if any or empty list.
        """
        array_handle = await self.execution_context.evaluate_handle(
            '(element, selector) => element.querySelectorAll(selector)',
            self, selector,
        )
        properties = await array_handle.get_properties()
        await array_handle.dispose()
        return [prop._as_element() for prop in properties.values()]

    async def xpath(self, expression: str) -> list[ElementHandle]:
        """
        Return all child elements in this element that match the expression,
        if any.

        Args:
            expression (str): XPath expression to evaluate.

        Returns:
            list[ElementHandle]: List of ElementHandle if any or empty list.
        """
        array_handle = await self.execution_context.evaluate_handle(
            METHOD_EVAL_XPATH,
            self,
            expression,
        )
        properties = await array_handle.get_properties()
        await array_handle.dispose()
        return [prop._as_element() for prop in properties.values()]

    async def is_in_viewport(self) -> bool:
        """
        Evaluate if the element is withing the viewport.

        Returns:
            bool: True if in viewport, else False.
        """
        return await self.execution_context.evaluate(
            METHOD_ELEMENT_IN_VIEW,
            self,
        )

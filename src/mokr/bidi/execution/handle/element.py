from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mokr.bidi.frame.frame import BidiFrame


class BidiElementHandle:
    """A DOM node represented by a BiDi shared reference."""

    def __init__(self, frame: BidiFrame, remote_value: dict[str, Any]) -> None:
        """Create an element handle from a BiDi node remote value.

        Args:
            frame: Frame containing the element.
            remote_value: BiDi node value with a shared reference.

        Raises:
            ValueError: If the value has no shared node reference.
        """
        shared_id = remote_value.get("sharedId")
        if not shared_id:
            raise ValueError(
                "BiDi locator did not return a shared node reference."
            )
        self._frame = frame
        self._remote_value = remote_value
        self._shared_id = shared_id

    async def click(self) -> None:
        """Click this element through its DOM ``click`` method."""
        await self._call("element => element.click()")

    async def hover(self) -> None:
        """Move the page mouse pointer to this element's center.

        Raises:
            RuntimeError: If the element is detached.
        """
        box = await self.bounding_box()
        if box is None:
            raise RuntimeError("Cannot hover a detached element.")
        await self._frame._page.mouse.move(
            box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        )

    async def focus(self) -> None:
        """Focus this element."""
        await self._call("element => element.focus()")

    async def type_text(self, text: str, delay: int = 0) -> None:
        """Focus this element and type text into it.

        Args:
            text: Text to type.
            delay: Time in milliseconds between characters. Defaults to ``0``.
        """
        await self.focus()
        await self._frame._page.keyboard.type_text(text, delay)

    async def tap(self) -> None:
        """Tap the center of this element.

        Raises:
            RuntimeError: If the element is detached.
        """
        box = await self.bounding_box()
        if box is None:
            raise RuntimeError("Cannot tap a detached element.")
        await self._frame._page.touchscreen.tap(
            box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        )

    async def select(self, values: list[str]) -> list[str]:
        """Select option values and return the resulting selected values.

        Args:
            values: Option values to select.
        """
        return await self._primitive(
            "(element, values) => { for (const option of element.options) option.selected = values.includes(option.value); element.dispatchEvent(new Event('input', {bubbles: true})); element.dispatchEvent(new Event('change', {bubbles: true})); return Array.from(element.selectedOptions, option => option.value); }",
            [
                self._frame._page._browser._session.serialize_remote_value(
                    values
                )
            ],
        )

    async def content(self) -> str:
        """Return this element's serialized outer HTML."""
        return await self._primitive("element => element.outerHTML")

    async def upload_file(self, file_paths: list[str]) -> None:
        """Set files on this file-input element.

        Args:
            file_paths: Local file paths to upload.
        """
        await self._frame._page._browser._session.set_files(
            self._frame._context_id, self._remote_value, file_paths
        )

    async def bounding_box(self) -> dict[str, float] | None:
        """Return the element's viewport bounding box."""
        return await self._primitive(
            "element => { const box = element.getBoundingClientRect(); return {x: box.x, y: box.y, width: box.width, height: box.height}; }"
        )

    async def screenshot(self, **kwargs: Any) -> bytes | str:
        """Capture a screenshot clipped to this element.

        Args:
            **kwargs: Additional page screenshot options.

        Raises:
            RuntimeError: If the element is detached.
        """
        clip = await self.bounding_box()
        if clip is None:
            raise RuntimeError("Cannot screenshot a detached element.")
        return await self._frame._page.screenshot(clip=clip, **kwargs)

    async def _call(self, function_declaration: str) -> None:
        await self._frame._page._browser._session.call_function(
            self._frame._context_id,
            function_declaration,
            [{"sharedId": self._shared_id}],
        )

    async def _primitive(
        self,
        function_declaration: str,
        arguments: list[dict[str, Any]] | None = None,
    ) -> Any:
        value = await self._frame._page._browser._session.call_function(
            self._frame._context_id,
            function_declaration,
            [{"sharedId": self._shared_id}, *(arguments or [])],
        )
        return self._frame._page._browser._session._deserialize_remote_value(
            value
        )

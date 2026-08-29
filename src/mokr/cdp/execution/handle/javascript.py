from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from mokr.cdp.connection import CdpSession
from mokr.constants import (
    METHOD_GET_PROPERTY,
    RUNTIME_CALL_FUNCTION,
    RUNTIME_GET_PROPERTIES,
)
from mokr.utils.remote import release_remote_object, serialize_remote_object

if TYPE_CHECKING:
    from mokr.cdp.execution.context import CdpExecutionContext


LOGGER = logging.getLogger(__name__)


class CdpJavascriptHandle:
    def __init__(
        self,
        context: CdpExecutionContext,
        client: CdpSession,
        remote_object: dict,
    ) -> None:
        """
        Representative of a JavaScript object within the frame.
        JavascriptHandles are created automatically by `mokr.cdp.frame.CdpFrameManager`
        and `mokr.cdp.browser.CdpWebWorker`.

        Args:
            context (CdpExecutionContext): `mokr.cdp.execution.CdpExecutionContext` of the
                `mokr.cdp.frame.CdpFrameManager` that spawned this.
            client (CdpSession): Remote connection from parent.
            remote_object (dict): The raw response from the remote connection
                representing the object.
        """
        self._context = context
        self._client = client
        self._remote_object = remote_object
        self._disposed = False

    @property
    def execution_context(self) -> CdpExecutionContext:
        """Get `mokr.cdp.execution.CdpExecutionContext` of this handle."""
        return self._context

    def _as_element(self) -> None:
        # Used in parity with CdpElementHandle.
        return None

    async def get_property(self, property_name: str) -> CdpJavascriptHandle:
        """
        Get a property of the remote object related to this handle.

        Args:
            property_name (str): Name of the target property.

        Returns:
            CdpJavascriptHandle: Newly created `CdpJavascriptHandle` from the result.
        """
        object_handle = await self._context.evaluate_handle(
            METHOD_GET_PROPERTY,
            self,
            property_name,
        )
        properties = await object_handle.get_properties()
        result = properties[property_name]
        await object_handle.dispose()
        return result

    async def get_properties(self) -> dict[str, CdpJavascriptHandle]:
        """
        Get all properties of the remote object related to this handle.

        Returns:
            dict[str, CdpJavascriptHandle]: Dictionary keyed as "property name" to
                newly created `CdpJavascriptHandle`s from the results.
        """
        response = await self._client.send(
            RUNTIME_GET_PROPERTIES,
            {
                "objectId": self._remote_object.get("objectId", ""),
                "ownProperties": True,
            },
        )
        result = {}
        for prop in response["result"]:
            if not prop.get("enumerable"):
                continue
            result[prop.get("name")] = self._context._object_handle_factory(
                prop.get("value")
            )
        return result

    async def json(self) -> dict:
        """
        Get and JSONify the values of the remote object this handle represents.

        Returns:
            dict: Dictionary of JSONified values.
        """
        object_id = self._remote_object.get("objectId")
        if object_id:
            response = await self._client.send(
                RUNTIME_CALL_FUNCTION,
                {
                    "functionDeclaration": "function() { return this; }",
                    "objectId": object_id,
                    "returnByValue": True,
                    "awaitPromise": True,
                },
            )
            return serialize_remote_object(response["result"])
        return serialize_remote_object(self._remote_object)

    async def dispose(self) -> None:
        """
        Stop referencing this handle. Allows it to be garbage-collected by the
        browser.
        """
        if self._disposed:
            return
        self._disposed = True
        try:
            await release_remote_object(
                self._client,
                self._remote_object,
            )
        except Exception:
            LOGGER.error("Error disposing element.", exc_info=True)

    def to_string(self) -> str:
        """
        Get a string representation of the remote object this represents.

        Returns:
            str: String representation of remote object. May contain
                object data or just the type.
        """
        if self._remote_object.get("objectId"):
            _type = self._remote_object.get(
                "subtype"
            ) or self._remote_object.get("type")
            return f"CdpJavascriptHandle@{_type}"
        return "CdpJavascriptHandle:{}".format(
            serialize_remote_object(self._remote_object)
        )

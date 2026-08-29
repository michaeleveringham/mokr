from __future__ import annotations

import base64
import json
from typing import Any

from mokr.bidi.connection.connection import BidiConnection


class BidiSession:
    """Expose typed operations over a WebDriver BiDi connection.

    Unlike :class:`CdpSession`, which is a target-scoped transport,
    ``BidiSession`` is a command facade over one browser-level
    :class:`BidiConnection`. It owns BiDi command names and payload shapes so
    browser, page, network, and input objects do not translate wire messages.
    """

    def __init__(self, connection: BidiConnection) -> None:
        """Create a command facade for an active BiDi connection.

        Args:
            connection: Event-capable WebDriver BiDi transport.
        """
        self._connection = connection

    @property
    def connection(self) -> BidiConnection:
        """Return the underlying event-capable WebSocket connection."""
        return self._connection

    async def subscribe(
        self,
        events: list[str],
        contexts: list[str] | None = None,
    ) -> None:
        """Subscribe to BiDi events globally or for selected contexts.

        Args:
            events: Fully qualified BiDi event names.
            contexts: Optional browsing-context identifiers used to scope the
                subscription.
        """
        params: dict[str, Any] = {"events": events}
        if contexts:
            params["contexts"] = contexts
        await self._connection.send("session.subscribe", params)

    async def create_user_context(self) -> str:
        """Create an isolated browser user context and return its identifier."""
        result = await self._connection.send("browser.createUserContext")
        return result["userContext"]

    async def get_tree(self) -> list[dict[str, Any]]:
        """Return metadata for the current top-level browsing contexts."""
        result = await self._connection.send(
            "browsingContext.getTree", {"maxDepth": 0}
        )
        return result.get("contexts", [])

    async def remove_user_context(self, context_id: str) -> None:
        """Remove an isolated browser user context.

        Args:
            context_id: User-context identifier to remove.
        """
        await self._connection.send(
            "browser.removeUserContext", {"userContext": context_id}
        )

    async def create_page(self, user_context: str | None = None) -> str:
        """Create a tab and return its browsing-context identifier.

        Args:
            user_context: Optional isolated user context for the new tab.
        """
        params: dict[str, Any] = {"type": "tab"}
        if user_context:
            params["userContext"] = user_context
        result = await self._connection.send("browsingContext.create", params)
        return result["context"]

    async def close_page(self, context_id: str) -> None:
        """Close a browsing context.

        Args:
            context_id: Browsing context to close.
        """
        await self._connection.send(
            "browsingContext.close", {"context": context_id}
        )

    async def activate_page(self, context_id: str) -> None:
        """Bring a browsing context to the foreground.

        Args:
            context_id: Browsing context to activate.
        """
        await self._connection.send(
            "browsingContext.activate", {"context": context_id}
        )

    async def reload_page(
        self,
        context_id: str,
        wait: str = "complete",
        ignore_cache: bool = False,
    ) -> dict[str, Any]:
        """Reload a context and return BiDi navigation metadata.

        Args:
            context_id: Browsing context to reload.
            wait: BiDi readiness state to await. Defaults to ``"complete"``.
            ignore_cache: Whether to bypass the browser cache.

        Returns:
            Navigation metadata returned by ``browsingContext.reload``.
        """
        return await self._connection.send(
            "browsingContext.reload",
            {
                "context": context_id,
                "wait": wait,
                "ignoreCache": ignore_cache,
            },
        )

    async def traverse_history(self, context_id: str, delta: int) -> None:
        """Move a browsing context through its session history.

        Args:
            context_id: Browsing context whose history should change.
            delta: Signed number of entries to traverse.
        """
        await self._connection.send(
            "browsingContext.traverseHistory",
            {"context": context_id, "delta": delta},
        )

    async def navigate(
        self,
        context_id: str,
        url: str,
        wait: str = "complete",
    ) -> dict[str, Any]:
        """Navigate a context and return BiDi navigation metadata.

        Args:
            context_id: Browsing context to navigate.
            url: Destination URL.
            wait: BiDi readiness state to await. Defaults to ``"complete"``.

        Returns:
            Navigation metadata returned by ``browsingContext.navigate``.
        """
        return await self._connection.send(
            "browsingContext.navigate",
            {"context": context_id, "url": url, "wait": wait},
        )

    async def evaluate(self, context_id: str, expression: str) -> Any:
        """Evaluate JavaScript in a browsing context and deserialize it.

        Args:
            context_id: Browsing context containing the target realm.
            expression: JavaScript expression to evaluate.

        Raises:
            RuntimeError: If the browser reports a JavaScript exception.

        Returns:
            The result converted from a BiDi remote value to Python.
        """
        result = await self._connection.send(
            "script.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "target": {"context": context_id},
                "resultOwnership": "none",
            },
        )
        if result.get("type") == "exception":
            details = result.get("exceptionDetails", {})
            raise RuntimeError(
                details.get("text", "JavaScript evaluation failed.")
            )
        return self._deserialize_remote_value(result.get("result"))

    @staticmethod
    def serialize_remote_value(value: Any) -> dict[str, Any]:
        """Encode a JSON-like Python value as a BiDi remote value.

        Args:
            value: Value to serialize.

        Raises:
            TypeError: If the value is not composed of JSON-like types.

        Returns:
            A WebDriver BiDi ``script.RemoteValue`` mapping.
        """
        if value is None:
            return {"type": "null"}
        if isinstance(value, bool):
            return {"type": "boolean", "value": value}
        if isinstance(value, (int, float)):
            return {"type": "number", "value": value}
        if isinstance(value, str):
            return {"type": "string", "value": value}
        if isinstance(value, (list, tuple)):
            return {
                "type": "array",
                "value": [
                    BidiSession.serialize_remote_value(item) for item in value
                ],
            }
        if isinstance(value, dict):
            return {
                "type": "object",
                "value": [
                    [str(key), BidiSession.serialize_remote_value(item)]
                    for key, item in value.items()
                ],
            }
        raise TypeError(
            "BiDi evaluation arguments must be JSON-like values; "
            f"got {type(value).__name__}."
        )

    async def call_function(
        self,
        context_id: str,
        function_declaration: str,
        arguments: list[dict[str, Any]] | None = None,
        result_ownership: str = "none",
        target: dict[str, str] | None = None,
    ) -> Any:
        """Call JavaScript in a context or an explicit BiDi target.

        Args:
            context_id: Default browsing context for the call.
            function_declaration: JavaScript function source.
            arguments: Serialized BiDi remote-value arguments.
            result_ownership: Ownership requested for the returned remote
                value.
            target: Explicit BiDi target overriding ``context_id``.

        Raises:
            RuntimeError: If the browser reports a JavaScript exception.

        Returns:
            The returned BiDi remote value.
        """
        result = await self._connection.send(
            "script.callFunction",
            {
                "functionDeclaration": function_declaration,
                "awaitPromise": True,
                "target": target or {"context": context_id},
                "arguments": arguments or [],
                "resultOwnership": result_ownership,
            },
        )
        if result.get("type") == "exception":
            details = result.get("exceptionDetails", {})
            raise RuntimeError(
                details.get("text", "JavaScript evaluation failed.")
            )
        return result.get("result")

    async def set_content(self, context_id: str, html: str) -> None:
        """Replace a browsing context's document HTML.

        Args:
            context_id: Browsing context whose document should change.
            html: New markup for ``document.documentElement``.
        """
        expression = f"document.documentElement.innerHTML = {json.dumps(html)}"
        await self.evaluate(context_id, expression)

    async def add_preload_script(
        self,
        function_declaration: str,
        contexts: list[str] | None = None,
        arguments: list[dict[str, Any]] | None = None,
    ) -> str:
        """Install a preload script and return its identifier.

        Args:
            function_declaration: JavaScript function installed in new realms.
            contexts: Optional browsing contexts that scope the script.
            arguments: Optional serialized BiDi channel arguments.

        Returns:
            Identifier used to remove the script later.
        """
        params: dict[str, Any] = {"functionDeclaration": function_declaration}
        if contexts:
            params["contexts"] = contexts
        if arguments:
            params["arguments"] = arguments
        result = await self._connection.send("script.addPreloadScript", params)
        return result["script"]

    async def remove_preload_script(self, script_id: str) -> None:
        """Remove a previously installed preload script."""
        await self._connection.send(
            "script.removePreloadScript", {"script": script_id}
        )

    async def set_user_agent(
        self, context_id: str, user_agent: str | None
    ) -> None:
        """Set or clear the user-agent override for a context."""
        await self._connection.send(
            "emulation.setUserAgentOverride",
            {"userAgent": user_agent, "contexts": [context_id]},
        )

    async def capture_screenshot(
        self, context_id: str, options: dict[str, Any]
    ) -> str:
        """Capture a screenshot and return its base64-encoded data."""
        result = await self._connection.send(
            "browsingContext.captureScreenshot",
            {"context": context_id, **options},
        )
        return result["data"]

    async def print_page(self, context_id: str, options: dict[str, Any]) -> str:
        """Print a browsing context and return its base64-encoded PDF data."""
        result = await self._connection.send(
            "browsingContext.print",
            {"context": context_id, **options},
        )
        return result["data"]

    async def locate_nodes(
        self,
        context_id: str,
        locator: dict[str, Any],
        start_nodes: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Locate DOM nodes using a BiDi locator."""
        params: dict[str, Any] = {"context": context_id, "locator": locator}
        if start_nodes:
            params["startNodes"] = start_nodes
        result = await self._connection.send(
            "browsingContext.locateNodes", params
        )
        return result.get("nodes", [])

    async def set_viewport(
        self, context_id: str, viewport: dict[str, Any]
    ) -> None:
        """Set a browsing context's viewport configuration."""
        await self._connection.send(
            "browsingContext.setViewport",
            {"context": context_id, **viewport},
        )

    async def handle_user_prompt(
        self,
        context_id: str,
        accept: bool,
        user_text: str = "",
    ) -> None:
        """Accept or dismiss the active user prompt for a context."""
        await self._connection.send(
            "browsingContext.handleUserPrompt",
            {
                "context": context_id,
                "accept": accept,
                "userText": user_text,
            },
        )

    async def perform_actions(
        self, context_id: str, actions: list[dict[str, Any]]
    ) -> None:
        """Perform a sequence of input-source actions.

        Args:
            context_id: Browsing context that receives the actions.
            actions: WebDriver BiDi input-source action sequences.
        """
        await self._connection.send(
            "input.performActions",
            {"context": context_id, "actions": actions},
        )

    async def release_actions(self, context_id: str) -> None:
        """Release active input actions and reset their session state.

        Args:
            context_id: Browsing context whose actions should be released.
        """
        await self._connection.send(
            "input.releaseActions", {"context": context_id}
        )

    async def set_files(
        self, context_id: str, element: dict[str, Any], files: list[str]
    ) -> None:
        """Set files on a shared DOM element reference."""
        await self._connection.send(
            "input.setFiles",
            {"context": context_id, "element": element, "files": files},
        )

    async def get_cookies(self, context_id: str) -> list[dict[str, Any]]:
        """Return cookies partitioned to a browsing context."""
        result = await self._connection.send(
            "storage.getCookies",
            {"partition": {"type": "context", "context": context_id}},
        )
        return result.get("cookies", [])

    async def set_cookie(self, cookie: dict[str, Any], context_id: str) -> None:
        """Set a cookie in a browsing context's storage partition."""
        await self._connection.send(
            "storage.setCookie",
            {
                "cookie": cookie,
                "partition": {"type": "context", "context": context_id},
            },
        )

    async def delete_cookies(
        self, cookie_filter: dict[str, Any], context_id: str
    ) -> None:
        """Delete cookies matching a filter in a storage partition."""
        await self._connection.send(
            "storage.deleteCookies",
            {
                "filter": cookie_filter,
                "partition": {"type": "context", "context": context_id},
            },
        )

    async def add_intercept(
        self,
        phases: list[str],
        contexts: list[str] | None = None,
    ) -> str:
        """Add a network intercept and return its identifier.

        Args:
            phases: Network phases at which requests should be blocked.
            contexts: Optional browsing contexts that scope the intercept.

        Returns:
            Identifier used to remove the intercept later.
        """
        params: dict[str, Any] = {"phases": phases}
        if contexts:
            params["contexts"] = contexts
        result = await self._connection.send("network.addIntercept", params)
        return result["intercept"]

    async def remove_intercept(self, intercept_id: str) -> None:
        """Remove a network intercept."""
        await self._connection.send(
            "network.removeIntercept", {"intercept": intercept_id}
        )

    async def continue_request(self, request_id: str) -> None:
        """Continue a paused network request unchanged.

        Args:
            request_id: BiDi request identifier to continue.
        """
        await self._connection.send(
            "network.continueRequest", {"request": request_id}
        )

    async def continue_with_auth(
        self,
        request_id: str,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        """Provide credentials for, or cancel, an authentication challenge.

        Args:
            request_id: Request associated with the challenge.
            username: Username to provide; ``None`` cancels the challenge.
            password: Password paired with ``username``.
        """
        params: dict[str, Any] = {"request": request_id}
        if username is None:
            params["action"] = "cancel"
        else:
            params.update(
                {
                    "action": "provideCredentials",
                    "credentials": {
                        "type": "password",
                        "username": username,
                        "password": password or "",
                    },
                }
            )
        await self._connection.send("network.continueWithAuth", params)

    async def install_extension(self, path: str) -> str:
        """Install a temporary WebExtension from a path."""
        result = await self._connection.send(
            "webExtension.install",
            {"extensionData": {"type": "path", "path": path}},
        )
        return result["extension"]

    async def uninstall_extension(self, extension_id: str) -> None:
        """Uninstall a temporary WebExtension."""
        await self._connection.send(
            "webExtension.uninstall", {"extension": extension_id}
        )

    async def fail_request(self, request_id: str) -> None:
        """Fail a paused network request.

        Args:
            request_id: BiDi request identifier to fail.
        """
        await self._connection.send(
            "network.failRequest", {"request": request_id}
        )

    async def provide_response(
        self,
        request_id: str,
        status: int,
        headers: dict[str, str],
        body: bytes,
    ) -> None:
        """Fulfill a paused request with a synthetic response.

        Args:
            request_id: BiDi request identifier to fulfill.
            status: HTTP response status code.
            headers: Response headers.
            body: Response body bytes.
        """
        await self._connection.send(
            "network.provideResponse",
            {
                "request": request_id,
                "statusCode": status,
                "headers": [
                    {"name": key, "value": {"type": "string", "value": value}}
                    for key, value in headers.items()
                ],
                "body": {
                    "type": "base64",
                    "value": base64.b64encode(body).decode(),
                },
            },
        )

    async def add_network_data_collector(
        self,
        data_types: list[str],
        max_encoded_data_size: int,
        contexts: list[str] | None = None,
    ) -> str:
        """Collect request or response bodies for the supplied contexts.

        BiDi deliberately does not retain response bodies unless a collector is
        registered before the request starts.  Keeping this operation here
        makes that lifecycle explicit to the browser facade.
        """
        params: dict[str, Any] = {
            "dataTypes": data_types,
            "maxEncodedDataSize": max_encoded_data_size,
        }
        if contexts:
            params["contexts"] = contexts
        result = await self._connection.send("network.addDataCollector", params)
        return result["collector"]

    async def get_network_data(self, request_id: str, collector: str) -> Any:
        """Read body data retained by a network data collector.

        Args:
            request_id: Request whose response body should be read.
            collector: Network data collector identifier.

        Returns:
            Encoded BiDi bytes value returned by ``network.getData``.
        """
        result = await self._connection.send(
            "network.getData",
            {
                "request": request_id,
                "dataType": "response",
                "collector": collector,
            },
        )
        return result.get("bytes")

    async def set_cache_behavior(self, context_id: str, enabled: bool) -> None:
        """Enable normal caching or bypass it for a browsing context."""
        await self._connection.send(
            "network.setCacheBehavior",
            {
                "cacheBehavior": "default" if enabled else "bypass",
                "contexts": [context_id],
            },
        )

    async def set_extra_headers(
        self, context_id: str, headers: dict[str, str]
    ) -> None:
        """Set extra headers for all requests from a browsing context."""
        await self._connection.send(
            "network.setExtraHeaders",
            {
                "headers": [
                    {"name": key, "value": {"type": "string", "value": value}}
                    for key, value in headers.items()
                ],
                "contexts": [context_id],
            },
        )

    @staticmethod
    def _deserialize_remote_value(value: dict[str, Any] | None) -> Any:
        if value is None:
            return None
        value_type = value.get("type")
        if value_type in {"undefined", "null"}:
            return None
        if value_type in {"string", "number", "boolean", "bigint"}:
            return value.get("value")
        if value_type == "array":
            return [
                BidiSession._deserialize_remote_value(item)
                for item in value.get("value", [])
            ]
        if value_type == "object":
            return {
                key: BidiSession._deserialize_remote_value(item)
                for key, item in value.get("value", [])
            }
        return value

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import logging
import math
import mimetypes
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal

from pyee import EventEmitter

from mokr.browser.console import ConsoleMessage
from mokr.browser.viewport import ViewportManager
from mokr.browser.worker import WebWorker
from mokr.connection import DevtoolsConnection
from mokr.constants import (
    CLOSE,
    DOM_LOADED,
    EMULATION_DISABLE_SCRIPT_EXECUTION,
    EMULATION_OVERRIDE_BACKGROUND,
    EMULATION_OVERRIDE_METRICS,
    EMULATION_SET_EMULATED_MEDIA,
    ERROR,
    FRAME_ATTACHED,
    FRAME_DETACHED,
    FRAME_NAVIGATED,
    HTTP_METHODS,
    INSPECTOR_TARGET_CRASHED,
    LIFECYCLE_EVENTS,
    LOG_ENABLE,
    LOG_ENTRY_ADDED,
    METHOD_ADD_PAGE_BINDING,
    METHOD_DELIVER_BINDING_RESULT,
    METRICS,
    NETWORK_CACHE_DISABLE,
    NETWORK_DELETE_COOKIES,
    NETWORK_ENABLE,
    NETWORK_GET_ALL_COOKIES,
    NETWORK_GET_COOKIES,
    NETWORK_MGR_REQUEST_FINISHED,
    NETWORK_MGR_RESPONSE,
    NETWORK_REQUEST_FAILED,
    NETWORK_REQUEST_FINISHED,
    NETWORK_RESPONSE,
    NETWORK_SET_COOKIES,
    PAGE_ADD_SCRIPT_TO_EVAL,
    PAGE_BRING_TO_FRONT,
    PAGE_CLOSE,
    PAGE_CONSOLE,
    PAGE_DIALOG,
    PAGE_DOM_LOADED,
    PAGE_ENABLE,
    PAGE_ENABLE_LIFECYCLE_EVENTS,
    PAGE_ERROR,
    PAGE_GET_FRAME_TREE,
    PAGE_GET_LAYOUT,
    PAGE_GET_NAVIGATION_HISTORY,
    PAGE_JAVASCRIPT_DIALOG_OPEN,
    PAGE_LOAD,
    PAGE_LOAD_EVENT_FIRED,
    PAGE_NAVIGATE,
    PAGE_NAVIGATE_TO_HISTORY_ENTRY,
    PAGE_PRINT_TO_PDF,
    PAGE_SCREENSHOT,
    PAGE_SET_BYPASS_CSP,
    PERFORMANCE_ENABLE,
    PERFORMANCE_GET_METRICS,
    PERFORMANCE_METRICS,
    RUMTIME_BINDING_CALL,
    RUNTIME_ADD_BINDING,
    RUNTIME_CONSOLE_API_CALL,
    RUNTIME_ENABLE,
    RUNTIME_EVALUATE,
    RUNTIME_EXCEPTION_THROWN,
    SECURITY_ENABLE,
    TARGET_ACTIVATE,
    TARGET_ATTACHED,
    TARGET_CLOSE,
    TARGET_DETACHED,
    TARGET_SEND_DETACH,
    TARGET_SET_AUTO_ATTACH,
    WORKER_CREATED,
    WORKER_DESTROYED,
    NETWORK_MGR_REQUEST,
    PAGE_RELOAD
)
from mokr.exceptions import FirefoxNotImplementedError, PageError
from mokr.execution import ElementHandle, JavascriptHandle
from mokr.frame import Frame, FrameManager
from mokr.input import Dialog, Keyboard, Mouse, Touchscreen
from mokr.network import (
    ChromeNetworkManager,
    FetchDomain,
    FirefoxNetworkManager,
    HttpDomain,
    NetworkManager,
    Request,
    Response,
)
from mokr.utils.remote import (
    add_event_listener,
    format_javascript_exception,
    release_remote_object,
    remove_event_listeners,
    serialize_remote_object,
)
from mokr.waiters import EventWaiter, NavigationWaiter

if TYPE_CHECKING:
    from mokr.browser import Browser
    from mokr.browser.target import Target


LOGGER = logging.getLogger(__name__)


class Page(EventEmitter):
    def __init__(
        self,
        browser: Browser,
        client: DevtoolsConnection,
        target: Target,
        frame_tree: dict,
        ignore_https_errors: bool,
        user_agent: str = None,
        screenshot_task_queue: list = None,
        proxy_credentials: dict | None = None,
    ) -> None:
        """
        Representative of a single tab within the browser (more specifically,
        within the browser context).
        This class is laregly the entry-point for most navigation, execution,
        or dom-manipulation tasks. Many methods within this class are simply
        wrappers to bound classes within it.

        `Page` emits events, often "inherited" from other classes (emitted
        in series on recieving them from bound classes); these events can be
        listened on via `Page.on`.
        Note, however, that certain network events will be bound directly to
        this `Page`'s `mokr.network.NetworkManager` when passed to `Page.on`.
        Additionally, `Page.on("request")` will not behaviour as a regular
        listener, but instead be added to the request interception callback
        chain. See `Page.on` for more.

        Args:
            browser (Browser): Parent `mokr.browser.Browser`.
            client (DevtoolsConnection): From parent `mokr.browser.Target`.
            target (Target): Spawning `mokr.browser.Target`.
            frame_tree (dict): Frame tree structure from remote connection.
            ignore_https_errors (bool): Ignore site security errors.
                Inherited from parent `mokr.browser.Browser`.
            user_agent (str): User agent for this page.
                Inherited from parent `mokr.browser.Browser`.
            screenshot_task_queue (list, optional): The screenshot task queue,
                empty by default. Inherited from parent `mokr.browser.Browser`.
            proxy_credentials: (dict | None, optional): Dictionary with proxy
                credentials keyed as "username" and "password". Credentials
                should be for the proxy the browser process is bound to.
                Inherited from parent `mokr.browser.Browser`.
        """
        super().__init__()
        self._browser = browser
        self._closed = False
        self._client = client
        self._target = target
        self._keyboard = Keyboard(client)
        self._mouse = Mouse(client, self._keyboard)
        self._touchscreen = Touchscreen(client, self._keyboard)
        self._frame_manager = FrameManager(client, frame_tree, self)
        self._network_manager: NetworkManager = None
        self._viewport_manager = ViewportManager(client)
        self._page_bindings: dict[str, Callable] = {}
        self._ignore_https_errors = ignore_https_errors
        self._default_navigation_timeout = 30000
        self._javascript_enabled = True
        self._viewport: dict | None = None
        self._proxy_credentials = proxy_credentials if proxy_credentials else {}
        self._user_agent = user_agent
        if screenshot_task_queue is None:
            screenshot_task_queue = []
        self._screenshot_task_queue = screenshot_task_queue
        self._workers: dict[str, WebWorker] = {}
        client.on(TARGET_ATTACHED, self._on_target_attached)
        client.on(TARGET_DETACHED, self._on_target_detached)
        for event_name in [FRAME_ATTACHED, FRAME_DETACHED, FRAME_NAVIGATED]:
            self._frame_manager.on(
                event_name, lambda event: self.emit(event_name, event)
            )
        client_events_to_methods = {
            PAGE_DOM_LOADED: lambda event: self.emit(DOM_LOADED),
            PAGE_LOAD_EVENT_FIRED: lambda event: self.emit(PAGE_LOAD),
            RUNTIME_CONSOLE_API_CALL: lambda event: self._on_console_api(event),
            RUMTIME_BINDING_CALL: lambda event: self._on_binding_called(event),
            PAGE_JAVASCRIPT_DIALOG_OPEN: lambda event: self._on_dialog(event),
            RUNTIME_EXCEPTION_THROWN: lambda exception: self._handle_exception(
                exception.get('exceptionDetails')
            ),
            INSPECTOR_TARGET_CRASHED: lambda event: self._on_target_crashed(),
            PERFORMANCE_METRICS: lambda event: self._emit_metrics(event),
            LOG_ENTRY_ADDED: lambda event: self._on_log_entry_added(event),
        }
        for event_name, method in client_events_to_methods.items():
            client.on(event_name, method)
        self._target._is_closed_promise.add_done_callback(self._set_closed)
        self._interception_callback_chain = [self._default_request_intercept]
        self._callback_chain_listeners = {}
        self._fetch_domain = None
        self._http_domain = None

    @staticmethod
    async def create(
        browser: Browser,
        client: DevtoolsConnection,
        target: Target,
        ignore_https_errors: bool,
        default_viewport: dict | None,
        screenshot_task_queue: list = None,
        proxy_credentials: dict | None = None,
        user_agent_data: dict[str, str] | None = None,
    ) -> Page:
        """
        Async constructor for this class. Necessary to run some asyncronous
        post-initialisation tasks.

        Args:
            browser (Browser): Parent `mokr.browser.Browser`.
            client (DevtoolsConnection): From parent `mokr.browser.Target`.
            target (Target): Spawning `mokr.browser.Target`.
            ignore_https_errors (bool): Ignore site security errors.
                Inherited from parent `mokr.browser.Browser`.
            default_viewport (dict | None): Default viewport configuration.
            screenshot_task_queue (list, optional): The screenshot task queue,
                empty by default. Inherited from parent `mokr.browser.Browser`.
            proxy_credentials: (dict | None, optional): Dictionary with proxy
                credentials keyed as "username" and "password". Credentials
                should be for the proxy the browser process is bound to.
                Inherited from parent `mokr.browser.Browser`.
            user_agent_data (dict[str, str] | None, optional): A dictionary
                containing the user agent and an indicator to whether it was the
                original or an override.

        Returns:
            Page: New `Page` with necessary remote configuration enabled.
        """
        await client.send(PAGE_ENABLE)
        frame_tree = (await client.send(PAGE_GET_FRAME_TREE))['frameTree']
        user_agent = user_agent_data["user_agent"]
        page = Page(
            browser,
            client,
            target,
            frame_tree,
            ignore_https_errors,
            user_agent,
            screenshot_task_queue,
            proxy_credentials,
        )
        network_manager_classes = {
            "chrome": ChromeNetworkManager,
            "firefox": FirefoxNetworkManager,
        }
        network_manager_cls = network_manager_classes.get(browser.kind)
        network_manager: NetworkManager = await network_manager_cls.create(
            page,
            page._client,
            page._frame_manager,
            page._ignore_https_errors,
            page._interception_callback_chain,
        )
        if page._is_firefox(mute=True):
            # Set this to true manually because it cannot be unset and while
            # interception is lacking, it is technically always on.
            network_manager._user_request_interception_enabled = True
        page._network_manager = network_manager
        # TODO emitting a "response" on page from network_mgr_response doesn't
        # behave as expected. Needs further investigaiton, for now we'll alias
        # this in page.on.
        for network_event in [
            NETWORK_MGR_REQUEST,
            NETWORK_MGR_RESPONSE,
            NETWORK_REQUEST_FAILED,
            NETWORK_MGR_REQUEST_FINISHED,
        ]:
            network_manager.on(
                network_event,
                lambda event: page.emit(network_event, event),
            )
        await asyncio.gather(
            client.send(
                TARGET_SET_AUTO_ATTACH,
                {'autoAttach': True, 'waitForDebuggerOnStart': False},
            ),
            client.send(PAGE_ENABLE_LIFECYCLE_EVENTS, {'enabled': True}),
            client.send(NETWORK_ENABLE, {}),
            client.send(RUNTIME_ENABLE, {}),
            client.send(SECURITY_ENABLE, {}),
            client.send(PERFORMANCE_ENABLE, {}),
            client.send(LOG_ENABLE, {}),
        )
        is_firefox = page._is_firefox(mute=True)
        if default_viewport:
            await page.set_viewport(default_viewport)
        if not is_firefox:
            await page.set_request_interception_enabled(True)
        if user_agent_data and user_agent_data.get("overridden"):
            await page.set_user_agent(user_agent)
        if proxy_credentials and not is_firefox:
            await page.set_credentials(proxy_credentials)
        page._fetch_domain = FetchDomain(page)
        return page

    @staticmethod
    def _make_javascript_function_string(method_name: str, *args: Any) -> str:
        # Convert function and arguments to str.
        _args = ', '.join(
            [
                json.dumps('undefined' if arg is None else arg) for arg in args
            ]
        )
        expr = f'({method_name})({_args})'
        return expr

    @staticmethod
    async def _evaluate(frame: Frame, expression: str) -> None:
        try:
            await frame.evaluate(expression, force_expr=True)
        except Exception:
            LOGGER.error(
                f"Error evaluating expression in frame: {expression}",
                exc_info=True,
            )

    @staticmethod
    def _stash_response(
        all_responses: dict[str, Response],
        request: Request,
    ) -> None:
        responses = all_responses.get(request.url, [])
        if request.response:
            responses.append(request.response)
        all_responses[request.url] = responses

    @staticmethod
    def _convert_print_param(
        parameter: None | int | float | str
    ) -> float | None:
        # Convert print parameter to inches.
        unit_to_pixels = {'px': 1, 'in': 96, 'cm': 37.8, 'mm': 3.78}
        if parameter is None:
            return None
        if isinstance(parameter, (int, float)):
            pixels = parameter
        elif isinstance(parameter, str):
            text = parameter
            unit = text[-2:].lower()
            if unit in unit_to_pixels:
                value_text = text[:-2]
            else:
                unit = 'px'
                value_text = text
            try:
                value = float(value_text)
            except ValueError:
                raise ValueError(f'Failed to parse parameter value: {text}')
            pixels = value * unit_to_pixels[unit]
        else:
            raise TypeError(f'Cannot accept type: {str(type(parameter))}')
        return pixels / 96

    @property
    def target(self) -> Target:
        """Parent `mokr.browser.Target` this `Page` was spawned from."""
        return self._target

    @property
    def browser(self) -> Browser:
        """Parent `mokr.browser.Browser` this `Page` belongs to."""
        return self._target.browser

    @property
    def main_frame(self) -> Frame | None:
        """This `Page`'s `mokr.frame.FrameManager`'s main `mokr.frame.Frame`."""
        return self._frame_manager._main_frame

    @property
    def network_manager(self) -> NetworkManager | None:
        """This `Page`'s `mokr.network.NetworkManager`."""
        return self._network_manager

    @property
    def fetch_domain(self) -> FetchDomain:
        """This `Page`'s `mokr.fetch.FetchDomain`."""
        return self._fetch_domain

    @property
    def http_domain(self) -> HttpDomain:
        """This `Page`'s `mokr.network.HttpDomain`."""
        if not self._http_domain:
            self.make_http_domain()
        return self._http_domain

    @property
    def keyboard(self) -> Keyboard:
        """This `Page`'s `mokr.input.Keyboard`."""
        return self._keyboard

    @property
    def mouse(self) -> Mouse:
        """This `Page`'s `mokr.input.Mouse`."""
        return self._mouse

    @property
    def touchscreen(self) -> Touchscreen:
        """This `Page`'s `mokr.input.Touchscreen`."""
        return self._touchscreen

    @property
    def frames(self) -> list[Frame]:
        """List of all `mokr.frame.Frames` within this `Page`."""
        return list(self._frame_manager.frames())

    @property
    def workers(self) -> list[WebWorker]:
        """List of all `mokr.browser.WebWorker`s within this `Page`."""
        return list(self._workers.values())

    @property
    def url(self) -> str:
        """The URL the `Page` is currently at."""
        frame = self._ensure_frame()
        return frame.url

    @property
    def viewport(self) -> dict | None:
        """Current viewport configuration, if any."""
        return self._viewport

    @property
    def user_agent(self) -> str | None:
        """The user agent given to override on all requests, if any."""
        return self._user_agent

    @property
    def is_closed(self) -> bool:
        """
        True if the `Page` is still alive, otherwise False.
        If a parent `mokr.browser.BrowserContext` is closed, all child `Page`s
        will close, too.
        """
        return self._closed

    @property
    def browser_type(self) -> str:
        """One of "chrome" or "firefox"."""
        return self._browser.kind

    def _is_firefox(self, mute: bool = False, caller: Any = None) -> bool:
        if not self.browser_type == "firefox":
            return False
        elif mute:
            return True
        else:
            name = inspect.currentframe().f_back.f_code.co_name
            if caller:
                name = f"{caller.__class__.__name__}.{name}"
            raise FirefoxNotImplementedError(
                f"Firefox doesn't support functionality to use method {name}."
            )

    def _set_closed(self, *args) -> None:
        self.emit(CLOSE)
        self._closed = True

    def _on_target_attached(self, event: dict) -> None:
        target_info = event['targetInfo']
        if target_info['type'] != 'worker':
            # If we don't detach from service workers, they will never die.
            try:
                self._client.send(
                    TARGET_SEND_DETACH,
                    {'sessionId': event['sessionId']},
                )
            except Exception:
                LOGGER.info("Error detaching worker.", exc_info=True)
            return
        session_id = event['sessionId']
        session = self._client._create_session(target_info['type'], session_id)
        worker = WebWorker(
            session,
            target_info['url'],
            self._add_console_message,
            self._handle_exception,
        )
        self._workers[session_id] = worker
        self.emit(WORKER_CREATED, worker)

    def _on_target_detached(self, event: dict) -> None:
        session_id = event['sessionId']
        worker = self._workers.get(session_id)
        if worker is None:
            return
        self.emit(WORKER_DESTROYED, worker)
        self._workers.pop(session_id)

    def _on_target_crashed(self, *args: Any, **kwargs: Any) -> None:
        self.emit(ERROR, PageError('Page crashed!'))

    def _on_log_entry_added(self, event: dict) -> None:
        entry = event.get('entry', {})
        level = entry.get('level', '')
        text = entry.get('text', '')
        args = entry.get('args', [])
        source = entry.get('source', '')
        for arg in args:
            release_remote_object(self._client, arg)
        if source != 'worker':
            self.emit(PAGE_CONSOLE, ConsoleMessage(level, text))

    def _ensure_frame(self) -> Frame:
        frame = self.main_frame
        if not frame:
            raise PageError('Page has no main frame.')
        return frame

    def _emit_metrics(self, event: dict) -> None:
        self.emit(
            METRICS,
            {
                'title': event['title'],
                'metrics': self._build_metrics(event.get("metrics", [])),
            }
        )

    def _build_metrics(self, metrics: list) -> dict[str, Any]:
        supported_metrics = (
            'Timestamp',
            'Documents',
            'Frames',
            'JSEventListeners',
            'Nodes',
            'LayoutCount',
            'RecalcStyleCount',
            'LayoutDuration',
            'RecalcStyleDuration',
            'ScriptDuration',
            'TaskDuration',
            'JSHeapUsedSize',
            'JSHeapTotalSize',
        )
        result = {}
        for metric in metrics:
            if metric['name'] in supported_metrics:
                result[metric['name']] = metric['value']
        return result

    def _handle_exception(self, exceptionDetails: dict) -> None:
        message = format_javascript_exception(exceptionDetails)
        self.emit(PAGE_ERROR, PageError(message))

    def _on_console_api(self, event: dict) -> None:
        context = self._frame_manager.execution_context_by_id(
            event['executionContextId']
        )
        values = []
        for arg in event.get('args', []):
            values.append(
                self._frame_manager.create_javascript_handle(context, arg)
            )
        self._add_console_message(event['type'], values)

    def _on_binding_called(self, event: dict) -> None:
        obj = json.loads(event['payload'])
        name = obj['name']
        seq = obj['seq']
        args = obj['args']
        result = self._page_bindings[name](*args)
        expression = self._make_javascript_function_string(
            METHOD_DELIVER_BINDING_RESULT,
            name,
            seq,
            result,
        )
        try:
            self._client.send(
                RUNTIME_EVALUATE,
                {
                    'expression': expression,
                    'context_id': event['executionContextId'],
                },
            )
        except Exception:
            LOGGER.error(
                f"Error evaluating expression: {expression}",
                exc_info=True,
            )

    def _add_console_message(
        self,
        type: str,
        args: list[JavascriptHandle],
    ) -> None:
        if not self.listeners(PAGE_CONSOLE):
            for arg in args:
                self._client._loop.create_task(arg.dispose())
            return
        text_tokens = []
        for arg in args:
            remote_object = arg._remote_object
            if remote_object.get('objectId'):
                text_tokens.append(arg.to_string())
            else:
                text_tokens.append(str(serialize_remote_object(remote_object)))
        message = ConsoleMessage(type, ' '.join(text_tokens), args)
        self.emit(PAGE_CONSOLE, message)

    def _on_dialog(self, event: Any) -> None:
        _type = event.get('type')
        if _type == 'alert':
            dialog_type = _type
        elif _type == 'confirm':
            dialog_type = _type
        elif _type == 'prompt':
            dialog_type = _type
        elif _type == 'beforeunload':
            dialog_type = _type
        else:
            dialog_type = ''
        if self._is_firefox(mute=True):
            dialog = event
        else:
            dialog = Dialog(
                self._client,
                dialog_type,
                event.get('message'),
                event.get('defaultPrompt'),
            )
        self.emit(PAGE_DIALOG, dialog)

    async def _default_request_intercept(self, request: Request) -> None:
        # Default interception is to just not block the request.
        if not self._is_firefox(mute=True):
            return await request.release()

    async def _navigate(self, url: str, referrer: str) -> str | None:
        response = await self._client.send(
            PAGE_NAVIGATE,
            {'url': url, 'referrer': referrer},
        )
        if response.get('errorText'):
            return f'{response["errorText"]} at {url}'
        return None

    async def _screenshot_task(
        self,
        file_type: Literal["png", "jpeg"] | None,
        file_path: str | None,
        jpeg_quality: int | None,
        full_page: bool,
        clip: dict[str, int] | None,
        omit_background: bool,
        encoding: Literal["binary", "base64"],
        scale: int,
    ) -> bytes:
        await self._client.send(
            TARGET_ACTIVATE,
            {'targetId': self._target._targetId},
        )
        if clip:
            clip['scale'] = 1
        if full_page:
            metrics = await self._client.send(PAGE_GET_LAYOUT)
            width = math.ceil(metrics['contentSize']['width'])
            height = math.ceil(metrics['contentSize']['height'])
            # Overwrite clip for full page.
            clip = dict(x=0, y=0, width=width, height=height, scale=1)
            if self._viewport is not None:
                mobile = self._viewport.get('isMobile', False)
                device_scale_factor = self._viewport.get(
                    'deviceScaleFactor',
                    scale,
                )
                landscape = self._viewport.get('isLandscape', False)
            else:
                mobile = False
                device_scale_factor = scale
                landscape = False
            if landscape:
                screen_orientation = dict(angle=90, type='landscapePrimary')
            else:
                screen_orientation = dict(angle=0, type='portraitPrimary')
            await self._client.send(
                EMULATION_OVERRIDE_METRICS,
                {
                    'mobile': mobile,
                    'width': width,
                    'height': height,
                    'deviceScaleFactor': device_scale_factor,
                    'screenOrientation': screen_orientation,
                },
            )
        if omit_background and not self._is_firefox(mute=True):
            await self._client.send(
                EMULATION_OVERRIDE_BACKGROUND,
                {'color': {'r': 0, 'g': 0, 'b': 0, 'a': 0}},
            )
        opt = {'format': file_type}
        if clip:
            opt['clip'] = clip
        if file_type == 'jpeg' and jpeg_quality is not None:
            opt['quality'] = jpeg_quality
        # Send the screenshot request with the given parameters.
        response = await self._client.send(PAGE_SCREENSHOT, opt)
        # Restore any overrides.
        if omit_background and not self._is_firefox(mute=True):
            await self._client.send(EMULATION_OVERRIDE_BACKGROUND)
        if full_page and self._viewport is not None:
            await self.set_viewport(self._viewport)
        # Encode and write file, if requested.
        if encoding == 'base64':
            buffer = response.get('data', b'')
        else:
            buffer = base64.b64decode(response.get('data', b''))
        if file_path:
            with open(file_path, 'wb') as f:
                f.write(buffer)
        return buffer

    async def _navigate_history(
        self,
        delta: int,
        timeout: int | None = None,
        wait_until: list[LIFECYCLE_EVENTS] | LIFECYCLE_EVENTS = "load",
    ) -> Response | None:
        history = await self._client.send(PAGE_GET_NAVIGATION_HISTORY)
        _count = history.get('currentIndex', 0) + delta
        entries = history.get('entries', [])
        if len(entries) <= _count:
            return None
        entry = entries.get(_count, {})
        response = (
            await asyncio.gather(
                self.wait_for_navigation(timeout, wait_until),
                self._client.send(
                    PAGE_NAVIGATE_TO_HISTORY_ENTRY,
                    {'entryId': entry.get('id')}
                ),
            )
        )[0]
        return response

    def on(self, event: str, method: Callable | None) -> None:
        """
        Registers the callable `method` to the event name `event`, if provided.
        When the target `event` is emitted by this class, the target `method`
        will be called.

        Notably, the event "request" does not register a listener. Instead, it
        adds the method to this `Page`'s `mokr.network.NetworkManager`'s
        request interception callback chain, which is already registered
        as a listener on "request" events, if interception is enabled.

        This callback chain allows multiple manipulations of requests, until the
        intercepted `mokr.network.Request` is `Request.released`, `.aborted`, or
        `.fulfilled`. For request interception, methods are executed in reverse
        order of registration, so newer `Page.on` methods will run first.

        Args:
            event (str): Event name to listen for.
            method (Callable | None): Method to call when event is emitted.

        Example::

            # Printing worker URL on creation, standard functionality.
            page.on("workercreated", lambda worker: print(worker.url))

            # Adding a handler to the request interception chain.
            async def intercept(request: Request) -> Request | None:
                if request.url.endswith("png"):
                    # Request will be killed, interception chain stopped here.
                    await request.abort()
                elif request.url.endswith("jpg"):
                    # Request will continue in the interception chain.
                    return request
                else:
                    # Request will be finished, interception chain stopped here.
                    await request.release()
            # Handlers can be synchronous, too.
            def note_url(request: Request) -> Request:
                print(request.url)
                return request
            page.on("request", note_url)
            page.on("request", intercept)
        """
        # Request interception may act strangely with stylesheet requests.
        if event == "request":
            if method in self._interception_callback_chain:
                self._interception_callback_chain.remove(method)
            self._interception_callback_chain.insert(0, method)
        else:
            _network_manager_on = False
            network_mgr_events = {
                NETWORK_RESPONSE: NETWORK_MGR_RESPONSE,
                NETWORK_REQUEST_FINISHED: NETWORK_MGR_REQUEST_FINISHED,
            }
            if event in network_mgr_events.keys():
                event = network_mgr_events.get(event)
                _network_manager_on = True
            if inspect.iscoroutinefunction(method):
                callback = lambda *args, **kwargs: asyncio.ensure_future(
                    method(*args, **kwargs)
                )
            else:
                callback = method
            _cls = self._network_manager if _network_manager_on else super()
            _cls.on(event, callback)

    def make_http_domain(
        self,
        sync_cookies: Literal["both", "http", "page", "none"] = "both",
        **httpx_client_kwargs,
    ) -> None:
        """
        Create a `mokr.network.HttpDomain` bound to this page.

        This method does not ever need to be called directly; accessing
        `Page.http_domain` will create a new domain with default values. This
        exists so any optional arguments could be passed to the constructor.

        Optionally set the cookie sync behaviour by setting `sync_cookies` to:
        - "both" (default): Sync back and forth.
        - "http": Sync to the `HttpDomain` from the `Page` only.
        - "page": Sync to the `Page` from the `HttpDomain` only.
        - "none": Don't sync at all.

        Args:
            sync_cookies (Literal["both", "http", "page", "none"], optional):
                Whether to sync cookies between the `HttpDomain` and the parent
                `Page` before/after each request and response.
                Defaults to "both".
        """
        self._http_domain = HttpDomain(
            self,
            sync_cookies,
            **httpx_client_kwargs,
        )

    async def set_request_interception_enabled(self, choice: bool) -> None:
        """
        Disable or enabled request interception (enabled by default).
        See `Page.on` for details on using the request interception
        callback chain.

        Args:
            choice (bool): False to disable, True to enable.
        """
        await self._network_manager.set_request_interception(choice)

    async def tap(self, selector: str) -> None:
        """
        Tap the first element that matches `selector`.
        Wrapper for `Page.main_frame.tap`.

        This method is a shortcut for running `Page.query_selector` and then
        running `mokr.execution.ElementHandle.tap` on the resultant
        ElementHandle. In either case, an element will be scrolled into view
        if needed, and the center of it clicked with the ElementHandle's
        bound `Page.touchscreen`.

        Args:
            selector (str): Selector to query element by.

        Raises:
            PageError: Raised if no element is found with given `selector`.
        """
        self._is_firefox(caller=self)
        frame = self._ensure_frame()
        await frame.tap(selector)

    async def set_offline_mode(self, choice: bool) -> None:
        """
        Enable or diable offline mode. Disabled by default.
        Wrapper for `Page.network_manager.set_offline_mode`.

        Args:
            enabled (bool): False to disable, True to enable.
        """
        await self._network_manager.set_offline_mode(choice)

    def set_default_navigation_timeout(self, timeout: int) -> None:
        """
        Change the default navigation timeout. This is used by `Page.goto`,
        `Page.go_back`, `Page.go_forward`, `Page.wait_for_navigation`,
        `Page.refresh`, and `Page.fetch`, unless overridden.

        Args:
            timeout (int): Milliseconds to wait. Use 0 for infinite.
        """
        self._default_navigation_timeout = timeout

    async def evaluate_handle(
        self,
        page_function: str,
        *args: Any,
    ) -> JavascriptHandle:
        """
        Execute a JavaScript function with given arguments.
        Runs this `Page`'s default `mokr.frame.Frame.evaluate_handle`.

        Args:
            page_function (str): JavaScript function to run.

        Raises:
            PageError: Raised if the `Page`'s main `mokr.frame.Frame` fails to
                find its `mokr.browser.ExecutionContext`.

        Returns:
            JavascriptHandle: `mokr.execution.JavascriptHandle`.
        """
        frame = self._ensure_frame()
        context = await frame.execution_context()
        if not context:
            raise PageError('No context attached to frame.')
        return await context.evaluate_handle(page_function, *args)

    async def query_objects(
        self,
        javascript_handle: JavascriptHandle,
    ) -> JavascriptHandle:
        """
        Query all objects with the given `mokr.execution.JavascriptHandle`'s
        `get_property("objectId")`.
        Wrapper for this `Page.main_frame`'s
        `mokr.execution.ExecutionContext.query_objects`.

        Args:
            javascript_handle (JavascriptHandle): A valid (not disposed)
                `mokr.execution.JavascriptHandle` object.

        Raises:
            PageError: Raised if the `Page`'s main `mokr.frame.Frame` fails to
                find its `mokr.browser.ExecutionContext`.
            ElementHandleError: Raised if the given handle is disposed, or
                does not have an "objectId" remote property (primitive type).

        Returns:
            JavascriptHandle: A `mokr.execution.JavascriptHandle` initialised
                from the remot response.
        """
        self._is_firefox(caller=self)
        frame = self._ensure_frame()
        context = await frame.execution_context()
        if not context:
            raise PageError('No context attached to frame.')
        return await context.query_objects(javascript_handle)

    async def query_selector(self, selector: str) -> ElementHandle | None:
        """
        Return the first element in the DOM that matches the selector, if any.
        Wrapper for `Page.main_frame.query_selector`.

        Args:
            selector (str): Element selector to locate.

        Returns:
            ElementHandle | None: ElementHandle if found or None.
        """
        frame = self._ensure_frame()
        return await frame.query_selector(selector)

    async def query_selector_all(self, selector: str) -> list[ElementHandle]:
        """
        Return all elements in the DOM that match the selector, if any.
        Wrapper for `Page.main_frame.query_selector_all`.

        Args:
            selector (str): Element selector to locate.

        Returns:
            list[ElementHandle]: List of ElementHandle if any or empty list.
        """
        frame = self._ensure_frame()
        return await frame.query_selector_all(selector)

    async def xpath(self, expression: str) -> list[ElementHandle]:
        """
        Return all elements in the DOM that match the expression, if any.
        Wrapper for `Page.main_frame.xpath`.

        Args:
            expression (str): XPath expression to evaluate.

        Returns:
            list[ElementHandle]: List of ElementHandle if any or empty list.
        """
        frame = self._ensure_frame()
        return await frame.xpath(expression)

    async def cookies(self) -> list[dict[str, str | int | bool]]:
        """
        Get all cookies accessible to the browser.

        Returns:
            list[dict[str, str | int | bool]]: List of dictionaries representing
                each cookie.
        """
        response = await self._client.send(NETWORK_GET_ALL_COOKIES)
        return response.get('cookies', [])

    async def get_cookies_by_urls(
        self,
        urls: list[str] | None = None,
    ) -> list[dict[str, str | int | bool]]:
        """
        Get cookies for the given URLs. If no URLs are given, defaults to a
        list containing the URLs of the page and all of its frames.

        Args:
            urls (list[str] | None): List of URLs to get cookies for.
                Defaults to None.

        Returns:
            list[dict[str, str | int | bool]]: List of dictionaries representing
                each cookie.
        """
        params = {}
        if urls:
            urls = params["urls"] = tuple(urls)
        response = await self._client.send(NETWORK_GET_COOKIES, params)
        return response.get('cookies', [])

    async def delete_cookies(self, cookies: list[dict]) -> None:
        """
        Delete a cookie from this `Page`.

        Args:
            cookies (list[dict]): A list of dictionaries representing a cookie
                entry. Each dictionary must at minimum contain a "name".
        """
        for cookie in cookies:
            await self._client.send(NETWORK_DELETE_COOKIES, cookie)

    async def set_cookies(self, cookies: list[dict]) -> None:
        """
        Set a cookie on this `Page`.

        Args:
            cookies (list[dict]): A list of dictionaries representing a cookie
                entry. Each dictionary must at minimum contain a "name" and
                a "value".

        Raises:
            PageError: Raised if the current page is blank ("about:blank") or
                is a data URL (starts with "data:").
        """
        items = []
        for cookie in cookies:
            item = cookie.copy()
            if item.get('url') == 'about:blank':
                name = item.get('name', '')
                raise PageError(f'Blank page can not have cookie "{name}"')
            if item.get('url', '').startswith('data:'):
                name = item.get('name', '')
                raise PageError(f'Data URL page can not have cookie "{name}"')
            items.append(item)
        await self.delete_cookies(items)
        if items:
            await self._client.send(NETWORK_SET_COOKIES, {'cookies': items})

    async def embed_javascript(
        self,
        file_content: str = None,
        file_path: str = None,
        url: str = None,
        script_type: str = None,
    ) -> ElementHandle:
        """
        Add script tag to this `Page.main_frame`.
        Wrapper for `Page.main_frame.embed_javascript`.

        Args:
            file_content (str, optional): Encoded file content for script to
                embed. If not given, must give `file_path` or `url`. Defaults
                to None.
            file_path (str, optional): File path for script to embed.
                If not given, must give `file_content` or `url`. Defaults to
                None.
            url (str, optional): URL for script to embed. If not given, must
                give `file_content` or `file_path`. Defaults to None.
            script_type (str, optional): Use "module" to load as JavaScript
                ES6 module, if not given, defaults to "text/javascript".
                Defaults to None.

        Raises:
            ValueError: Raised if none of `file_content`, `file_path`, or
                `url` are given.
            PageError: Raised if error occurs sending embed request to remote
                connection (from ElementHandleError).

        Returns:
            ElementHandle: Newly embedded element.
        """
        frame = self._ensure_frame()
        return await frame.embed_javascript(
            file_content,
            file_path,
            url,
            script_type,
        )

    async def embed_style(
        self,
        file_content: str = None,
        file_path: str = None,
        url: str = None,
    ) -> ElementHandle:
        """
        Add style tag to this `Page.main_frame`.
        Wrapper for `Page.main_frame.embed_style`.

        Args:
            file_content (str, optional): Encoded file content for style to
                embed. If not given, must give `file_path` or `url`. Defaults
                to None.
            file_path (str, optional): File path for style to embed.
                If not given, must give `file_content` or `url`. Defaults to
                None.
            url (str, optional): URL for style to embed. If not given, must
                give `file_content` or `file_path`. Defaults to None.

        Raises:
            ValueError: Raised if none of `file_content`, `file_path`, or
                `url` are given.
            PageError: Raised if error occurs sending embed request to remote
                connection (from ElementHandleError).

        Returns:
            ElementHandle: Newly embedded element.
        """
        frame = self._ensure_frame()
        return await frame.embed_style(file_content, file_path, url)

    async def expose_function(
        self,
        name: str,
        method: Callable
    ) -> None:
        """
        Bind a remote JavaScript function "name" to local `method`. This will
        allow triggering local `method` by calling `window["name"]()` in the
        browser.

        Args:
            name (str): Remote JavaScript function name.
            method (Callable): Local callable to bind to.

        Raises:
            PageError: Raised if a function exists already with given "name".
        """
        self._is_firefox(caller=self)
        if self._page_bindings.get(name):
            raise PageError(
                f'Failed to add page binding with name {name}:'
                f' window["{name}"] already exists.'
            )
        self._page_bindings[name] = method
        expression = self._make_javascript_function_string(
            METHOD_ADD_PAGE_BINDING,
            name,
        )
        await self._client.send(RUNTIME_ADD_BINDING, {'name': name})
        await self._client.send(PAGE_ADD_SCRIPT_TO_EVAL, {'source': expression})
        loop = asyncio.get_event_loop()
        await asyncio.wait(
            [
                loop.create_task(self._evaluate(frame, expression))
                for frame in self.frames
            ]
        )

    async def set_credentials(
        self,
        credentials: dict[Literal["username", "password"], str],
    ) -> None:
        """
        Set the credentials to use for HTTP authentication.
        Wrapper for `Page.network_manager.set_credentials`.

        Args:
            credentials (dict[str, str]): A dictionary with credentials,
                keyed as "username" and "password".
        """
        self._is_firefox(caller=self)
        credentials = credentials.copy()
        if credentials.copy().get("proxy"):
            credentials.pop("proxy")
        if credentials:
            return await self._network_manager.set_credentials(credentials)

    async def set_extra_http_headers(self, headers: dict[str, str]) -> None:
        """
        Set extra headers to be sent with every request.
        Wrapper for `Page.network_manager.set_extra_http_headers`.

        Args:
            extra_http_headers (dict[str, str]): A dictionary of headers.

        Raises:
            ValueError: Raised if any header value is not string.
        """
        return await self._network_manager.set_extra_http_headers(headers)

    async def set_user_agent(
        self,
        user_agent: str,
        user_agent_metadata: str | None = None,
    ) -> None:
        """
        Update the user agent to be sent with every request.
        Wrapper for `Page.network_manager.set_user_agent`.

        Args:
            user_agent (str): User agent string.
            user_agent_metadata (str | None, optional): Experimental, used to
                specify user agent client hints to emulate.
        """
        return await self._network_manager.set_user_agent(
            user_agent,
            user_agent_metadata,
        )

    async def metrics(self) -> dict[str, Any]:
        """
        Return dictionary with current values of runtime metrics.

        Returns:
            dict[str, Any]: Runtime metrics as dictionary.
        """
        self._is_firefox(caller=self)
        response = await self._client.send(PERFORMANCE_GET_METRICS)
        return self._build_metrics(response.get("metrics", []))

    async def content(self) -> str:
        """
        Get encoded string representation of HTML in this `Page.main_frame`.
        Wrapper for `Page.main_frame.content`.

        Returns:
            str: HTML content.
        """
        frame = self._ensure_frame()
        return await frame.content()

    async def set_content(self, html: str) -> None:
        """
        Set the value of the HTML on this `Page.main_frame`.
        Wrapper for `Page.main_frame.set_content`.

        This does not change the value of the "document" request's response,
        it only changes what is shown in the window.

        Response values can be changed by intercepting requests or responses,
        see `Page.on` for more.

        Args:
            html (str): HTML content to set to.
        """
        frame = self._ensure_frame()
        await frame.set_content(html)

    async def goto(
        self,
        url: str,
        timeout: int | None = None,
        wait_until: list[LIFECYCLE_EVENTS] | LIFECYCLE_EVENTS = "load",
    ) -> Response | None:
        """
        Navigate to the given `url`.

        Args:
            url (str): URL to navigate to. Should be fully-qualified, starting
                with "https://" or "http://" (allowed if `ignore_https_errors`).
            timeout (int | None, optional): Time in milliseconds to wait for
                `wait_until` event. Defaults to None.
            wait_until (list[LIFECYCLE_EVENTS] | LIFECYCLE_EVENTS, optional):
                Event(s) to wait for, can be one or some combination of
                "load", "domcontentloaded", "networkidle", and
                "networkalmostidle". Defaults to "load".

        Raises:
            PageError: Raised if error encountered during navigation.
            MokrTimeoutError: Raised if timeout exceeded before all expected
                `wait_until` events are recieved.

        Returns:
            Response | None: Last response recieved after all redirects, if any.
        """
        main_frame = self._ensure_frame()
        referrer = self._network_manager.extra_http_headers.get('referer', '')
        all_responses = {}
        event_listeners = [
            add_event_listener(
                self._network_manager,
                NETWORK_MGR_REQUEST_FINISHED,
                lambda response: self._stash_response(all_responses, response),
            )
        ]
        _timeout = timeout if timeout else self._default_navigation_timeout
        watcher = NavigationWaiter(
            self._frame_manager,
            main_frame,
            _timeout,
            wait_until,
        )
        result = await self._navigate(url, referrer)
        if result is not None:
            raise PageError(result)
        result = await watcher.navigation_promise()
        watcher.cancel()
        remove_event_listeners(event_listeners)
        error = result[0].pop().exception()
        if error:
            raise error
        responses = all_responses.get(main_frame._navigation_url, [])
        return responses[-1] if responses else None

    async def go_back(
        self,
        timeout: int | None = None,
        wait_until: list[LIFECYCLE_EVENTS] | LIFECYCLE_EVENTS = "load",
    ) -> Response | None:
        """
        Navigate back in history.

        Args:
            timeout (int | None, optional): Time in milliseconds to wait for
                `wait_until` event. Defaults to None.
            wait_until (list[LIFECYCLE_EVENTS] | LIFECYCLE_EVENTS, optional):
                Event(s) to wait for, can be one or some combination of
                "load", "domcontentloaded", "networkidle", and
                "networkalmostidle". Defaults to "load".

        Returns:
            Response | None: History `mokr.network.Response`, if any.
        """
        return await self._navigate_history(-1, timeout, wait_until)

    async def go_forward(
        self,
        timeout: int | None = None,
        wait_until: list[LIFECYCLE_EVENTS] | LIFECYCLE_EVENTS = "load",
    ) -> Response | None:
        """
        Navigate next in history.

        Args:
            timeout (int | None, optional): Time in milliseconds to wait for
                `wait_until` event. Defaults to None.
            wait_until (list[LIFECYCLE_EVENTS] | LIFECYCLE_EVENTS, optional):
                Event(s) to wait for, can be one or some combination of
                "load", "domcontentloaded", "networkidle", and
                "networkalmostidle". Defaults to "load".

        Returns:
            Response | None: History `mokr.network.Response`, if any.
        """
        return await self._navigate_history(1, timeout, wait_until)

    async def refresh(
        self,
        timeout: int | None = None,
        wait_until: list[LIFECYCLE_EVENTS] | LIFECYCLE_EVENTS = "load",
    ) -> Response | None:
        """
        Refresh (reload) the current page.

        Args:
            timeout (int | None, optional): Time in milliseconds to wait for
                `wait_until` event. Defaults to None.
            wait_until (list[LIFECYCLE_EVENTS] | LIFECYCLE_EVENTS, optional):
                Event(s) to wait for, can be one or some combination of
                "load", "domcontentloaded", "networkidle", and
                "networkalmostidle". Defaults to "load".

        Raises:
            MokrTimeoutError: Raised if timeout exceeded before all expected
                `wait_until` events are recieved.

        Returns:
            Response | None: Last response recieved after all redirects, if any.
        """
        response = (
            await asyncio.gather(
                self.wait_for_navigation(timeout, wait_until),
                self._client.send(PAGE_RELOAD),
            )
        )[0]
        return response

    async def wait_for_navigation(
        self,
        timeout: int | None = None,
        wait_until: list[LIFECYCLE_EVENTS] | LIFECYCLE_EVENTS = "load",
    ) -> Response | None:
        """
        Wait for navigation to occur. Navigation is triggered by `Page.goto`,
        `Page.refresh`, redirects, and history (`Page.go_back` and
        `Page.go_forward`).

        Note that anchor navigation will not and history navigation may not
        yield any `mokr.network.Response` objects.

        Args:
            timeout (int | None, optional): Time in milliseconds to wait for
                `wait_until` event. Defaults to None.
            wait_until (list[LIFECYCLE_EVENTS] | LIFECYCLE_EVENTS, optional):
                Event(s) to wait for, can be one or some combination of
                "load", "domcontentloaded", "networkidle", and
                "networkalmostidle". Defaults to "load".

        Raises:
            MokrTimeoutError: Raised if timeout exceeded before all expected
                `wait_until` events are recieved.

        Returns:
            Response | None: Last response recieved after all redirects, if any.
        """
        main_frame = self._ensure_frame()
        _timeout = timeout if timeout else self._default_navigation_timeout
        watcher = NavigationWaiter(
            self._frame_manager,
            main_frame,
            _timeout,
            wait_until,
        )
        all_responses = {}
        listener = add_event_listener(
            self._network_manager,
            NETWORK_MGR_REQUEST_FINISHED,
            lambda response: self._stash_response(all_responses, response),
        )
        result = await watcher.navigation_promise()
        remove_event_listeners([listener])
        error = result[0].pop().exception()
        if error:
            raise error
        responses = all_responses.get(main_frame._navigation_url, [])
        return responses[-1] if responses else None

    async def wait_for_request(
        self,
        url: str | None = None,
        method: Callable | None = None,
        timeout: int | None = 30000,
    ) -> Request:
        """
        Wait for a `mokr.network.Request` whose `url` matches the `url` or
        that evaluates to True when passed to `method`.

        Args:
            url (str | None, optional): URL to wait. Defaults to None.
            method (Callable | None, optional): Callable to pass
                `mokr.network.Request`s emitted by `Page.network_manager` to.
                Defaults to None.
            timeout (int | None, optional): Time in milliseconds to wait.
                Defaults to 30000.

        Raises:
            ValueError: Raised if neither `url` nor `method` given.

        Returns:
            Request: First matching `mokr.network.Request`.
        """
        if url:
            callback = lambda request: url == request.url
        elif method:
            callback = lambda request: bool(method(request))
        else:
            raise ValueError("Must provide url or method.")
        waiter = EventWaiter(
            self._network_manager,
            NETWORK_MGR_REQUEST,
            callback,
            timeout,
            self._client._loop,
        )
        return await waiter.wait()

    async def wait_for_response(
        self,
        url: str | None = None,
        method: Callable | None = None,
        timeout: int | None = 30000,
    ) -> Response:
        """
        Wait for a `mokr.network.Response` whose `url` matches the `url` or
        that evaluates to True when passed to `method`.

        Args:
            url (str | None, optional): URL to wait. Defaults to None.
            method (Callable | None, optional): Callable to pass
                `mokr.network.Response`s emitted by `Page.network_manager` to.
                Defaults to None.
            timeout (int | None, optional): Time in milliseconds to wait.
                Defaults to 30000.

        Raises:
            ValueError: Raised if neither `url` nor `method` given.

        Returns:
            Request: First matching `mokr.network.Response`.
        """
        if url:
            callback = lambda response: url == response.url
        elif method:
            callback = lambda response: bool(method(response))
        else:
            raise ValueError("Must provide url or method.")
        waiter = EventWaiter(
            self._network_manager,
            NETWORK_MGR_RESPONSE,
            callback,
            timeout,
            self._client._loop,
        )
        return await waiter.wait()

    async def bring_to_front(self) -> None:
        """Bring this `Page` to front (activate tab)."""
        await self._client.send(PAGE_BRING_TO_FRONT)

    async def set_javascript_enabled(self, choice: bool) -> None:
        """
        Enable or disable JavaScript on this `Page`.

        Args:
            choice (bool): True to enable, False to disable.
        """
        self._is_firefox(caller=self)
        if self._javascript_enabled == choice:
            return
        self._javascript_enabled = choice
        await self._client.send(
            EMULATION_DISABLE_SCRIPT_EXECUTION,
            {'value': not choice}
        )

    async def set_bypass_csp(self, choice: bool) -> None:
        """
        Enable or disable the target page's Content Security Policy.

        Note this should be called before navigation to the domain as this
        happens at CSP initialization.

        Args:
            choice (bool): True to enable, False to disable.
        """
        self._is_firefox(caller=self)
        await self._client.send(PAGE_SET_BYPASS_CSP, {'enabled': choice})

    async def emulate_media(
        self,
        media_type: Literal["screen", "print"] | None = None,
    ) -> None:
        """
        Emulate CSS media type on target page.

        Args:
            media_type (Literal["screen", "print"] | None, optional):
                Media type to emulate; one of "screen", "print", or None.
                Defaults to None.

        Raises:
            ValueError: _description_
        """
        self._is_firefox(caller=self)
        if media_type not in ['screen', 'print', None, '']:
            raise ValueError(f'Unsupported media type: {media_type}')
        await self._client.send(
            EMULATION_SET_EMULATED_MEDIA,
            {'media': media_type or ''},
        )

    async def set_viewport(self, viewport: dict) -> None:
        """
        Run viewport adjustments based off given `viewport` parameters.
        Not all viewport options are considered, only: "isMobile", "width",
        "height", "deviceScaleFactor", "isLandscape", and "hasTouch".

        Args:
            viewport (dict[str, bool  |  int]): The parameters to adjust
                the viewport to.
        """
        needs_reload = await self._viewport_manager.emulate_viewport(viewport)
        self._viewport = viewport
        if needs_reload:
            await self.reload()

    async def evaluate(
        self,
        page_function: str,
        *args: Any,
        force_expr: bool = False,
    ) -> dict | None:
        """
        Execute a JavaScript function with given arguments.
        Runs this `Page`'s default `mokr.frame.Frame.evaluate`.

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
        frame = self._ensure_frame()
        return await frame.evaluate(page_function, *args, force_expr=force_expr)

    async def evaluate_on_new_document(
        self,
        page_function: str,
        *args: str,
    ) -> None:
        """
        Attach a function that will be evaluated on every new document.
        This occurs when a page or frame is navigated or attached.

        Args:
            page_function (str): JavaScript function to attach.
        """
        source = self._make_javascript_function_string(page_function, *args)
        await self._client.send(PAGE_ADD_SCRIPT_TO_EVAL, {'source': source})

    async def set_request_cache(self, choice: bool = True) -> None:
        """
        Enable or disable request caching. Request caching caches requests in
        the browser, not `mokr.network.Request` objects.

        Does not check if request caching was enabled already by
        `Page.network_manager`.

        Args:
            enabled (bool, optional): True to enable, False to disable.
                Defaults to True.
        """
        await self._client.send(
            NETWORK_CACHE_DISABLE,
            {'cacheDisabled': not choice},
        )

    async def screenshot(
        self,
        file_type: Literal["png", "jpeg"] | None = None,
        file_path: str | None = None,
        jpeg_quality: int | None = None,
        full_page: bool = False,
        clip: dict[str, int] | None = None,
        omit_background: bool = False,
        encoding: Literal["binary", "base64"] = "binary",
        scale: int | float = 1,
    ) -> bytes:
        """
        Take a screenshot of the page viewport.

        Args:
            file_type (Literal["png", "jpeg"] | None, optional): File type
                to save the image as. Defaults to "png" if None.
            file_path (str | None, optional): Path to save image to. If given
                without `file_type`,  the type will be inferred.
                Defaults to None.
            jpeg_quality (int | None, optional): JPEG quality, 0-100 (only
                applicable if type is or is inferred to be JPEG.
                Defaults to 100 if None.
            full_page (bool, optional): Take a screenshot of the entire page if
                True, otherwise use the current viewport. Defaults to False.
            clip (dict[str, int] | None, optional): Applicable viewport
                settings to crop by. Defaults to None.
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

        Returns:
            bytes: The image content as bytes or base64 encoded bytes.
        """
        screenshot_type = "png"
        if file_type:
            screenshot_type = file_type
        elif file_path:
            mime_type, _ = mimetypes.guess_type(file_path)
            if mime_type == 'image/png':
                screenshot_type = 'png'
            elif mime_type == 'image/jpeg':
                screenshot_type = 'jpeg'
            else:
                screenshot_type = f"{mime_type} (mimetype)"
        if screenshot_type not in ['png', 'jpeg']:
            raise ValueError(f'Unsupported screenshot type: {screenshot_type}')
        return await self._screenshot_task(
            screenshot_type,
            file_path,
            jpeg_quality,
            full_page,
            clip,
            omit_background,
            encoding,
            scale,
        )

    async def pdf(
        self,
        file_path: str | None = None,
        scale: int | float = 1,
        display_header_footer: bool = False,
        header_template: str = None,
        footer_template: str = None,
        print_background: bool = False,
        landscape: bool = False,
        page_ranges: str = None,
        paper_format: str = "letter",
        width: str = None,
        height: str = None,
        margin: dict = None,
        prefer_css_page_size: bool = False,
    ) -> bytes:
        """
        Generate a PDF of the current page.

        `Page.pdf` generates a pdf of the page with "print" css media. To
        generate a pdf with screen media, first call
        `page.emulate_media("screen")`.

        The generated PDF will have modified colors for printing; this can
        be overriden by setting "-webkit-print-color-adjust" to "exact" in
        the page's stylesheet.

        Args:
            file_path (str | None, optional): File path to write output to, if
                any. Defaults to None.
            scale (int | float, optional): Scale the PDF, 0-1. Defaults to 1.
            display_header_footer (bool, optional): Display header and footer.
                Defaults to False.
            header_template (str, optional): HTML template for the print header.
                Should be valid HTML markup with following HTML classes used to
                inject printing values into them:
                    date: formatted print date
                    title: document title
                    url: document location
                    pageNumber: current page number
                    totalPages: total pages in the document
                For example, `<span class=title></span>` would generate span
                containing the title.
                Defaults to None.
            footer_template (str, optional): Same as `header_template` but for
                the page footer. Defaults to None.
            print_background (bool, optional): Print background graphics.
                Defaults to False.
            landscape (bool, optional): Orient the PDF as landscape if True,
                otherwise as portrait. Defaults to False.
            page_ranges (str, optional): Page ranges to print, can be individual
                such as "7" or numerous such as "2-4,7,11-17".
                Defaults to all if None.
            paper_format (str, optional): Paper format, overrides width/height.
                Formats are:
                    "letter": 8.5in x 11in
                    "legal": 8.5in x 14in
                    "tabloid": 11in x 17in
                    "ledger": 17in x 11in
                    "a0": 33.1in x 46.8in
                    "a1": 23.4in x 33.1in
                    "a2": 16.5in x 23.4in
                    "a3": 11.7in x 16.5in
                    "a4": 8.27in x 11.7in
                    "a5": 5.83in x 8.27in
                    "a6": 4.13in x 5.83in
                Defaults to "letter".
            width (str, optional): Page width. Accepts units, defaults to pixels
                if not provided. Units:
                    "px": pixel
                    "in": inch
                    "cm": centimeter
                    "mm": millimeter
                Defaults to None.
            height (str, optional): Page width. Accepts the same units as width.
                Defaults to None.
            margin (dict, optional): Margin values, can include any combination
                of "top", "bottom", "left", and "right".
                Accepts the same unit values as `width` and `height`.
                Defaults to None.
            prefer_css_page_size (bool, optional): Any CSS "@page" size.
                Overrides values from `paper_format`, `width`, and `height`.
                Defaults to False.

        Raises:
            ValueError: Raised if unknown paper format given.

        Returns:
            bytes: File content as bytes.
        """
        paper_formats = dict(
            letter={'width': 8.5, 'height': 11},
            legal={'width': 8.5, 'height': 14},
            tabloid={'width': 11, 'height': 17},
            ledger={'width': 17, 'height': 11},
            a0={'width': 33.1, 'height': 46.8},
            a1={'width': 23.4, 'height': 33.1},
            a2={'width': 16.5, 'height': 23.4},
            a3={'width': 11.7, 'height': 16.5},
            a4={'width': 8.27, 'height': 11.7},
            a5={'width': 5.83, 'height': 8.27},
        )
        if not header_template:
            header_template = ''
        if not footer_template:
            footer_template = ''
        if not page_ranges:
            page_ranges = ''
        paper_width = 8.5
        paper_height = 11.0
        if paper_format:
            fmt = paper_formats.get(paper_format.lower())
            if not fmt:
                raise ValueError(f"Unknown paper format: {paper_format}")
            paper_width = fmt['width']
            paper_height = fmt['height']
        else:
            paper_width = self._convert_print_param(width) or paper_width
            paper_height = self._convert_print_param(height) or paper_height
        if margin:
            margin_top = self._convert_print_param(margin.get('top')) or 0
            margin_left = self._convert_print_param(margin.get('left')) or 0
            margin_bottom = self._convert_print_param(margin.get('bottom')) or 0
            margin_right = self._convert_print_param(margin.get('right')) or 0
        else:
            margin_top = margin_left = margin_bottom = margin_right = 0
        result = await self._client.send(
            PAGE_PRINT_TO_PDF,
            dict(
                landscape=landscape,
                displayHeaderFooter=display_header_footer,
                headerTemplate=header_template,
                footerTemplate=footer_template,
                printBackground=print_background,
                scale=scale,
                paperWidth=paper_width,
                paperHeight=paper_height,
                marginTop=margin_top,
                marginBottom=margin_bottom,
                marginLeft=margin_left,
                marginRight=margin_right,
                pageRanges=page_ranges,
                preferCSSPageSize=prefer_css_page_size,
            ),
        )
        buffer = base64.b64decode(result.get('data', b''))
        if file_path:
            with open(file_path, 'wb') as f:
                f.write(buffer)
        return buffer

    async def title(self) -> str:
        """
        Get the title for this `Page.main_frame`.
        Wrapper for `Page.main_frame.title`.

        Returns:
            str: Page title.
        """
        frame = self._ensure_frame()
        return await frame.title()

    async def close(self, run_before_unload: bool = False) -> None:
        """
        Close the remote page.

        Args:
            run_before_unload (bool, optional): Whether to run handlers
                registered to "Window.beforeunload".
                Defaults to False.

        Raises:
            PageError: Raised if the remote connection has already been closed.
        """
        conn = self._client._connection
        if conn is None:
            raise PageError(
                'Protocol Error: Connection Closed. '
                'Most likely the page has been closed.'
            )
        if run_before_unload:
            await self._client.send(PAGE_CLOSE)
        else:
            await conn.send(TARGET_CLOSE, {'targetId': self._target._targetId})
            await self._target._is_closed_promise

    async def click(
        self,
        selector: str,
        button: Literal["left", "right", "middle"] = "left",
        click_count: int = 1,
        delay: int | float | None = 1000,
    ) -> None:
        """
        Click the first element that matches `selector`.
        Wrapper for `Page.main_frame.click`.

        This method is a shortcut for running `Page.query_selector` and then
        running `mokr.execution.ElementHandle.click` on the resultant
        ElementHandle. In either case, an element will be scrolled into view
        if needed, and the center of it clicked with the bound `Page.mouse`.

        Args:
            selector (str): Selector to query element by.
            button (Literal["left", "right", "middle"], optional): Mouse button
                to click with. Defaults to "left".
            click_count (int, optional): Number of clicks to run. Defaults to 1.
            delay (int | float | None, optional): Time in milliseconds to wait
                before each click. Defaults to 1000.

        Raises:
            PageError: Raised if no element is found with given `selector`.
        """
        frame = self._ensure_frame()
        await frame.click(selector, button, click_count, delay)

    async def hover(self, selector: str) -> None:
        """
        Mouse hover over the first element that matches `selector`.
        Wrapper for `Page.main_frame.hover`.

        Raises:
            PageError: Raised if no element is found with given `selector`.

        Args:
            selector (str): Selector to query element by.
        """
        frame = self._ensure_frame()
        await frame.hover(selector)

    async def focus(self, selector: str) -> None:
        """
        Focus on the first element that matches `selector`.
        Wrapper for `Page.main_frame.focus`.

        Raises:
            PageError: Raised if no element is found with given `selector`.

        Args:
            selector (str): Selector to query element by.
        """
        frame = self._ensure_frame()
        await frame.focus(selector)

    async def select(self, selector: str, values: list[str]) -> list[str]:
        """
        Select options on a "select" element.
        Wrapper for `Page.main_frame.select`.

        Args:
            selector (str): Selector to query element by.
            values (list[str]): List of string options to select by.

        Returns:
            list[str]: List of selected values.
        """
        frame = self._ensure_frame()
        return await frame.select(selector, values)

    async def type_text(
        self,
        selector: str,
        text: str,
        delay: int | float = 0,
    ) -> None:
        """
        Focus on the first element that matches `selector` and type characters
        into it.
        Wrapper for `Page.main_frame.type_text`.

        Note that modifier keys do not alter text case, meaning sending
        `mokr.input.Keyboard.press("shift")` and typing
        `Page.type_text("input", "mokr")` will not type "MOKR" into the it.

        Raises:
            PageError: Raised if no element is found with given `selector`.

        Args:
            selector (str): Selector to query element by.
            text (str): Text to type.
            delay (int | float, optional): Time in milliseconds to wait between
                each character typed. Defaults to 0.
        """
        frame = self._ensure_frame()
        return await frame.type_text(selector, text, delay)

    def wait_for_timeout(self, timeout: int | float) -> Awaitable[None]:
        """
        Wait for the given amount of time. Same as `asyncio.sleep`.
        Wrapper for `Page.main_frame.wait_for_timeout`.

        Args:
            timeout (int | float): Time in milliseconds to wait.

        Returns:
            Awaitable[None]: Task to be awaited.
        """
        frame = self._ensure_frame()
        return frame.wait_for(timeout)

    def wait_for_selector(
        self,
        selector: str,
        visible: bool = False,
        hidden: bool = False,
        timeout: int = 30000,
    ) -> Awaitable[ElementHandle]:
        """
        Wait for element that matches `selector` to appear in DOM.
        If element is in DOM already when called, return immediately.
        Wrapper for `Page.main_frame.wait_for_selector`.

        Args:
            selector (str): Selector to query element by.
            visible (bool, optional): Element must also not be hidden.
                Defaults to False.
            hidden (bool, optional): Element must also be hidden.
                Defaults to False.
            timeout (int, optional): Time in milliseconds to wait.
                Defaults to 30000.

        Raises:
            MokrTimeoutError: Raised if timeout exceeded before element found.

        Returns:
            Awaitable[ElementHandle]: Newly created
                `mokr.execution.ElementHandle` from found object.
        """
        frame = self._ensure_frame()
        return frame.wait_for_selector(selector, visible, hidden, timeout)

    def wait_for_xpath(
        self,
        xpath: str,
        visible: bool = False,
        hidden: bool = False,
        timeout: int = 30000,
    ) -> Awaitable[ElementHandle]:
        """
        Wait for element that matches `xpath` expression to appear in DOM.
        If element is in DOM already when called, return immediately.
        Wrapper for `Page.main_frame.wait_for_xpath`.

        Args:
            xpath (str): Expression to query element by.
            visible (bool, optional): Element must also not be hidden.
                Defaults to False.
            hidden (bool, optional): Element must also be hidden.
                Defaults to False.
            timeout (int, optional): Time in milliseconds to wait.
                Defaults to 30000.

        Raises:
            MokrTimeoutError: Raised if timeout exceeded before element found.

        Returns:
            Awaitable[ElementHandle]: Newly created
                `mokr.execution.ElementHandle` from found object.
        """
        frame = self._ensure_frame()
        return frame.wait_for_xpath(xpath, visible, hidden, timeout)

    def wait_for_function(
        self,
        page_function: str,
        polling: Literal["raf", "mutation"] | int | float = "raf",
        timeout: int = 30000,
    ) -> Awaitable[JavascriptHandle]:
        """
        Wait until the given `page_function` returns a truthy value.
        Wrapper for `Page.main_frame.wait_for_function`.

        Args:
            page_function (str): JavaScript function to run.
            polling (Literal["raf", "mutation"] | int | float, optional):
                Polling type; if set to "raf", executes continously in
                "requestAnimationFrame", else if set to "mutation" executes
                only on DOM mutations.
                Defaults to "raf".
            timeout (int, optional): Time in milliseconds to wait.
                Defaults to 30000.

        Returns:
            Awaitable[JavascriptHandle]: JavascriptHandle from JavaScript
                `page_function` successful result.
        """
        frame = self._ensure_frame()
        return frame.wait_for_function(page_function, polling, timeout)

    async def fetch(
        self,
        url: str | None = None,
        timeout: int = None,
        request: Request | None = None,
        body: str | None = None,
        browsing_topics: bool | None = None,
        cache: Literal[
            "default",
            "no-store",
            "reload",
            "no-cache",
            "force-cache",
            "only-if-cache",
        ] | None = None,
        credentials: Literal["omit", "same-origin", "include"] | None = None,
        headers: dict | None = None,
        method: str = "GET",
        mode: Literal["cors", "no-cors", "same-origin"] = None,
        priority: Literal["high", "low", "auto"] | None = None,
        redirect: Literal["follow", "error", "manual"] | None = None,
        referrer: str | None = None,
        referrer_policy: Literal[
            "no-referrer",
            "no-referrer-when-downgrade",
            "same-origin",
            "origin",
            "strict-origin",
            "origin-when-cross-origin",
            "strict-origin-when-cross-origin",
            "unsafe-url",
        ] | None = None,
    ) -> Response:
        """
        Send a fetch request.
        Wrapper for `Page.fetch_domain.fetch`.

        Note that fetch is sensitive to the current site's CORS settings.
        Additionally, trying to send a fetch request before the DOM loads can
        hang forever.

        Args:
            url (str | None, optional): The url to request.
                Ignored if `request` is given.
                Defaults to None.
            timeout (int, optional): Time in milliseconds to wait.
                Defaults to None.
            request (Request | None, optional): A request object to pull `url`,
                `method`, and `headers` from. Defaults to None.
            body (str | None, optional): Body to add to the request.
                Defaults to None.
            browsing_topics (bool | None, optional): If True, selected topics
                will be sent in a Sec-Browsing-Topics header with the associated
                request.
                Defaults to None.
            cache (Literal[str]): How the request should
                interact with the HTTP cache. One of: "default", "no-store",
                "reload", "no-cache", "force-cache", or "only-if-cache".
                Defaults to None.
            credentials (Literal[str] | None, optional): How to handle
                credentials. One of "omit", "same-origin", or "include".
                Defaults to None.
            headers (dict | None, optional): Headers to pass with the request.
                Defaults to None.
            method (str, optional): HTTP method. Defaults to "GET".
            mode (Literal["cors", "no-cors", "same-origin"], optional):
                CORS mode to use. Defaults to None.
            priority (Literal["high", "low", "auto"] | None, optional):
                Priority of request relative to others. Defaults to None.
            redirect (Literal["follow", "error", "manual"] | None, optional):
                How to handle redirects. Defaults to None ("follow").
            referrer (str | None, optional): Request referrer. Defaults to None.
            referrer_policy (Literal[str]): The referrer policy to use.
                One of "no-referrer", "no-referrer-when-downgrade",
                "same-origin", "origin", "strict-origin",
                "origin-when-cross-origin", "strict-origin-when-cross-origin",
                or "unsafe-url".
                Defaults to None ("strict-origin-when-cross-origin").

        Raises:
            ValueError: Raised if neither `url` nor `request` given.
            NetworkError: Raised if no response found when request resolves.

        Returns:
            Response: Last response recieved after all redirects, if any.
        """
        return await self._fetch_domain.fetch(
            url,
            timeout,
            request,
            body,
            browsing_topics,
            cache,
            credentials,
            headers,
            method,
            mode,
            priority,
            redirect,
            referrer,
            referrer_policy
        )

    async def send(
        self,
        url: str,
        method: HTTP_METHODS = "GET",
        params: dict | None = None,
        headers: dict | None = None,
        data: dict | None = None,
        json: dict | None = None,
        **httpx_request_kwargs,
    ) -> Response:
        """
        Send an HTTP request.
        Wrapper for `Page.http_domain.send`.

        Args:
            url (str): The url to request.
            method (Literal[str], optional): HTTP method. Defaults to "GET".
            params (dict | None, optional): Parameters to encode in the URL
                before sending. Defaults to None (omitted).
            headers (dict | None, optional): Additional headers to send with
                this request beyond what was set when the client was created.
                Defaults to None (omitted).
            data (dict | None, optional): Data payload to deliver with request
                (form-encoded data). Only for "PUT", "POST", and "PATCH".
                Defaults to None (omitted).
            json (dict | None, optional): Data payload to deliver with request
                (JSON-encoded data). Only for "PUT", "POST", and "PATCH".
                Defaults to None (omitted).

        Raises:
            ValueError: Raised if invalid HTTP method given or `data` or `json`
                arguments given with incompatible methods.

        Returns:
            Response: A `mokr.network.Response` created from the
                `httpx.Response`. All redirects will also be created, and
                original requests and responses will be accessible from the
                `mokr.network` objects.
        """
        return await self.http_domain.send(
            url,
            method,
            params,
            headers,
            data,
            json,
            **httpx_request_kwargs,
        )

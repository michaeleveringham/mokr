from mokr.network.request import Request


class NetworkEventManager():
    def __init__(self) -> None:
        """
        This class manages a collection of dictionaries used by
        `mokr.network.NetworkManager` to track active event status as events can
        be received in multiple different orders.

        See `mokr.network.NetworkManager` for more information.
        """
        # NetworkRequestId to Network.RequestWillBeSentEvent
        self.request_will_be_sent_map = {}
        # NetworkRequestId to Fetch.RequestPausedEvent
        self.request_paused_map = {}
        # NetworkRequestId to CdpHTTPRequest
        self.http_requests_map = {}
        # NetworkRequestId to Network.ResponseReceivedExtraInfoEvent
        self.response_received_extra_info_map = {}
        # NetworkRequestId to RedirectInfoList
        self.queued_redirect_info_map = {}
        # NetworkRequestId to QueuedEventGroup
        self.queued_event_group_map = {}
        # The response_received_extra_info_map, queued_redirect_info_map,
        # and queued_event_group_map maps are used to reconcile
        # "Network.ResponseReceivedExtraInfo" events with their corresponding
        # request.
        # Each response and redirect response gets an "ExtraInfo" event, but we
        # don't know which will come first.
        # To resolve this, we store a Response or an ExtraInfo for each
        # response, and the `NetworkManager` emits the event when we have both.
        # As arrays they model the chain of events and handle redirects.

    def forget(self, network_id: str) -> None:
        """
        Remove data for the given `network_id` from all mappings.

        Args:
            network_id (str): Request network identifier.
        """
        for request_map in [
            self.request_will_be_sent_map,
            self.request_paused_map,
            self.queued_event_group_map,
            self.queued_redirect_info_map,
            self.response_received_extra_info_map,
        ]:
            try:
                request_map.pop(network_id)
            except KeyError:
                pass

    def response_extra_info(self, network_id: str) -> list[dict]:
        """
        Get stored response extraInfo for given `network_id`.

        Args:
            network_id (str): Request network identifier.

        Returns:
            list[dict]: List of extraInfo events as dictionaries.
        """
        if not self.response_received_extra_info_map.get(network_id):
            self.response_received_extra_info_map[network_id] = []
        return self.response_received_extra_info_map[network_id]

    def queued_redirect_info(self, fetch_id: str) -> list[dict]:
        """
        Get stored redirect info for given `fetch_id`.

        Args:
            fetch_id (str): Request fetch identifier.

        Returns:
            list[dict]: List of redirect info as dictionaries.
        """
        if not self.queued_redirect_info_map.get(fetch_id):
            self.queued_redirect_info_map[fetch_id] = []
        return self.queued_redirect_info_map[fetch_id]

    def queue_redirect_info(
        self,
        fetch_id: str,
        redirect_info: list[dict],
    ) -> None:
        """
        Store redirect info under a given `fetch_id`.

        Args:
            fetch_id (str): Request fetch identifier.
            redirect_info (list[dict]): Redirect info data.
        """
        self.queued_redirect_info_map[fetch_id] = redirect_info

    def take_queued_redirect_info(self, fetch_id: str) -> list[dict]:
        """
        Remove and return redirect info stored under given `fetch_id`.

        Args:
            fetch_id (str): Request fetch identifier.

        Returns:
            list[dict]: Redirect info data.
        """
        if self.queued_redirect_info(fetch_id):
            return self.queued_redirect_info_map.pop(fetch_id)
        else:
            return []

    def get_in_flight_requests_count(self) -> int:
        """
        Get the number of active requests (not resolved).

        Returns:
            int: Number of active requests.
        """
        in_flight_requests_counter = 0
        for request in self.http_requests_map.values():
            if not request.response():
                in_flight_requests_counter += 1
        return in_flight_requests_counter

    def store_request_will_be_sent(self, network_id: str, event: dict) -> None:
        """
        Store a requestWillBeSent event under given `network_id`.

        Args:
            network_id (str): Request network identifier.
            event (dict): The requestWillBeSent event received.
        """
        self.request_will_be_sent_map[network_id] = event

    def get_request_will_be_sent(self, network_id: str) -> dict:
        """
        Get requestWillBeSent event stored under given `network_id`.

        Args:
            network_id (str): Request network identifier.

        Returns:
            dict: The stored requestWillBeSent under given `network_id`.
        """
        return self.request_will_be_sent_map.get(network_id)

    def forget_request_will_be_sent(self, network_id: str) -> None:
        """
        Remove requestWillBeSent stored under given `network_id`.

        Args:
            network_id (str): Request network identifier.
        """
        self.request_will_be_sent_map.pop(network_id)

    def get_request_paused(self, network_id: str) -> dict:
        """
        Get requestPaused event stored under given `network_id`.

        Args:
            network_id (str): Request network identifier.

        Returns:
            dict: The stored requestPaused under given `network_id`.
        """
        return self.request_paused_map.get(network_id)

    def forget_request_paused(self, network_id: str) -> None:
        """
        Remove requestPaused stored under given `network_id`.

        Args:
            network_id (str): Request network identifier.
        """
        self.request_paused_map.pop(network_id)

    def store_request_paused(self, network_id: str, event: dict) -> None:
        """
        Store a requestPaused event under given `network_id`.

        Args:
            network_id (str): Request network identifier.
            event (dict): The requestPaused event received.
        """
        self.request_paused_map[network_id] = event

    def get_request(self, network_id: str) -> Request:
        """
        Get `mokr.network.Request` stored under given `network_id`.

        Args:
            network_id (str): Request network identifier.

        Returns:
            dict: The stored `mokr.network.Request` under given `network_id`.
        """
        return self.http_requests_map.get(network_id)

    def store_request(self, network_id: str, request: Request) -> None:
        """
        Store a `mokr.network.Request` under given `network_id`.

        Args:
            network_id (str): Request network identifier.
            request (Request): The `mokr.network.Request` received.
        """
        self.http_requests_map[network_id] = request

    def forget_request(self, network_id: str) -> None:
        """
        Remove `mokr.network.Request` stored under given `network_id`.

        Args:
            network_id (str): Request network identifier.
        """
        self.http_requests_map.pop(network_id)

    def get_queued_event_group(self, network_id: str) -> dict:
        """
        Get responseReceivedEvent event stored under given `network_id`.

        Args:
            network_id (str): Request network identifier.

        Returns:
            dict: The stored responseReceivedEvent event under given
                `network_id`.
        """
        return self.queued_event_group_map.get(network_id)

    def queue_event_group(self, network_id: str, event: dict) -> None:
        """
        Store a responseReceivedEvent event under given `network_id`.

        Args:
            network_id (str): Request network identifier.
            event (dict): The responseReceivedEvent received.
        """
        self.queued_event_group_map[network_id] = event

    def forget_queued_event_group(self, network_id: str) -> None:
        """
        Remove responseReceivedEvent event stored under given `network_id`.

        Args:
            network_id (str): Request network identifier.
        """
        self.queued_event_group_map.pop(network_id)

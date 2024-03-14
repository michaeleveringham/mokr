import logging


LOGGER = logging.getLogger(__name__)


class SecurityDetails():
    def __init__(
        self,
        subject_name: str,
        issuer: str,
        valid_from: int,
        valid_to: int,
        protocol: str,
    ) -> None:
        """
        A simple representation of remote response security details.

        Args:
            subject_name (str): Subject to which the certificate was issued to.
            issuer (str): Name of issuer of the certificate.
            valid_from (int): Unix time string of start of certificate validity.
            valid_to (int): Unix time string of end of certificate validity.
            protocol (str): Security protocol (e.g. "TLS1.2", "TLS1.3").
        """
        self._subject_name = subject_name
        self._issuer = issuer
        self._valid_from = valid_from
        self._valid_to = valid_to
        self._protocol = protocol

    @property
    def subject_name(self) -> str:
        """Subject to which the certificate was issued to."""
        return self._subject_name

    @property
    def issuer(self) -> str:
        """Name of issuer of the certificate."""
        return self._issuer

    @property
    def valid_from(self) -> int:
        """Unix time string of start of certificate validity."""
        return self._valid_from

    @property
    def valid_to(self) -> int:
        """Unix time string of end of certificate validity."""
        return self._valid_to

    @property
    def protocol(self) -> str:
        """Security protocol (e.g. "TLS1.2", "TLS1.3")."""
        return self._protocol

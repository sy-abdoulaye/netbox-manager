"""Polatis Optical Switch SDK Wrapper.

This module provides an interface to control Polatis optical switches
via the pypolatis library. Used for managing fiber cross-connections
in test topologies.

Example:
    ```python
    from common.sdk.polatis import Polatis

    # Initialize and connect
    polatis = Polatis(
        polatis_address="192.168.1.50",
        username="admin"
    )
    polatis.connect(password="secret")

    # Get current connection for a port
    connection = polatis.get_conn([1, 2])

    # Create a new cross-connection (port 1 to port 33)
    polatis.create_conn([1, 33])

    # Remove a connection
    polatis.remove_conn([1, 33])

    # Cleanup
    polatis.logout()
    ```
"""

from pypolatis import Session as PolatisSession


class Polatis:
    """SDK wrapper for Polatis optical switches.

    Provides methods to manage fiber cross-connections on Polatis
    optical switches. Used in test topologies to dynamically route
    optical signals between ports.

    Attributes:
        session (PolatisSession): pypolatis session instance.

    Exceptions:
        NoConnectionError: Requested connection does not exist.
        ConnectionNotCompliantError: Connection state doesn't match expected.
    """

    class NoConnectionError(Exception): pass
    class ConnectionNotCompliantError(Exception): pass

    def __init__(self, polatis_address: str, username: str):
        """Initialize the Polatis client.

        Args:
            polatis_address: IP address or hostname of the Polatis switch.
            username: Username for authentication.
        """
        self.session = PolatisSession(
            username=username,
            interface=polatis_address,
            timeout=30
        )

    def connect(self, password: str) -> None:
        """Authenticate with the Polatis switch.

        Args:
            password: Password for authentication.
        """
        self.session.login(password)

    def get_conn(self, connection: list) -> list:
        """Get the current cross-connection state for given ports.

        Args:
            connection: List of port numbers to query (e.g., [1, 33]).

        Returns:
            List containing the current connection state.
        """
        xc = self.session.crossConnection()
        return xc.connection(connection)

    def remove_conn(self, connection: list):
        """Remove an existing cross-connection.

        Args:
            connection: List of port numbers to disconnect (e.g., [1, 33]).

        Returns:
            Result of the remove operation.
        """
        xc = self.session.crossConnection()
        return xc.removeConnection(connection)

    def create_conn(self, connection: list) -> None:
        """Create a new fiber cross-connection.

        Connects two ports on the optical switch. Ports are sorted
        before creating the connection.

        Args:
            connection: List of two port numbers to connect (e.g., [1, 33]).
                The lower port number will be the input, higher will be output.

        Example:
            ```python
            # Connect port 1 to port 33
            polatis.create_conn([1, 33])
            ```
        """
        xc = self.session.crossConnection()
        connection.sort()
        xc.setConnection([connection[0]], [connection[1]])

    def ensure_connection_compliance(self, connection: list) -> None:
        """Verify that a connection exists and matches expected state.

        Used to validate that the physical fiber topology matches
        the expected test configuration.

        Args:
            connection: Expected connection ports (e.g., [1, 33]).

        Raises:
            NoConnectionError: If the connection doesn't exist.
            ConnectionNotCompliantError: If connection exists but doesn't
                match the expected configuration.
        """
        xc_con = self.get_conn(connection)
        if not xc_con:
            raise Polatis.NoConnectionError(f"Connection: '{connection}' does not exist on Polatis")
        if not all(item in connection for item in xc_con[0]):
            raise Polatis.ConnectionNotCompliantError(f"Described Connection in triggers.yaml: '{connection}' for current interface is not compliant with Polatis: '{xc_con}'")

    def get_all_connections(self) -> list:
        """Get all active cross-connections on the Polatis switch.

        Returns:
            List of (ingress, egress) tuples representing active connections.
            Returns empty list if no connections exist.
        """
        xc = self.session.crossConnection()
        return xc.connection() or []

    def logout(self) -> None:
        """Logout from the Polatis switch."""
        self.session.logout()

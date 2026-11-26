"""Compatibility names for the loopback telemetry proxy (see proxy_server.py)."""
from .proxy_server import LocalProxyServer, ProxyConfig

TCPServerConfig = ProxyConfig
TCPServerTransport = LocalProxyServer

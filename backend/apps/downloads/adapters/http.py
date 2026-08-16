from .base import HostAdapter


class DefaultHttpAdapter(HostAdapter):
    """Ports Dart's DefaultHttpAdapter — no header/auth logic of its own;
    the browser-style User-Agent is set by tasks.http_download itself."""

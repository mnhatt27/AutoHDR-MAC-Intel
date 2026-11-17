"""A bundled CA store for macOS, where build-host OpenSSL paths do not exist."""
import ssl
import sys


def ssl_context():
    if sys.platform == "darwin":
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()

"""Put pytest's temporary files on the `/dev/shm` tmpfs."""

try:
    from pytest_shm._version import __version__, __version_tuple__
except ImportError:
    __version__ = "0.0.0"
    __version_tuple__ = (0, 0, 0)

__all__ = ["__version__", "__version_tuple__"]

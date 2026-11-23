"""The scan's camera interface. Its one camera is :class:`treemap.cameras.http.HttpCamera`:
frames the scan page uploads from the phone."""

from treemap.cameras.base import Camera, Frame

__all__ = ["Camera", "Frame"]

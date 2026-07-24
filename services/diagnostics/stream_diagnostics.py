from __future__ import annotations

from typing import Any, Dict, List, Optional
from utils.logger import get_logger

logger = get_logger("stream_diagnostics")


class StreamDiagnostics:
    """Service for monitoring active audio streams, querying performance metrics,
    and programmatically asserting zero buffer underflows/overflows or device errors.
    """

    def __init__(self):
        self._streams: Dict[str, Any] = {}

    def register_stream(self, name: str, stream_obj: Any) -> None:
        """Register an active audio stream instance for diagnostics monitoring."""
        self._streams[name] = stream_obj
        logger.info(f"Registered audio stream '{name}' for diagnostics")

    def unregister_stream(self, name: str) -> None:
        """Unregister an audio stream instance from diagnostics monitoring."""
        if name in self._streams:
            del self._streams[name]
            logger.info(f"Unregistered audio stream '{name}' from diagnostics")

    def get_stream_status(self, name: str) -> Dict[str, Any]:
        """Query diagnostic status for a registered audio stream by name."""
        stream_obj = self._streams.get(name)
        if stream_obj is None:
            return {"name": name, "registered": False, "error": f"Stream '{name}' not registered"}

        if hasattr(stream_obj, "get_diagnostics"):
            diag = stream_obj.get_diagnostics()
            diag["name"] = name
            diag["registered"] = True
            return diag

        # Generic fallback stream status inspection
        running = getattr(stream_obj, "_running", False)
        overflow_count = getattr(stream_obj, "_overflow_count", 0)
        underflow_count = getattr(stream_obj, "_underflow_count", 0)
        total_chunks = getattr(stream_obj, "_total_chunks_processed", 0)
        device_errors = getattr(stream_obj, "_device_init_errors", [])

        return {
            "name": name,
            "registered": True,
            "running": running,
            "overflow_count": overflow_count,
            "underflow_count": underflow_count,
            "total_chunks": total_chunks,
            "device_init_errors": list(device_errors),
        }

    def get_all_diagnostics(self) -> Dict[str, Any]:
        """Query diagnostic status for all registered audio streams."""
        statuses = {name: self.get_stream_status(name) for name in self._streams}
        total_overflows = sum(s.get("overflow_count", 0) for s in statuses.values())
        total_underflows = sum(s.get("underflow_count", 0) for s in statuses.values())
        all_errors: List[str] = []
        for s in statuses.values():
            all_errors.extend(s.get("device_init_errors", []))

        is_reliable = (total_overflows == 0) and (total_underflows == 0) and (len(all_errors) == 0)

        return {
            "active_streams": statuses,
            "stream_count": len(self._streams),
            "total_overflows": total_overflows,
            "total_underflows": total_underflows,
            "device_errors": all_errors,
            "is_reliable": is_reliable,
        }

    def assert_stream_reliability(self, name: Optional[str] = None) -> None:
        """Programmatically assert zero buffer underflows/overflows or device initialization errors.

        Raises AssertionError if any reliability failures are detected.
        """
        if name is not None:
            status = self.get_stream_status(name)
            if not status.get("registered", False):
                raise AssertionError(f"Stream '{name}' is not registered for reliability assertion")
            overflows = status.get("overflow_count", 0)
            underflows = status.get("underflow_count", 0)
            device_errors = status.get("device_init_errors", [])

            err_details = []
            if overflows > 0:
                err_details.append(f"buffer overflows: {overflows}")
            if underflows > 0:
                err_details.append(f"buffer underflows: {underflows}")
            if device_errors:
                err_details.append(f"device errors: {device_errors}")

            if err_details:
                raise AssertionError(f"Audio stream '{name}' failed reliability assertion: {', '.join(err_details)}")
        else:
            diag = self.get_all_diagnostics()
            if not diag["is_reliable"]:
                raise AssertionError(
                    f"Global audio stream reliability assertion failed: "
                    f"overflows={diag['total_overflows']}, "
                    f"underflows={diag['total_underflows']}, "
                    f"device_errors={diag['device_errors']}"
                )

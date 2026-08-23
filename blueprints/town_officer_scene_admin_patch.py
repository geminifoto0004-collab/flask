"""Small admin integration for generic existing-officer scenes."""

import requests as _real_requests

from . import town_admin_runtime as _admin


class _AdminRequestsProxy:
    """Keep admin DeepSeek reads alive past the old 12 second cap.

    This changes only town_admin_runtime's local requests reference; other app
    HTTP calls keep their existing timeouts. The read cap stays below a typical
    Gunicorn worker timeout so one slow model call cannot block forever.
    """

    Timeout = _real_requests.Timeout

    def __getattr__(self, name):
        return getattr(_real_requests, name)

    def post(self, *args, **kwargs):
        timeout = kwargs.get("timeout")
        if isinstance(timeout, tuple) and len(timeout) == 2:
            connect_timeout, read_timeout = timeout
            try:
                if float(read_timeout) < 24:
                    kwargs["timeout"] = (connect_timeout, 24)
            except Exception:
                kwargs["timeout"] = (connect_timeout, 24)
        elif timeout is not None:
            try:
                if float(timeout) < 24:
                    kwargs["timeout"] = 24
            except Exception:
                kwargs["timeout"] = 24
        try:
            return _real_requests.post(*args, **kwargs)
        except _real_requests.Timeout as exc:
            raise RuntimeError("DeepSeek request timed out after the extended wait") from exc


def install_officer_scene_admin_patch():
    previous_metadata = _admin._scene_metadata
    previous_slim_world = _admin._slim_world

    def scene_metadata(raw_actions):
        for action in raw_actions or []:
            if not isinstance(action, dict) or str(action.get("type") or "") != "officer_scene":
                continue
            return {
                "intent_summary": str(action.get("intentSummary") or "").strip()[:140],
                "must_keep": [],
                "creative_freedom": [],
                "director_note": str(action.get("directorNote") or "").strip()[:180],
            }
        return previous_metadata(raw_actions)

    def slim_world(world):
        result = previous_slim_world(world)
        if isinstance(world, dict):
            result["dogPoops"] = world.get("dogPoops", 0)
        return result

    _admin._scene_metadata = scene_metadata
    _admin._slim_world = slim_world
    _admin.requests = _AdminRequestsProxy()

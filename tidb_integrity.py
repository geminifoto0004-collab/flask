"""Process-local evidence and circuit breaker; contains no credentials or SQL I/O."""
from copy import deepcopy
import threading
import time

_lock = threading.RLock()
_generation = 0
_evidence = {'state': 'unverified', 'verified': False, 'targets': {}, 'differences': []}
_blocked = {}
_writers = {}


def note_writer(target, scope):
    with _lock: _writers[scope] = target


def preferred(scope, fallback):
    with _lock: return _writers.get(scope) or fallback


def quota_error(error):
    text = str(error).casefold()
    return any(value in text for value in ('request unit', 'ru limit', 'ru budget', 'ru quota',
               'storage quota', 'resource group quota', 'resource group run out'))


def target_failed(target, error):
    if quota_error(error):
        with _lock:
            _blocked[str(target)] = time.monotonic() + 60


def target_blocked(target):
    with _lock:
        return _blocked.get(str(target), 0) > time.monotonic()


def invalidate():
    global _generation
    with _lock:
        _generation += 1
        _evidence.update(state='pending', verified=False)


def generation():
    with _lock:
        return _generation


def publish(result, expected_generation):
    global _evidence
    with _lock:
        _evidence = deepcopy(result)
        if _generation != expected_generation:
            _evidence.update(state='changed_during_check', verified=False)
        _evidence['checked_at_epoch'] = time.time()
        return deepcopy(_evidence)


def snapshot():
    with _lock:
        result = deepcopy(_evidence)
        result['quota_cooldown_targets'] = [key for key in _blocked if target_blocked(key)]
        return result


def can_promote(target, scope='cloud'):
    with _lock:
        return bool(_evidence.get('verified') and not target_blocked(target)
                    and time.time() - float(_evidence.get('checked_at_epoch') or 0) <= 900
                    and _evidence.get(scope + '_equal') is True
                    and _evidence.get('targets', {}).get(target, {}).get('reachable') is True)

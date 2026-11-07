"""One model request owner across web, CLI, and native worker processes."""
import fcntl
from contextlib import contextmanager
from pathlib import Path

DEFAULT_LOCK=Path(__file__).resolve().parents[1]/'data/inference.lock'

class InferenceBusy(RuntimeError):
    pass

@contextmanager
def inference_lock(path=DEFAULT_LOCK):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+') as handle:
        try:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise InferenceBusy('Another project inference is active; no competing request was sent.') from exc
        try:
            yield
        finally:
            fcntl.flock(handle,fcntl.LOCK_UN)

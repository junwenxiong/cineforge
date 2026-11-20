"""与 h3_queue.py 共用 renders/queue.lock：同一台云机一次只跑一个重型任务。

h3_queue.py 整批持锁且非阻塞抢锁；这里改为阻塞等待，每个任务结束立即释放，
让其他会话（例如 Gemini 的短剧队列）可以在两个任务之间插入。
"""
import contextlib
import msvcrt
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "renders" / "queue.lock"


@contextlib.contextmanager
def gpu_turn(label: str, poll: float = 10.0):
    LOCK.parent.mkdir(exist_ok=True)
    with LOCK.open("a+b") as fh:
        waited = 0.0
        while True:
            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if waited == 0:
                    print(f"[lock] {label}: 云机被其他队列占用，等待中", flush=True)
                time.sleep(poll)
                waited += poll
        try:
            yield
        finally:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)

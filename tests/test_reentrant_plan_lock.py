from concurrent.futures import ThreadPoolExecutor
import multiprocessing
from pathlib import Path
from threading import Event

from local_ai_hub.file_locks import exclusive_file_update


def _try_process_lock(path, queue):
    try:
        with exclusive_file_update(Path(path), timeout=0.3, reentrant=True):
            queue.put("acquired")
    except TimeoutError:
        queue.put("timeout")


def test_reentrant_lock_keeps_other_threads_excluded(tmp_path):
    target = tmp_path / "plan"
    started, finished = Event(), Event()

    def compete():
        started.set()
        with exclusive_file_update(target, timeout=3, reentrant=True):
            finished.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with exclusive_file_update(target, reentrant=True):
            with exclusive_file_update(target, timeout=0.2, reentrant=True):
                future = pool.submit(compete)
                assert started.wait(2)
                assert not finished.wait(0.2)
            assert not finished.is_set()
        future.result(timeout=3)
    assert finished.is_set()


def test_reentrant_lock_cleans_up_after_nested_exception(tmp_path):
    target = tmp_path / "plan"
    try:
        with exclusive_file_update(target, reentrant=True):
            with exclusive_file_update(target, reentrant=True):
                raise RuntimeError("injected")
    except RuntimeError:
        pass
    with exclusive_file_update(target, timeout=0.5, reentrant=True):
        pass


def test_reentrant_lock_retains_process_exclusion(tmp_path):
    target = tmp_path / "plan"
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    with exclusive_file_update(target, reentrant=True):
        with exclusive_file_update(target, reentrant=True):
            process = ctx.Process(target=_try_process_lock, args=(str(target), queue))
            process.start()
            try:
                process.join(timeout=5)
                assert not process.is_alive()
                assert process.exitcode == 0
                assert queue.get(timeout=2) == "timeout"
            finally:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=2)
    queue.close()

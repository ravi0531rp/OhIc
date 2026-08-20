import subprocess
import threading
from dataclasses import dataclass, field


@dataclass
class JobRuntime:
    cancel: threading.Event = field(default_factory=threading.Event)
    pause: threading.Event = field(default_factory=threading.Event)
    processes: list[subprocess.Popen] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)

    def add(self, process: subprocess.Popen) -> None:
        with self.lock:
            self.processes.append(process)

    def remove(self, process: subprocess.Popen) -> None:
        with self.lock:
            if process in self.processes:
                self.processes.remove(process)

    def stop(self) -> None:
        self.cancel.set()
        self.close_processes()

    def request_pause(self) -> None:
        self.pause.set()
        self.cancel.set()
        self.close_processes()

    def close_processes(self) -> None:
        with self.lock:
            for process in self.processes:
                if process.poll() is None:
                    process.terminate()
            self.processes.clear()

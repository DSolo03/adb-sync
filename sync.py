import hashlib
import logging
import shutil
import shlex
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Optional

import adbutils
import yaml


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

def get_file_md5(path: Path):
    md5_hash = hashlib.md5()
    if not path.exists():
        return ""
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            md5_hash.update(chunk)
    return md5_hash.hexdigest()

class Direction(StrEnum):
    push = "push"
    pull = "pull"

class Client:
    adb: adbutils.AdbClient
    device: adbutils.AdbDevice
    def __init__(self):
        self.adb = adbutils.AdbClient("localhost", 5037)
        self.device = self.adb.device()
    
    def _raw_bool(self, result: str) -> bool:
        match result.strip():
            case "True":
                return True
            case "False":
                return False
            case _:
                raise ConnectionError(result)

    def _md5_file(self, remote_path: PurePosixPath) -> str:
        quoted_path = shlex.quote(str(remote_path))
        result = self.device.shell(f"md5sum {quoted_path}").strip()
        if "No such file" in result or not result:
            return ""
        return result.split()[0]

    def compare_files(self, remote_path: PurePosixPath, local_path: Path) -> bool:
        return self._md5_file(remote_path) == get_file_md5(local_path)

    def push(self, remote_path: PurePosixPath, local_path: Path):
        self.device.sync.push(str(local_path), str(remote_path))
    
    def pull(self, remote_path: PurePosixPath, local_path: Path):
        local_path.parent.mkdir(parents = True, exist_ok = True)
        self.device.sync.pull(str(remote_path), str(local_path), exist_ok = True)

    def remove_file(self, remote_path: PurePosixPath):
        self.device.shell(f"rm {shlex.quote(str(remote_path))}")

    def remove_folder(self, remote_path: PurePosixPath):
        self.device.shell(f"rm -r {shlex.quote(str(remote_path))}")

    def verify_path(self, remote_path: PurePosixPath) -> bool:
        path = shlex.quote(str(remote_path))
        result = self.device.shell(f'[ -d {path} ] && echo "True" || echo "False"')
        return self._raw_bool(result)
    
    def verify_file(self, remote_path: PurePosixPath) -> bool:
        path = shlex.quote(str(remote_path))
        result = self.device.shell(f'[ -f {path} ] && echo "True" || echo "False"')
        return self._raw_bool(result)
            
    def list(self, remote_path: PurePosixPath) -> Iterator[PurePosixPath]:
        path = shlex.quote(str(remote_path))
        result = self.device.shell(f'find {path} -maxdepth 1').split("\n")
        for pth in result:
            pth_str = pth.strip()
            if pth_str:
                path_obj = PurePosixPath(pth_str)
                if path_obj != remote_path:
                    yield path_obj

@dataclass
class Sync:
    remote: PurePosixPath
    local: Path
    direction: Direction

class Config:
    syncs: list[Sync]
    def __init__(self, client: Client, config_path: str = "config.yaml"):
        self.syncs = []
        with open(config_path, "r", encoding = "UTF-8") as config_file:
            config = yaml.safe_load(config_file)
        for sync in config.get("syncs", []):
            remote = PurePosixPath(sync.get("remote", ""))
            if not client.verify_path(remote):
                raise ValueError(f"Invalid remote path: {remote}")
            local = Path(sync.get("local", ""))
            if not (local.exists() and local.is_dir()):
                raise ValueError(f"Invalid local path: {local}")
            direction_str = sync.get("direction", "")
            if not direction_str in Direction:
                raise ValueError(f"Invalid direction: {direction_str}")
            direction = Direction(direction_str)
            self.syncs.append(Sync(remote, local, direction))

client = Client()
config = Config(client)

def push(sync: Sync, client: Client, start: Optional[Path] = None):
    '''
    Pushing new files and directories in to Android.
    '''
    folder = start or sync.local
    for object in folder.iterdir():
        if object.is_dir():
            push(sync, client, object)
        elif object.is_file():
            relative = object.relative_to(sync.local)
            if not client.compare_files(sync.remote/relative, object):
                logging.info(f"Pushing {object} to {sync.remote/relative}")
                client.push(sync.remote/relative, object)

def pull(sync: Sync, client: Client, start: Optional[PurePosixPath] = None):
    '''
    Pulling new files and directories from Android.
    '''
    folder = start or sync.remote
    for object in client.list(folder):
        if client.verify_path(object):
            pull(sync, client, object)
        elif client.verify_file(object):
            relative = object.relative_to(sync.remote)
            if not client.compare_files(object, sync.local/relative):
                logging.info(f"Pulling {object} to {sync.local/relative}")
                client.pull(object, sync.local/relative)

def sync_remote(sync: Sync, client: Client, start: Optional[PurePosixPath] = None):
    '''
    Removing deleted files and directories in local on Android.
    '''
    folder = start or sync.remote
    for object in client.list(folder):
        relative = object.relative_to(sync.remote)
        if client.verify_path(object):
            if not (sync.local/relative).exists():
                client.remove_folder(object)
                logging.info(f"Removing folder {object}")
            else:
                sync_remote(sync, client, object)
        elif client.verify_file(object):
            if not (sync.local/relative).exists():
                client.remove_file(object)
                logging.info(f"Removing file {object}")

def sync_local(sync: Sync, client: Client, start: Optional[Path] = None):
    '''
    Removing deleted files and directories in Android on local.
    '''
    folder = start or sync.local
    for object in folder.iterdir():
        relative = object.relative_to(sync.local)
        if object.is_dir():
            if not client.verify_path(sync.remote/relative):
                shutil.rmtree(object)
                logging.info(f"Removing folder {object}")
            else:
                sync_local(sync, client, object)
        elif object.is_file():
            if not client.verify_file(sync.remote/relative):
                object.unlink()
                logging.info(f"Removing file {object}")

for sync in config.syncs:
    match sync.direction:
        case Direction.push:
            push(sync, client)
            sync_remote(sync, client)
        case Direction.pull:
            pull(sync, client)
            sync_local(sync, client)
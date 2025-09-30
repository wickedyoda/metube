codex/disable-actions-and-build-docker-image

import os
import yt_dlp
import shelve
import time
import asyncio
import multiprocessing
import logging
import re
import pickle
import tempfile
import dbm
import dbm.dumb
from collections import OrderedDict
from contextlib import contextmanager
master

import yt_dlp.networking.impersonate
from dl_formats import get_format, get_opts, AUDIO_FORMATS
from datetime import datetime

log = logging.getLogger('ytdl')


class DownloadQueueNotifier:
    async def added(self, dl): raise NotImplementedError
    async def updated(self, dl): raise NotImplementedError
    async def completed(self, dl): raise NotImplementedError
    async def canceled(self, id): raise NotImplementedError
    async def cleared(self, id): raise NotImplementedError


class DownloadInfo:
    def __init__(self, id, title, url, quality, format, folder, custom_name_prefix, error, entry, playlist_item_limit):
        self.id = id if len(custom_name_prefix) == 0 else f'{custom_name_prefix}.{id}'
        self.title = title if len(custom_name_prefix) == 0 else f'{custom_name_prefix}.{title}'
        self.url = url
        self.quality = quality
        self.format = format
        self.folder = folder
        self.custom_name_prefix = custom_name_prefix
        self.msg = self.percent = self.speed = self.eta = None
        self.status = "pending"
        self.size = None
        self.timestamp = time.time_ns()
        self.error = error
        self.entry = entry
        self.playlist_item_limit = playlist_item_limit


# ... (Download class stays unchanged)

class PersistentQueue:
    def __init__(self, path):
        pdir = os.path.dirname(path)
        os.makedirs(pdir, exist_ok=True)
        self.path = path
        with self._open_shelf('c'):
            pass
        self.dict = OrderedDict()

    def _reset_store(self):
        log.warning(f"Resetting persistent store at {self.path} due to unreadable state database")
        candidates = [self.path]
        candidates.extend(f"{self.path}{suffix}" for suffix in ('.db', '.dat', '.dir', '.bak'))
        for candidate in candidates:
            if os.path.isfile(candidate):
                try:
                    os.remove(candidate)
                except OSError as exc:
                    log.error(f"Failed to remove corrupted state file {candidate}: {exc}")

    @contextmanager
    def _open_shelf(self, flag):
        try:
            shelf = shelve.open(self.path, flag)
        except dbm.error:
            log.warning(f"Falling back to dbm.dumb for {self.path}")
            shelf = self._open_dumb(flag)
        except FileNotFoundError:
            if 'r' in flag:
                shelf = self._open_dumb('c')
            else:
                raise
        except Exception:
            if 'r' in flag:
                self._reset_store()
                shelf = self._open_dumb('c')
            else:
                raise
        try:
            yield shelf
        finally:
            shelf.close()

    def _open_dumb(self, flag):
        try:
            return shelve.DbfilenameShelf(dbm.dumb.open(self.path, flag))
        except Exception:
            if 'r' in flag or 'w' in flag:
                self._reset_store()
                return shelve.DbfilenameShelf(dbm.dumb.open(self.path, 'c'))
            raise

    def load(self):
        for k, v in self.saved_items():
            self.dict[k] = Download(None, None, None, None, None, None, {}, v)

    def exists(self, key):
        return key in self.dict

    def get(self, key):
        return self.dict[key]

    def items(self):
        return self.dict.items()

    def saved_items(self):
        try:
            with self._open_shelf('r') as shelf:
                return sorted(shelf.items(), key=lambda item: item[1].timestamp)
        except FileNotFoundError:
            return []

    def put(self, value):
        key = value.info.url
        self.dict[key] = value
        with self._open_shelf('c') as shelf:
            shelf[key] = value.info

    def delete(self, key):
        if key in self.dict:
            del self.dict[key]
            with self._open_shelf('c') as shelf:
                shelf.pop(key, None)
    master

    def next(self):
        k, v = next(iter(self.dict.items()))
        return k, v

    def empty(self):
        return not bool(self.dict)


# ... (DownloadQueue class continues)
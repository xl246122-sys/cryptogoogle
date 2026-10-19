"""Capacity telemetry; estimates are journal-only and never a retention policy."""
import logging
import shutil
import threading
from collections import deque


class CapacityMonitor:
    def __init__(self, store, directory):
        self.store, self.directory = store, directory
        self.samples = deque()
        self.lock = threading.Lock()
        self.latest = {'state': 'WARMUP', 'healthy': None}
        self.last_warning = None

    def sample(self, now):
        with self.store.lock:
            size = self.store.db.execute('PRAGMA page_count').fetchone()[0] * self.store.db.execute('PRAGMA page_size').fetchone()[0]
        disk = shutil.disk_usage(self.directory)
        with self.lock:
            if self.samples and (now <= self.samples[-1][0] or size < self.samples[-1][1]):
                self.samples.clear()
            self.samples.append((now, size))
            while len(self.samples) > 2 and self.samples[1][0] < now-3600000:
                self.samples.popleft()
            elapsed = now-self.samples[0][0]
            growth = (size-self.samples[0][1])*86400000/elapsed if elapsed >= 60000 else None
            days = disk.free/growth if growth is not None and growth > 0 else None
            warning = disk.free < disk.total*.15 or (days is not None and days < 7)
            self.latest = dict(atMs=now, healthy=not warning, state='WARNING' if warning else 'OK' if growth is not None else 'WARMUP',
                               diskFreeBytes=disk.free, diskTotalBytes=disk.total, journalBytes=size,
                               sampleWindowMs=elapsed, journalGrowthBytesPerDay=growth, estimatedJournalDaysRemaining=days,
                               forecastScope='MONITOR_JOURNAL_ONLY', warningFreeFraction=.15, warningDays=7)
            if warning and (self.last_warning is None or now-self.last_warning >= 3600000):
                logging.getLogger('cryptog.capacity').warning('Storage capacity: free=%s bytes; journal growth/day=%s; estimated days=%s', disk.free, growth, days)
                self.last_warning = now
            elif not warning:
                self.last_warning = None

    def status(self, now):
        with self.lock:
            result = dict(self.latest)
        if now-result.get('atMs', 0) > 90000:
            result.update(state='STALE', healthy=False)
        return result

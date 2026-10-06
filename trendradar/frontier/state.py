"""Delivery receipt ledger: previews and failed requests never consume items."""
from datetime import timedelta
from difflib import SequenceMatcher
import json
from pathlib import Path
import sqlite3
from .models import normalized_title


class State:
    def __init__(self, path, now, retention_days=90):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS delivered (key TEXT PRIMARY KEY, day TEXT, title TEXT, aliases TEXT)')
        self.db.execute('DELETE FROM delivered WHERE day < ?', ((now-timedelta(days=retention_days)).date().isoformat(),))
        self.db.commit()

    def history(self):
        return [{'day': day, 'event_title': title} for day, title in
                self.db.execute('SELECT day,title FROM delivered ORDER BY day,key')]

    def delivered_count(self, day):
        return self.db.execute('SELECT count(*) FROM delivered WHERE day=?', (day,)).fetchone()[0]

    def was_delivered(self, event):
        urls = {url for c in event.members for url in c.aliases + [c.url]}
        title = normalized_title(event.event_title)
        for key, old_title, aliases in self.db.execute('SELECT key,title,aliases FROM delivered'):
            if key == event.key or urls.intersection(json.loads(aliases)):
                return True
            if min(len(title), len(normalized_title(old_title))) > 20 and SequenceMatcher(None, title, normalized_title(old_title)).ratio() >= .95:
                return True
        return False

    def record(self, event, now):
        urls = sorted({url for c in event.members for url in c.aliases + [c.url]})
        self.db.execute('INSERT OR IGNORE INTO delivered VALUES (?,?,?,?)',
                        (event.key, now.date().isoformat(), event.event_title, json.dumps(urls)))
        self.db.commit()

    def close(self):
        self.db.close()

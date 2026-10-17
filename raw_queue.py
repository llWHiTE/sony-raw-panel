"""Persistent selection queue. Adding files never opens or develops an image."""
from pathlib import Path
import uuid
from profile_catalog import load, save


class RawQueue:
    def __init__(self, root):
        self.path = Path(root) / 'raw-queue.json'
        data = load(self.path)
        self.items = []
        for row in data.get('items', []):
            if not isinstance(row, dict) or not isinstance(row.get('source'), str) or not isinstance(row.get('id'), str):
                continue
            row = dict(row)
            if row.get('status') in ('running', 'copying', 'preview_ready'):
                row['status'] = 'waiting'
            self.items.append(row)
        self.current = data.get('current')
        if not any(item['id'] == self.current for item in self.items):
            self.current = self.items[0]['id'] if self.items else None

    def save(self):
        save(self.path, dict(version=1, current=self.current, items=self.items))

    def add(self, paths, settings=None):
        validated = [Path(value).resolve(strict=True) for value in paths]
        if any(not path.is_file() or path.suffix.lower() != '.arw' for path in validated):
            raise ValueError('Добавлять можно только существующие Sony ARW.')
        added = []
        for path in validated:
            row = next((item for item in self.items if Path(item['source']) == path), None)
            if row is None:
                row = dict(id=uuid.uuid4().hex, source=str(path), status='waiting', settings=dict(settings or {}))
                self.items.append(row)
            added.append(row)
        if not self.current and added:
            self.current = added[0]['id']
        self.save()
        return added

    def selected(self):
        return next((item for item in self.items if item['id'] == self.current), None)

    def next(self):
        index = next((i for i, item in enumerate(self.items) if item['id'] == self.current), -1)
        return self.items[index + 1] if 0 <= index + 1 < len(self.items) else None

    def select(self, ident):
        row = next(item for item in self.items if item['id'] == ident)
        self.current = ident
        self.save()
        return row

    def move(self, ident, delta):
        index = next(i for i, item in enumerate(self.items) if item['id'] == ident)
        target = max(0, min(len(self.items) - 1, index + delta))
        self.items.insert(target, self.items.pop(index))
        self.save()

    def remove(self, ident):
        if ident == self.current:
            raise ValueError('Сначала выберите другой кадр очереди.')
        self.items = [item for item in self.items if item['id'] != ident]
        self.save()

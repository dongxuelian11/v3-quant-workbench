"""Portable JSON projects and transactional local records."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier():
    return uuid.uuid4().hex


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + identifier() + '.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path, default=None):
    return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else default


class Store:
    def __init__(self, app_data):
        self.root = Path(app_data).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'research.sqlite'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, project TEXT, body TEXT, PRIMARY KEY(kind,id))')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db, timeout=30)
        try:
            db.execute('PRAGMA journal_mode=WAL')
            with db:
                yield db
        finally:
            db.close()

    def put(self, kind, value, project=''):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO records VALUES (?,?,?,?)',
                       (kind, value['id'], project, json.dumps(value, ensure_ascii=False, allow_nan=False)))
        return value

    def get(self, kind, key):
        with self.connect() as db:
            row = db.execute('SELECT body FROM records WHERE kind=? AND id=?', (kind, key)).fetchone()
        if row is None:
            raise ValueError(f'{kind} 不存在: {key}')
        return json.loads(row[0])

    def list(self, kind, project=None):
        with self.connect() as db:
            rows = db.execute('SELECT body FROM records WHERE kind=?' + (' AND project=?' if project else ''),
                              (kind, project) if project else (kind,)).fetchall()
        return sorted((json.loads(row[0]) for row in rows), key=lambda x: x.get('createdAt', ''), reverse=True)

    def delete(self, kind, key):
        with self.connect() as db:
            db.execute('DELETE FROM records WHERE kind=? AND id=?', (kind, key))

    def create_project(self, path, name, objective=''):
        folder = Path(path).resolve()
        if (folder / 'project.json').exists():
            raise ValueError('此目录已有项目，请打开项目')
        folder.mkdir(parents=True, exist_ok=True)
        project = dict(id=identifier(), name=name, objective=objective, path=str(folder),
                       createdAt=now(), updatedAt=now(), startDate='', endDate='', settings={},
                       universe=dict(name='我的股票池', symbols=[], source='manual', excludeST=True, minListingDays=60))
        return self.save_project(project, new=True)

    def open_project(self, path):
        folder = Path(path).resolve()
        project = read_json(folder / 'project.json')
        if not isinstance(project, dict) or not project.get('id'):
            raise ValueError('不是有效的研究项目目录')
        project['path'] = str(folder)
        self.put('project', project)
        portable = self.project_store(project['id'])
        for job in portable.list('job', project['id']):
            if job['status'] in {'running', 'queued'}:
                try:
                    # The service startup handles lost workers. Opening a project inside
                    # that service must preserve its currently owned running/queued record.
                    job = self.get('job', job['id'])
                except ValueError:
                    job.update(status='interrupted', message='此应用没有该任务的工作进程，可重跑', updatedAt=now())
                    portable.put('job', job, project['id'])
            self.put('job', job, project['id'])
        return project

    def project(self, key):
        registered = self.get('project', key)
        project = read_json(Path(registered['path']) / 'project.json')
        if not project or project.get('id') != key:
            raise ValueError('项目目录不可用或项目身份已改变')
        project['path'] = registered['path']
        return project

    def save_project(self, project, new=False):
        project = dict(project)
        if not new:
            old = self.project(project['id'])
            project['path'] = old['path']
            project['createdAt'] = old['createdAt']
        if not project.get('name') or not isinstance(project.get('universe', {}).get('symbols'), list):
            raise ValueError('项目名称和股票池格式无效')
        project['updatedAt'] = now()
        write_json(Path(project['path']) / 'project.json', project)
        self.put('project', project)
        return project

    def project_store(self, project_id):
        return Store(Path(self.project(project_id)['path']) / '.research')

    def experiments(self, project_id):
        return self.project_store(project_id).list('experiment', project_id)

    def experiment(self, project_id, experiment_id):
        return self.project_store(project_id).get('experiment', experiment_id)

    def save_experiment(self, project_id, value):
        value = {**value, 'artifacts': [dict(artifact) for artifact in value['artifacts']]}
        project_root = Path(self.project(project_id)['path']).resolve()
        for artifact in value['artifacts']:
            artifact['path'] = self.artifact_path(project_id, artifact).relative_to(project_root).as_posix()
        return self.project_store(project_id).put('experiment', value, project_id)

    def artifact_path(self, project_id, artifact):
        root = Path(self.project(project_id)['path']).resolve()
        path = Path(artifact['path'])
        if path.is_absolute():
            marker = '/.research/runs/'
            normalized = path.as_posix()
            if marker in normalized:
                path = root / '.research' / 'runs' / normalized.split(marker, 1)[1]
        else:
            path = root / path
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError('实验工件必须位于项目目录内')
        return resolved

    def settings(self, value=None):
        path = self.root / 'settings.json'
        if value is not None:
            old = read_json(path, {})
            old.update(value)
            write_json(path, old)
        result = {'ai': {'baseUrl': '', 'model': '', 'apiKey': '', 'temperature': 0.2}, 'defaultDataSource': 'baostock'}
        saved = read_json(path, {})
        result.update(saved)
        return result

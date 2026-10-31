"""Actual SQLite evidence filtering and bounds; no infrastructure operations."""
import sqlite3
import tempfile
from pathlib import Path
import unittest
from triage.evidence import IncidentStore

class Engine:
    def __init__(self,path):self.path=path
    def connect(self):return sqlite3.connect(self.path)

class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=IncidentStore(Engine(Path(self.temp.name)/'incidents.sqlite3'))
    def add(self,incident,value):
        self.store.record(incident,'owned-target','observation',{'value':value})
    def test_unfiltered_history_is_newest_first_and_bounded(self):
        for i in range(105):self.add('first' if i%2 else 'second',i)
        rows=self.store.timeline()
        self.assertEqual(len(rows),100)
        self.assertEqual([r['data']['value'] for r in rows],list(range(104,4,-1)))
        self.assertEqual(self.store.timeline(''),rows)
    def test_exact_incident_filter_does_not_include_other_incidents(self):
        self.add('one',1);self.add('other',2);self.add('one',3)
        self.assertEqual([r['data']['value'] for r in self.store.timeline('one')],[3,1])
        self.assertEqual(self.store.timeline('missing'),[])
    def test_sql_looking_incident_is_a_literal_not_an_instruction(self):
        literal="' OR 1=1; DROP TABLE incident_steps; --"
        self.add('ordinary',1);self.add(literal,2)
        rows=self.store.timeline(literal)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['incident'],literal)
        self.assertEqual(len(self.store.timeline()),2)

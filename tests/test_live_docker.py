"""Opt-in real Docker acceptance on an explicit local socket, never a remote context.

This lab creates its own containers and automatically approves only their restart
plans. Production approvals are never bypassed. Cleanup checks ownership labels.
"""
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import tempfile
import time
import unittest
from urllib.error import URLError
from urllib.request import urlopen
import uuid
from triage.experience import ExperienceEngine
from triage.integrations import ToolAdapter
from triage.tool_engine import ToolEngine

IMAGE='python:3.12-alpine'
SERVER="""
from http.server import BaseHTTPRequestHandler, HTTPServer
import sys
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        body=b'{"status":"ok"}'
        self.send_response(200)
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)
print('connection refused: synthetic lab log signature',file=sys.stderr,flush=True)
HTTPServer(('0.0.0.0',8080),Handler).serve_forever()
"""


@unittest.skipUnless(os.environ.get('TRIAGE_RUN_DOCKER_LAB')=='1','Opt-in local Docker acceptance lab')
class LiveDockerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(shutil.which('docker'),'Live lab requested but Docker CLI is unavailable')
        local_socket=Path('/var/run/docker.sock')
        self.assertTrue(local_socket.exists() and stat.S_ISSOCK(local_socket.stat().st_mode),'Live lab requires an explicit local Unix Docker socket')
        self.nonce=uuid.uuid4().hex
        self.context='triage-lab-'+self.nonce
        self.name='triage-lab-'+self.nonce
        self.container_id=None
        self.env=dict(os.environ,DOCKER_HOST='',DOCKER_CONTEXT='')
        self.native(['context','create',self.context,'--docker','host=unix:///var/run/docker.sock'],context=False)
        self.addCleanup(self.cleanup_context)
        self.container_id=self.native(['run','--detach','--name',self.name,
            '--label','devops-triage.lab='+self.nonce,
            '--env','TRIAGE_PRIVATE_TEST_VALUE=lab-only-do-not-report',
            '--publish','127.0.0.1::8080',IMAGE,'python','-u','-c',SERVER]).strip()
        self.addCleanup(self.cleanup_container)
        address=self.native(['port',self.container_id,'8080/tcp']).strip()
        self.assertTrue(address.startswith('127.0.0.1:'))
        self.url='http://'+address+'/health'
        deadline=time.monotonic()+15
        while True:
            try:
                with urlopen(self.url,timeout=1) as response:
                    self.assertEqual(response.status,200)
                break
            except (OSError,URLError):
                if time.monotonic()>deadline:self.fail('Disposable application did not become ready')
                time.sleep(.1)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        config={'context':self.context,'resource':self.container_id,
                'application_health':{'url':self.url,'json_path':'status','equals':'ok','attempts':5,'successes':2,'interval':1}}
        self.adapter=ToolAdapter('docker',config)
        self.engine=ExperienceEngine(ToolEngine(self.adapter,self.tmp.name),config['application_health'])

    def native(self,args,context=True):
        command=['docker']+(['--context',self.context] if context else [])+args
        result=subprocess.run(command,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=120,env=self.env)
        if result.returncode:
            # Do not emit daemon details, environment dumps, or arbitrary stderr.
            self.fail('Local disposable Docker operation failed: '+args[0])
        return result.stdout

    def cleanup_container(self):
        if not self.container_id:return
        inspect=subprocess.run(['docker','--context',self.context,'container','inspect',self.container_id],capture_output=True,text=True,timeout=15,env=self.env)
        if inspect.returncode:return
        data=json.loads(inspect.stdout)
        if data[0].get('Id')==self.container_id and data[0].get('Config',{}).get('Labels',{}).get('devops-triage.lab')==self.nonce:
            self.native(['container','rm','--force',self.container_id])
        else:self.fail('Ownership mismatch; refusing cleanup of an unrelated container')

    def cleanup_context(self):
        subprocess.run(['docker','context','rm','--force',self.context],capture_output=True,timeout=15,env=self.env)

    def stop_owned_container(self):
        self.native(['container','stop','--time','1',self.container_id])
        self.assertEqual(self.adapter.collect()['observations']['state'],['exited'])

    def test_real_state_health_deep_logs_and_private_projection(self):
        report=self.engine.scan(deep=True)
        self.assertEqual(report['snapshot']['observations']['state'],['running'])
        self.assertTrue(report['application_health']['healthy'])
        self.assertEqual(report['deep_evidence']['log_signals']['dependency'],1)
        self.assertNotIn('lab-only-do-not-report',json.dumps(report))
        self.assertNotIn('synthetic lab log signature',json.dumps(report))
        self.assertTrue(self.engine.store.timeline(report['incident_id']))

    def test_real_restart_requires_approval_and_recovers_application(self):
        self.stop_owned_container()
        report=self.engine.scan()
        self.assertTrue(any(f['code']=='docker:state' for f in report['findings']))
        plan=self.engine.plan('restart')
        with self.assertRaises(ValueError):self.engine.apply(plan['id'])
        self.assertEqual(self.adapter.collect()['observations']['state'],['exited'])
        # Automated approval is confined to this generated, ownership-labelled lab container.
        self.engine.approve(plan['id'])
        result=self.engine.apply(plan['id'])
        self.assertEqual(result['status'],'verified',result.get('failure_reason'))
        self.assertTrue(result['application_health']['healthy'])
        started=self.adapter.collect()['observations']['started']
        with self.assertRaises(ValueError):self.engine.apply(plan['id'])
        self.assertEqual(self.adapter.collect()['observations']['started'],started)
        self.assertTrue(any(a['severity']=='info' for a in self.engine.store.alerts()))

    def test_external_state_change_invalidates_real_plan(self):
        self.stop_owned_container()
        plan=self.engine.plan('restart')
        self.native(['container','start',self.container_id])
        with self.assertRaises(ValueError):self.engine.approve(plan['id'])
        with self.assertRaises(ValueError):self.engine.apply(plan['id'])
        self.assertEqual(self.adapter.collect()['observations']['state'],['running'])


if __name__=='__main__':unittest.main()

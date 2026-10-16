"""Named local environments sharing one private, atomically written connection file."""
import json
import os
from pathlib import Path
import re
import tempfile
import threading

FILE_LOCK=threading.RLock()
ENVIRONMENTS=('development','staging','production')


def read_document(path):
    path=Path(path)
    if not path.exists():return {'tools':{}}
    if path.stat().st_size>1024*1024:raise ValueError('Configuration exceeds 1 MiB')
    doc=json.loads(path.read_text())
    if not isinstance(doc,dict) or not isinstance(doc.get('tools',{}),dict) or not isinstance(doc.get('profiles',{}),dict):
        raise ValueError('Expected tools and profiles objects in the connection file')
    return doc


def write_document(path,doc):
    path=Path(path);raw=json.dumps(doc,indent=2)+'\n'
    if len(raw.encode())>1024*1024:raise ValueError('Combined configuration exceeds 1 MiB')
    path.parent.mkdir(parents=True,exist_ok=True)
    descriptor,name=tempfile.mkstemp(prefix='.triage-config-',dir=path.parent)
    try:
        with os.fdopen(descriptor,'w') as stream:
            os.fchmod(stream.fileno(),0o600);stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


class Profiles:
    def __init__(self,path,current='default'):
        self.path=Path(path).expanduser().resolve();self.current=current
        self.tools()  # Fail before creating a dashboard for an unknown profile.
    @staticmethod
    def name(value):
        if not isinstance(value,str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,39}',value):raise ValueError('Profile name must be 1–40 lowercase letters, digits or hyphens, starting with a letter')
        return value
    def tools(self,name=None):
        name=self.name(name or self.current);doc=read_document(self.path)
        if name=='default':tools=doc.get('tools',{})
        else:
            item=doc.get('profiles',{}).get(name)
            if not isinstance(item,dict) or item.get('environment') not in ENVIRONMENTS or not isinstance(item.get('tools'),dict):
                raise ValueError('Unknown or invalid profile: '+name)
            tools=item['tools']
        from .catalog import PROFILES
        if any(tool not in PROFILES or not isinstance(config,dict) for tool,config in tools.items()):raise ValueError('Profiles must contain known tool IDs and configuration objects')
        return json.loads(json.dumps(tools))
    def context(self):
        doc=read_document(self.path)
        return {'profile':self.current,'environment':'unspecified' if self.current=='default' else doc['profiles'][self.current]['environment']}
    def listing(self):
        doc=read_document(self.path)
        items=[{'name':'default','environment':'unspecified','tools':sorted(doc.get('tools',{}))}]
        for name in sorted(doc.get('profiles',{})):
            self.tools(name)
            items.append({'name':name,'environment':doc['profiles'][name]['environment'],'tools':sorted(doc['profiles'][name]['tools'])})
        return {'current':self.current,'profiles':items,'note':'Switching does not validate credentials or grant permissions. Production labels are metadata, not RBAC.'}
    def create(self,name,environment):
        name=self.name(name)
        if name=='default' or environment not in ENVIRONMENTS:raise ValueError('Choose a new name and development, staging or production')
        with FILE_LOCK:
            doc=read_document(self.path)
            if name in doc.get('profiles',{}):raise ValueError('Profile already exists; select it to edit tool connections')
            tools=self.tools()
            doc.setdefault('profiles',{})[name]={'environment':environment,'tools':tools}
            write_document(self.path,doc)
        return self.listing()
    def select(self,name):
        self.name(name)
        tools=self.tools(name);self.current=name
        return tools


class ScopedAdapter:
    """Namespace approval identity without changing the native transport target."""
    def __init__(self,adapter,profile):
        from .engine import fingerprint
        self._adapter=adapter
        self.target=adapter.target+':profile:'+fingerprint(profile)[:12]
    def __getattr__(self,name):
        return getattr(self._adapter,name)

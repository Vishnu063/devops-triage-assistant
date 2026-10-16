"""A local configuration wizard. Validation never attempts a mutation."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
from .catalog import PROFILES
from .integrations import ToolAdapter, requirements
from .health import validate_health


class ConnectionWizard:
    def __init__(self,path,configurations):
        self.path=Path(path).expanduser().resolve()
        self.configurations=configurations
        self.lock=threading.RLock()
    def schema(self,tool):
        if tool not in PROFILES:raise ValueError('Choose one of the 60 tool profiles')
        p=PROFILES[tool]
        return {'tool':tool,'name':p['name'],'scope':p['scope'],'required':requirements(p)+(['base_url'] if p['endpoint'] else []),
                'current':self.configurations.get(tool,{}),'auth':'Environment-variable references only; native profiles use their normal credential store.'}
    def save(self,tool,config):
        health=config.get('application_health') if isinstance(config,dict) else None
        validate_health(health)
        # ToolAdapter performs the same validation as the actual runtime.
        adapter=ToolAdapter(tool,config)
        with self.lock:
            document={'tools':{}}
            if self.path.exists():
                if self.path.stat().st_size>1024*1024:raise ValueError('Configuration file is too large')
                document=json.loads(self.path.read_text())
            if not isinstance(document,dict) or not isinstance(document.get('tools',{}),dict):raise ValueError('Existing configuration is invalid')
            document.setdefault('tools',{})[tool]=config
            raw=json.dumps(document,indent=2)+'\n'
            if len(raw.encode())>1024*1024:raise ValueError('Combined configuration exceeds 1 MiB')
            self.path.parent.mkdir(parents=True,exist_ok=True)
            descriptor,name=tempfile.mkstemp(prefix='.triage-config-',dir=self.path.parent)
            try:
                with os.fdopen(descriptor,'w') as stream:
                    os.fchmod(stream.fileno(),0o600);stream.write(raw);stream.flush();os.fsync(stream.fileno())
                os.replace(name,self.path)
            finally:
                if os.path.exists(name):os.unlink(name)
            self.configurations[tool]=json.loads(json.dumps(config))
        binary=PROFILES[tool]['command'][0] if PROFILES[tool]['command'] else None
        return {'tool':tool,'saved':True,'native_cli':binary,'cli_available':shutil.which(binary) is not None if binary else None,
                'read_access':'not_checked; use Validate connection','write_access':'not_tested','note':'No resource change was attempted.'}

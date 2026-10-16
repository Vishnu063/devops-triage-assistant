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
from .profiles import FILE_LOCK, read_document, write_document


class ConnectionWizard:
    def __init__(self,path,configurations,profile="default"):
        self.path=Path(path).expanduser().resolve()
        self.configurations=configurations
        self.lock=FILE_LOCK
        self.profile=profile
    def schema(self,tool):
        if tool not in PROFILES:raise ValueError('Choose one of the 60 tool profiles')
        p=PROFILES[tool]
        return {'tool':tool,'name':p['name'],'scope':p['scope'],'required':requirements(p)+(['base_url'] if p['endpoint'] else []),
                'optional':['service'] if tool=='kubernetes' else [],'current':self.configurations.get(tool,{}),'auth':'Environment-variable references only; native profiles use their normal credential store.'}
    def save(self,tool,config):
        health=config.get('application_health') if isinstance(config,dict) else None
        validate_health(health)
        # ToolAdapter performs the same validation as the actual runtime.
        adapter=ToolAdapter(tool,config)
        with self.lock:
            document=read_document(self.path)
            if self.profile=='default':tools=document.setdefault('tools',{})
            else:
                item=document.get('profiles',{}).get(self.profile)
                if not isinstance(item,dict) or not isinstance(item.get('tools'),dict):raise ValueError('Profile no longer exists')
                tools=item['tools']
            tools[tool]=config
            write_document(self.path,document)
            self.configurations[tool]=json.loads(json.dumps(config))
        binary=PROFILES[tool]['command'][0] if PROFILES[tool]['command'] else None
        return {'tool':tool,'saved':True,'native_cli':binary,'cli_available':shutil.which(binary) is not None if binary else None,
                'read_access':'not_checked; use Validate connection','write_access':'not_tested','note':'No resource change was attempted.'}

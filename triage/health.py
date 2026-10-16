"""Bounded application health probes, with credentials isolated from provider APIs."""
import json
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler
from .integrations import NoRedirect, ToolAdapter, ENV_NAME


def validate_health(config):
    if config is None:
        return None
    if not isinstance(config, dict) or set(config) - {'url','expected_status','json_path','equals','attempts','successes','timeout','interval','headers'}:
        raise ValueError('Unsupported application_health configuration')
    ToolAdapter.validate_base_url(config.get('url',''))
    for name, default, low, high in [('attempts',3,1,5),('successes',2,1,3),('timeout',3,1,5),('interval',1,0,2)]:
        value=config.get(name,default)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'Invalid health setting: {name}')
    if config.get('successes',2)>config.get('attempts',3):
        raise ValueError('Health successes cannot exceed attempts')
    statuses=config.get('expected_status',[200])
    if not isinstance(statuses,list) or not statuses or len(statuses)>10 or any(type(code) is not int or not 100<=code<=599 for code in statuses):
        raise ValueError('expected_status must contain HTTP status codes')
    if 'json_path' in config:
        if not isinstance(config['json_path'],str) or not re.fullmatch(r'[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*',config['json_path']) or 'equals' not in config or not isinstance(config['equals'],(str,int,float,bool,type(None))):
            raise ValueError('JSON health checks need a simple json_path and scalar equals value')
    elif 'equals' in config:
        raise ValueError('equals requires json_path')
    headers=config.get('headers',{})
    if not isinstance(headers,dict):
        raise ValueError('Health headers must reference environment variables')
    # Reuse header validation without resolving credentials or forwarding provider headers.
    ToolAdapter('grafana',{'base_url':config['url'],'headers':headers})
    return config


def check_health(config):
    if not config:
        return {'configured':False,'healthy':None,'scope':'No application health endpoint configured'}
    validate_health(config)
    binding=ToolAdapter('grafana',{'base_url':config['url'],'headers':config.get('headers',{})})
    samples=[];consecutive=0
    for attempt in range(config.get('attempts',3)):
        if attempt:time.sleep(config.get('interval',1))
        started=time.monotonic();status=None;passed=False;reason='Endpoint not reachable or TLS validation failed'
        try:
            opener=build_opener(ProxyHandler({}),NoRedirect())
            request=Request(config['url'],headers=binding.headers(),method='GET')
            try:
                response=opener.open(request,timeout=config.get('timeout',3))
            except HTTPError as error:
                response=error
            with response:
                status=response.code
                # Redirects are never successful health checks, even if configured as expected.
                passed=status in config.get('expected_status',[200]) and not 300<=status<400
                reason='Expected HTTP status observed' if passed else 'Unexpected HTTP status'
                if passed and 'json_path' in config:
                    raw=response.read(65537)
                    if len(raw)>65536:
                        passed=False;reason='Health response exceeded 64 KiB'
                    else:
                        obj=json.loads(raw)
                        for key in config['json_path'].split('.'):
                            obj=obj[key]
                        passed=type(obj) is type(config['equals']) and obj==config['equals']
                        reason='JSON condition matched' if passed else 'JSON condition did not match'
        except (URLError,OSError,ValueError,KeyError,TypeError):
            passed=False;reason='Connection, credential or response validation failed'
        samples.append({'status':status,'passed':passed,'latency_ms':round((time.monotonic()-started)*1000),'reason':reason})
        consecutive=consecutive+1 if passed else 0
        if consecutive>=config.get('successes',2):break
    return {'configured':True,'healthy':consecutive>=config.get('successes',2),'samples':samples,
            'required_consecutive_successes':config.get('successes',2),
            'scope':'Configured endpoint/status and optional JSON assertion only; not a full business transaction test'}

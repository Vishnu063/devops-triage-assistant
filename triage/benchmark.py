"""Opt-in synthetic Ollama benchmark. Keyword checks are not a diagnosis-quality score."""
import os
import platform
import threading
import time
from pathlib import Path
from . import ai
from .investigation import demo_report


def _rss(pid):
    if not pid:return None
    total=0;visited=set();queue=[pid]
    while queue and len(visited)<64:
        current=queue.pop()
        if current in visited:continue
        visited.add(current)
        try:
            total+=int(Path(f'/proc/{current}/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')
            for task in Path(f'/proc/{current}/task').iterdir():
                try:queue.extend(int(p) for p in (task/'children').read_text().split())
                except (OSError,ValueError):continue
        except (OSError,ValueError,IndexError):continue
    return total or None


def benchmark(model=ai.DEFAULT_MODEL,cases=3,ollama_pid=None):
    ai.model_name(model)
    if type(cases) is not int or not 1<=cases<=3 or ollama_pid is not None and (type(ollama_pid) is not int or ollama_pid<1):raise ValueError('Invalid benchmark bounds')
    status=ai.status()
    result={'status':'unavailable','model':model,'hardware':{'system':platform.system(),'machine':platform.machine(),'cpu_count':os.cpu_count()},
            'cases':[],'peak_ollama_process_tree_rss_bytes':None,'peak_reported_model_bytes':None,
            'scope':'Synthetic cases only. RSS sampling includes the supplied Ollama process and descendants, can double-count shared pages, and is not an isolated RAM minimum. Model size is not RAM usage. Keyword checks are not answer-quality validation.'}
    if not status['available'] or model not in status['models']:
        result['message']='Start Ollama and install the requested local model before benchmarking. No model is downloaded by this command.'
        return result
    stop=threading.Event();samples=[];sizes=[]
    def monitor():
        while not stop.is_set():
            samples.append(_rss(ollama_pid))
            try:
                running=ai._request('/api/ps').get('models',[])
                sizes.extend(m['size'] for m in running if isinstance(m,dict) and m.get('name')==model and type(m.get('size')) is int)
            except (OSError,ValueError,ai.http.client.HTTPException):pass
            stop.wait(0.25)
    thread=threading.Thread(target=monitor,daemon=True);thread.start()
    try:
        for scenario,keywords in [('docker-oom',['memory','oom']),('kubernetes-image',['image','registry']),('linux-disk',['disk','space'])][:cases]:
            start=time.monotonic();response=ai.explain(demo_report(scenario),model)
            text=response.get('explanation','')
            result['cases'].append({'scenario':scenario,'latency_ms':round((time.monotonic()-start)*1000),
                'status':response['status'],'explanation':text,'metrics':response.get('metrics',{}),
                'topic_keyword_present':any(word in text.lower() for word in keywords),
                'review_required':True,'validation_flags':response.get('validation_flags',[]),'message':response.get('message')})
    finally:
        stop.set();thread.join(timeout=4)
    memory=[n for n in samples if n is not None]
    result['peak_ollama_process_tree_rss_bytes']=max(memory) if memory else None
    result['peak_reported_model_bytes']=max(sizes) if sizes else None
    result['status']='completed' if all(c['status'] in ('ok','unreliable') for c in result['cases']) else 'incomplete'
    result['accepted_explanations']=sum(c['status']=='ok' for c in result['cases'])
    result['quality_gate']='known_contradictions_detected' if any(c['status']=='unreliable' for c in result['cases']) else 'human_review_still_required'
    result['manual_review']='Review each answer for unsupported root-cause claims, missing evidence and unsafe advice before using this model operationally.'
    return result

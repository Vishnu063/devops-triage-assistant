"""Offline, bounded Kubernetes Deployment review. Never executes manifest content."""
import json
import math
import re
from pathlib import Path
from .kubernetes import references

LIMIT = 1024 * 1024


def load(path):
    with Path(path).expanduser().open('rb') as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('Preflight input exceeds 1 MiB')
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError('Preflight requires Kubernetes JSON; see docs/PREFLIGHT.md') from None
    objects = obj.get('items') if isinstance(obj, dict) and obj.get('kind') == 'List' else [obj]
    if not isinstance(objects, list) or not 1 <= len(objects) <= 100:
        raise ValueError('Provide one object or a Kubernetes List of 1–100 objects')
    if any(not isinstance(o, dict) for o in objects):
        raise ValueError('Every input object must be a JSON object')
    return objects


def matches(selector, labels):
    """Evaluate the Deployment selector subset used by the API."""
    if not isinstance(selector, dict) or not selector:
        raise ValueError('Missing selector')
    fixed = selector.get('matchLabels', {})
    expressions = selector.get('matchExpressions', [])
    if not isinstance(fixed, dict) or not isinstance(expressions, list) or not (fixed or expressions):
        raise ValueError('Invalid selector')
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in fixed.items()):
        raise ValueError('Invalid selector labels')
    result = all(labels.get(k) == v for k, v in fixed.items())
    for expr in expressions:
        key, op, values = expr['key'], expr['operator'], expr.get('values', [])
        if not isinstance(key, str) or not isinstance(values, list) or any(not isinstance(v, str) for v in values):
            raise ValueError('Invalid selector expression')
        if op in ('In', 'NotIn') and values:
            result &= (labels.get(key) in values) if op == 'In' else (labels.get(key) not in values)
        elif op in ('Exists', 'DoesNotExist') and not values:
            result &= (key in labels) if op == 'Exists' else (key not in labels)
        else:
            raise ValueError('Invalid selector operator or values')
    return result


def amount(value, replicas, up=False):
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r'(100|[0-9]{1,2})%', value):
        n = replicas * int(value[:-1]) / 100
        return math.ceil(n) if up else math.floor(n)
    raise ValueError('Invalid rollout budget')


def review(objects):
    findings, unknowns = [], []
    deployments = [(i, o) for i, o in enumerate(objects) if o.get('kind') == 'Deployment']
    if not deployments:
        raise ValueError('Input must contain at least one apps/v1 Deployment')
    def add(index, code, level, message):
        findings.append({'object_index': index, 'code': code, 'severity': level, 'message': message})
    def unknown(index, code, message):
        unknowns.append({'object_index': index, 'code': code, 'message': message})
    for i, dep in deployments:
        try:
            if dep.get('apiVersion') != 'apps/v1':
                raise ValueError('Unsupported Deployment version')
            metadata = dep['metadata']
            if not isinstance(metadata.get('name'), str) or not metadata['name']:
                raise ValueError('Deployment name is required')
            ns = metadata.get('namespace', 'default')
            spec = dep['spec']; template = spec['template']; pod = template['spec']
            labels = template.get('metadata', {}).get('labels', {})
            if not isinstance(labels, dict):
                raise ValueError('Invalid template labels')
            if not matches(spec.get('selector'), labels):
                add(i, 'selector-mismatch', 'critical', 'Deployment selector does not match its pod template labels.')
            replicas = spec.get('replicas', 1)
            if type(replicas) is not int or replicas < 0:
                raise ValueError('Invalid replica count')
            if replicas == 0:
                add(i, 'zero-replicas', 'warning', 'The proposed Deployment runs no replicas.')
            elif replicas == 1:
                add(i, 'single-replica', 'warning', 'One replica provides no replica redundancy.')
            strategy = spec.get('strategy', {})
            if strategy.get('type', 'RollingUpdate') == 'Recreate':
                add(i, 'recreate', 'warning', 'Recreate stops old pods before replacing them; plan for an availability gap.')
            elif strategy.get('type', 'RollingUpdate') == 'RollingUpdate':
                rolling = strategy.get('rollingUpdate', {})
                unavailable = amount(rolling.get('maxUnavailable', '25%'), replicas)
                surge = amount(rolling.get('maxSurge', '25%'), replicas, True)
                if replicas and unavailable == 0 and surge == 0:
                    add(i, 'rollout-blocked', 'critical', 'Both effective rollout budgets are zero; the rollout cannot progress.')
                if replicas and unavailable >= replicas:
                    add(i, 'all-replicas-unavailable', 'warning', 'The rollout budget permits every desired replica to be unavailable.')
            else:
                raise ValueError('Unsupported strategy')
            containers = pod['containers']
            init = pod.get('initContainers', [])
            if not isinstance(containers, list) or not containers or not isinstance(init, list) or len(containers) + len(init) > 100:
                raise ValueError('Expected 1–100 containers including init containers')
            names = set()
            for c in containers + init:
                name = c.get('name')
                if not isinstance(name, str) or not name or name in names:
                    raise ValueError('Container names must be present and unique')
                names.add(name)
                image = c.get('image')
                if not isinstance(image, str) or not image or len(image) > 2048 or re.search(r'\s|://|\$|[{}]', image):
                    add(i, 'invalid-image', 'critical', 'A container image is missing or contains unsupported whitespace, scheme or template syntax.')
                elif not re.fullmatch(r'.+@sha256:[a-fA-F0-9]{64}', image):
                    add(i, 'mutable-image', 'warning', 'An image lacks a sha256 digest; tags may change. Registry existence is unverified.')
                if c in containers and not c.get('readinessProbe'):
                    add(i, 'readiness-missing', 'warning', 'An application container has no explicit readiness probe.')
                requests = c.get('resources', {}).get('requests', {})
                if not requests.get('cpu') or not requests.get('memory'):
                    add(i, 'requests-missing', 'warning', 'A container lacks explicit CPU or memory requests; scheduling capacity is unverified.')
            refs = references(pod)
            if len(refs) > 100:
                raise ValueError('Too many configuration references')
            for (kind, name), optional in refs.items():
                supplied = any(o.get('kind', '').lower() == kind and o.get('metadata', {}).get('name') == name
                               and o.get('metadata', {}).get('namespace', 'default') == ns for o in objects)
                if not supplied and not optional:
                    unknown(i, 'external-configuration', 'A required Secret/ConfigMap reference is not included in this namespace. Verify its live existence and required keys.')
            for service in (o for o in objects if o.get('kind') == 'Service' and o.get('metadata', {}).get('namespace', 'default') == ns):
                sel = service.get('spec', {}).get('selector', {})
                if sel and not isinstance(sel, dict):
                    raise ValueError('Invalid Service selector')
                if sel and not all(labels.get(k) == v for k, v in sel.items()):
                    add(i, 'service-selector-mismatch', 'warning', 'A supplied Service does not select this Deployment template; verify whether that relationship is intended.')
            unknown(i, 'live-checks-required', 'Registry image existence, Secret/ConfigMap keys and values, node capacity, admission, networking and runtime health require separate live validation.')
        except (KeyError, TypeError, ValueError, AttributeError, IndexError):
            # Never echo manifest content or exception values: those may contain secrets.
            unknown(i, 'unsupported-structure', 'This Deployment or related object has an invalid or unsupported structure; review the manifest with Kubernetes schema validation.')
    return {'status': 'incomplete' if any(x['code'] == 'unsupported-structure' for x in unknowns) else 'reviewed',
            'scope': 'Offline Deployment heuristics only. No API, registry, commands, AI or repairs. Not Kubernetes schema validation or deployment approval.',
            'deployments_reviewed': len(deployments), 'findings': findings, 'unverified': unknowns,
            'other_objects': sum(o.get('kind') not in ('Deployment', 'Service', 'Secret', 'ConfigMap') for o in objects)}


def exit_code(report, fail_on='critical'):
    if report['status'] == 'incomplete':
        return 2
    return 3 if any(fail_on in ('any', 'warning') or fail_on == f['severity'] for f in report['findings']) else 0

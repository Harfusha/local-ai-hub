"""Single bounded runtime check in a previously prepared disposable sandbox."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('sandbox')
    parser.add_argument('--state', choices=('state', 'state-rollback'), default='state')
    parser.add_argument('--expected-version', required=True)
    args = parser.parse_args()
    root = Path(args.sandbox).resolve(strict=True)
    venv = root / 'venv'
    if not (root / 'wheel_manifest.json').is_file() or venv.is_symlink() or not venv.resolve().is_relative_to(root) or Path(sys.prefix).resolve() != venv.resolve():
        raise RuntimeError('requires a prepared sandbox and its own venv interpreter')
    import local_ai_hub
    from local_ai_hub.process_utils import find_listening_pid, popen_managed, process_identity, process_owner_state, process_parent_pid, terminate_tree
    if not Path(local_ai_hub.__file__).resolve().is_relative_to((root / 'venv').resolve()):
        raise RuntimeError('installed package does not belong to sandbox venv')
    state = root / args.state
    state.mkdir(exist_ok=True)
    if state.is_symlink() or state.resolve().parent != root:
        raise RuntimeError('sandbox state must be a direct physical child of the sandbox')
    for role in ('supervisor', 'hub'):
        owner_path = state / (role + '.owner.json')
        if owner_path.exists():
            owner = json.loads(owner_path.read_text(encoding='utf-8'))
            if process_owner_state(owner, state, role) != 'stale':
                raise RuntimeError('sandbox state has a live or unverified owner')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    token = secrets.token_urlsafe(32)
    config = root / ('smoke-' + args.state + '-' + str(port) + '.toml')
    with config.open('x', encoding='utf-8') as output:
        output.write('[server]\nbind = "127.0.0.1"\nport = ' + str(port) + '\nstate_dir = ' + json.dumps(str(state)) + '\nauto_start_ollama = false\n[security]\napi_token = ' + json.dumps(token) + '\n[ollama]\nenabled = false\n[llama_cpp]\nenabled = false\n[code_intelligence]\nenabled = false\nserena_enabled = false\npreprocess_serena = false\n[headless]\nmanage_ollama = false\n[resilience]\nwatchdog_enabled = false\n[setup]\ninstall_dir = ' + json.dumps(str(root / 'install')) + '\n')
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    evidence = {'state':str(state), 'port':port, 'package_version':importlib.metadata.version('local-ai-hub'), 'package_path':str(Path(local_ai_hub.__file__).resolve()), 'runtime_acceptance':False}
    with (root / 'sandbox-supervisor.log').open('ab') as log:
        process = popen_managed([sys.executable, '-m', 'local_ai_hub.supervisor', '--config', str(config)], cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            time.sleep(8)
            if process.poll() is not None:
                raise RuntimeError('supervisor exited before check')
            request = Request(f'http://127.0.0.1:{port}/api/status', headers={'Authorization':'Bearer '+token})
            with urlopen(request, timeout=10) as response:
                status = json.load(response)
            supervisor_owner = json.loads((state/'supervisor.owner.json').read_text(encoding='utf-8'))
            hub_owner = json.loads((state/'hub.owner.json').read_text(encoding='utf-8'))
            hub_pid = int((state/'hub.pid').read_text(encoding='utf-8'))
            listener_pid = find_listening_pid(port)
            listener_identity = process_identity(listener_pid) if listener_pid is not None else None
            if process_owner_state(supervisor_owner, state, 'supervisor') != 'owned' or process_owner_state(hub_owner, state, 'hub') != 'owned':
                raise RuntimeError('process ownership could not be verified')
            if not listener_identity or (listener_pid != hub_owner['pid'] and process_parent_pid(listener_pid) != hub_owner['pid']):
                raise RuntimeError('listener identity or parent does not match Hub owner')
            evidence.update({'version':status.get('version'), 'online':status.get('hub_online'), 'supervisor':supervisor_owner, 'hub_owner':hub_owner, 'hub_pid_file':hub_pid, 'listener':listener_identity, 'listener_binding_verified':True})
            if status.get('hub_online') is not True or status.get('version') != args.expected_version or evidence['package_version'] != args.expected_version:
                raise RuntimeError('runtime/version mismatch')
        finally:
            evidence['process_tree_terminated'] = terminate_tree(process.pid, process_handle=process, grace_seconds=3)
            path = root / ('smoke-result-' + args.state + '-' + str(port) + '.json')
            with path.open('x', encoding='utf-8') as output:
                output.write(json.dumps(evidence, ensure_ascii=False, indent=2)+'\n')
            print(path)
            if not evidence['process_tree_terminated']:
                raise RuntimeError('sandbox process tree cleanup not confirmed')

if __name__ == '__main__':
    main()

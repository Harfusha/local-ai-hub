"""Start a disposable Hub and correlate a task through MCP and HTTP."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from urllib.request import Request, urlopen


async def mcp_call(python, root, env, arguments):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(command=python, args=['-m', 'local_ai_hub.mcp_server'], cwd=root, env=env)
    async with stdio_client(params) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            return await session.call_tool('local_ai_coord', arguments)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('sandbox')
    parser.add_argument('--task-id', default='')
    parser.add_argument('--no-wait', action='store_true', help='stop after recording MCP and HTTP evidence')
    args = parser.parse_args()
    if args.task_id and not re.fullmatch(r'task_[0-9a-f]{12}', args.task_id):
        raise ValueError('invalid task ID')
    root = Path(args.sandbox).resolve(strict=True)
    venv = root / 'venv'
    workspace = root / 'workspace'
    state = root / 'state'
    if Path(sys.prefix).resolve() != venv.resolve() or venv.is_symlink() or not venv.resolve().is_relative_to(root):
        raise RuntimeError('use this sandbox venv interpreter')
    if not workspace.is_dir() or workspace.is_symlink() or workspace.resolve().parent != root:
        raise RuntimeError('workspace must be a direct physical sandbox child')
    state.mkdir(exist_ok=True)
    if state.is_symlink() or state.resolve().parent != root:
        raise RuntimeError('state must be a direct physical sandbox child')
    import local_ai_hub
    if not Path(local_ai_hub.__file__).resolve().is_relative_to(venv.resolve()):
        raise RuntimeError('installed package does not belong to sandbox venv')
    from local_ai_hub.process_utils import find_listening_pid, popen_managed, process_identity, process_owner_state, process_parent_pid, terminate_tree
    for role in ('supervisor', 'hub'):
        owner_path = state / (role + '.owner.json')
        if owner_path.exists() and process_owner_state(json.loads(owner_path.read_text(encoding='utf-8')), state, role) != 'stale':
            raise RuntimeError('state has an active or unverified owner')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    config = root / ('config-' + str(port) + '.toml')
    with config.open('x', encoding='utf-8') as stream:
        stream.write('[server]\nbind = "127.0.0.1"\nport = ' + str(port) + '\nstate_dir = ' + json.dumps(str(state)) + '\nauto_start_ollama = false\n[security]\napi_token = ""\nallowed_roots = [' + json.dumps(str(workspace)) + ']\n[ollama]\nenabled = false\n[llama_cpp]\nenabled = false\n[code_intelligence]\nenabled = false\nserena_enabled = false\npreprocess_serena = false\n[headless]\nmanage_ollama = false\n[resilience]\nwatchdog_enabled = false\n[setup]\ninstall_dir = ' + json.dumps(str(root/'install')) + '\n')
    env = dict(os.environ, LOCAL_AI_CONFIG=str(config))
    env.pop('PYTHONPATH', None)
    with (root/'supervisor.log').open('ab') as log:
        process = popen_managed([sys.executable, '-m', 'local_ai_hub.supervisor', '--config', str(config)], cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            time.sleep(8)
            if process.poll() is not None:
                raise RuntimeError('supervisor exited before check')
            supervisor_owner = json.loads((state/'supervisor.owner.json').read_text(encoding='utf-8'))
            hub_owner = json.loads((state/'hub.owner.json').read_text(encoding='utf-8'))
            listener = find_listening_pid(port)
            if (process_owner_state(supervisor_owner, state, 'supervisor') != 'owned'
                    or process_owner_state(hub_owner, state, 'hub') != 'owned'
                    or listener is None
                    or (listener != hub_owner['pid'] and process_parent_pid(listener) != hub_owner['pid'])):
                raise RuntimeError('sandbox listener ownership could not be verified')
            listener_identity = process_identity(listener)
            if not listener_identity:
                raise RuntimeError('sandbox listener identity is unavailable')
            if args.task_id:
                arguments = {'action':'task_checkpoint','root':str(workspace),'task_id':args.task_id,'checkpoint':{'phase':'sandbox-ready','next_action':'Inspect same task across interfaces','affected_paths':[],'evidence_ids':[],'blockers':['Authentic receipt producer not yet established'],'state_data':{}},'max_response_tokens':2400}
            else:
                arguments = {'action':'task_create','root':str(workspace),'goal':'Verify isolated cross-interface workflow','acceptance_criteria':['An authentic validation receipt is present'],'max_response_tokens':2400}
            result = asyncio.run(asyncio.wait_for(mcp_call(sys.executable, root, env, arguments), timeout=30))
            data = result.structuredContent
            if not isinstance(data, dict) or data.get('success') is not True:
                raise RuntimeError('MCP task action failed: ' + str(data))
            task_id = data.get('task_id') or data.get('task', {}).get('task_id')
            if not isinstance(task_id, str) or not re.fullmatch(r'task_[0-9a-f]{12}', task_id):
                raise RuntimeError('successful MCP response omitted task identity; do not repeat create')
            evidence = {'task_id':task_id,'port':port,'supervisor':supervisor_owner,'hub_owner':hub_owner,'listener':listener_identity,'mcp':data,'runtime_acceptance':False}
            evidence_path = root / ('identity-' + task_id + '-' + str(port) + '.json')
            with evidence_path.open('x', encoding='utf-8') as output:
                json.dump(evidence, output, ensure_ascii=False, indent=2)
            payload = json.dumps({'action':'get','root':str(workspace),'task_id':task_id,'response_budget_tokens':2400}).encode('utf-8')
            request = Request(f'http://127.0.0.1:{port}/api/agent-state/tasks', data=payload, headers={'Content-Type':'application/json'}, method='POST')
            with urlopen(request, timeout=10) as response:
                http = json.load(response)
            if http.get('success') is not True or http.get('task',{}).get('task_id') != task_id:
                raise RuntimeError('HTTP did not return the MCP task')
            evidence['http'] = http
            evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'task_id':task_id,'dashboard':f'http://127.0.0.1:{port}/dashboard','evidence':str(evidence_path)}), flush=True)
            if not args.no_wait:
                input('Inspect the task in the dashboard, then press Enter to stop the sandbox.\n')
        finally:
            stopped = terminate_tree(process.pid, process_handle=process, grace_seconds=3)
            print('sandbox_tree_terminated:', stopped, flush=True)
            if not stopped:
                raise RuntimeError('sandbox process tree cleanup not confirmed')

if __name__ == '__main__':
    main()

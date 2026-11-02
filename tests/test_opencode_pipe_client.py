from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_client_decodes_fragmented_frames_and_acknowledges():
    script = r'''
const assert=require('node:assert/strict'),net=require('node:net'),http=require('node:http');
const {createBridge}=require('./tools/opencode_pipe_client.cjs');
(async()=>{
 let received=Buffer.alloc(0),ack=false;
 const host=net.createServer(s=>{s.on('data',data=>{received=Buffer.concat([received,data]);
  if(!ack&&received.includes(Buffer.from('GET /health'))){ack=true;
   const body=Buffer.from('HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nok');const frame=Buffer.alloc(4);frame.writeUInt32BE(body.length);
   s.write(frame.subarray(0,2));s.write(Buffer.concat([frame.subarray(2),body]));s.write(Buffer.alloc(4));
  }
  if(received.at(-1)===6)s.end();
 })});
 await new Promise(r=>host.listen(0,'127.0.0.1',r));
 const bridge=createBridge({secret:Buffer.alloc(32,120),connectPipe:()=>net.connect(host.address().port,'127.0.0.1'),timeoutMs:3000});
 await new Promise(r=>bridge.listen(0,'127.0.0.1',r));
 const body=await new Promise((resolve,reject)=>{http.get({host:'127.0.0.1',port:bridge.address().port,path:'/health'},r=>{let x='';r.on('data',d=>x+=d);r.on('end',()=>resolve(x));}).on('error',reject)});
 assert.equal(body,'ok');await new Promise(r=>setTimeout(r,50));assert.equal(received.subarray(0,32).toString(),'x'.repeat(32));assert.equal(received.at(-1),6);
 await new Promise(r=>bridge.close(r));await new Promise(r=>host.close(r));
})().catch(e=>{console.error(e);process.exitCode=1});
'''
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr


def test_client_rejects_invalid_framing_and_configuration():
    script = r'''
const assert=require('node:assert/strict'),net=require('node:net');
const {createBridge,validatePipeName}=require('./tools/opencode_pipe_client.cjs');
assert.throws(()=>validatePipeName('\\\\.\\pipe\\other'));
assert.throws(()=>createBridge({secret:Buffer.alloc(31),connectPipe:()=>{}}));
(async()=>{
 const host=net.createServer(s=>s.once('data',()=>{const bad=Buffer.alloc(4);bad.writeUInt32BE(65537);s.write(bad)}));
 await new Promise(r=>host.listen(0,'127.0.0.1',r));
 const bridge=createBridge({secret:Buffer.alloc(32),connectPipe:()=>net.connect(host.address().port,'127.0.0.1'),timeoutMs:2000});
 await new Promise(r=>bridge.listen(0,'127.0.0.1',r));
 const client=net.connect(bridge.address().port,'127.0.0.1');
 const got=[];client.on('data',x=>got.push(x));await new Promise(resolve=>{client.on('error',resolve);client.on('close',resolve)});
 assert.equal(Buffer.concat(got).length,0);await new Promise(r=>bridge.close(r));await new Promise(r=>host.close(r));
})().catch(e=>{console.error(e);process.exitCode=1});
'''
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr


def test_concurrent_requests_wait_for_exclusive_pipe():
    script = r'''
const assert=require('node:assert/strict'),net=require('node:net'),http=require('node:http');
const {createBridge}=require('./tools/opencode_pipe_client.cjs');
(async()=>{
 let active=0,overlap=false;
 const host=net.createServer(s=>{if(++active>1)overlap=true;let received=Buffer.alloc(0),sent=false;
  s.on('data',data=>{received=Buffer.concat([received,data]);
   if(!sent&&received.includes(Buffer.from('GET '))){sent=true;setTimeout(()=>{
    const body=Buffer.from('HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nok'),frame=Buffer.alloc(4);frame.writeUInt32BE(body.length);s.write(Buffer.concat([frame,body,Buffer.alloc(4)]));
   },50)}
   if(sent&&received.at(-1)===6)s.end();
  });s.on('close',()=>active--);
 });
 await new Promise(r=>host.listen(0,'127.0.0.1',r));
 const bridge=createBridge({secret:Buffer.alloc(32),connectPipe:()=>net.connect(host.address().port,'127.0.0.1'),timeoutMs:3000});
 await new Promise(r=>bridge.listen(0,'127.0.0.1',r));
 const request=()=>new Promise((resolve,reject)=>http.get({host:'127.0.0.1',port:bridge.address().port,agent:false},r=>{let body='';r.on('data',d=>body+=d);r.on('end',()=>resolve(body))}).on('error',reject));
 assert.deepEqual(await Promise.all([request(),request(),request()]),['ok','ok','ok']);
 await new Promise(r=>bridge.close(r));await new Promise(r=>host.close(r));
 assert.equal(overlap,false);
})().catch(e=>{console.error(e);process.exitCode=1});
'''
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr


def test_cancelled_queued_request_does_not_block_following_request():
    script = r'''
const assert=require('node:assert/strict'),net=require('node:net'),http=require('node:http');
const {createBridge}=require('./tools/opencode_pipe_client.cjs');
(async()=>{
 let accepted=0;
 const host=net.createServer(s=>{accepted++;let sent=false;s.on('data',data=>{
  if(!sent&&data.includes(Buffer.from('GET '))){sent=true;setTimeout(()=>{const body=Buffer.from('HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nok'),frame=Buffer.alloc(4);frame.writeUInt32BE(body.length);s.write(Buffer.concat([frame,body,Buffer.alloc(4)]))},150)}
  else if(sent&&data.includes(Buffer.from([6])))s.end();
 })});
 await new Promise(r=>host.listen(0,'127.0.0.1',r));
 const bridge=createBridge({secret:Buffer.alloc(32),connectPipe:()=>net.connect(host.address().port,'127.0.0.1'),timeoutMs:2000});
 await new Promise(r=>bridge.listen(0,'127.0.0.1',r));
 const request=()=>new Promise((resolve,reject)=>http.get({host:'127.0.0.1',port:bridge.address().port,agent:false},r=>{let body='';r.on('data',d=>body+=d);r.on('end',()=>resolve(body))}).on('error',reject));
 const first=request();await new Promise(r=>setTimeout(r,30));
 const canceled=net.connect(bridge.address().port,'127.0.0.1');canceled.on('error',()=>{});await new Promise(r=>canceled.once('connect',r));canceled.destroy();
 await new Promise(r=>setTimeout(r,30));const last=request();
 assert.deepEqual(await Promise.all([first,last]),['ok','ok']);
 await new Promise(r=>bridge.close(r));await new Promise(r=>host.close(r));assert.equal(accepted,2);
})().catch(e=>{console.error(e);process.exit(1)});
'''
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=8, check=False)
    assert result.returncode == 0, result.stderr


def test_failed_ack_write_destroys_pipe_instead_of_marking_success():
    script = r'''
const assert=require('node:assert/strict'),net=require('node:net'),EventEmitter=require('node:events');
const {createBridge}=require('./tools/opencode_pipe_client.cjs');
(async()=>{
 let destroyed=false,ended=false;const pipe=new EventEmitter();
 pipe.write=(data,cb)=>{if(data.length===1&&data[0]===6)setImmediate(()=>cb(Error('ack failed')));
 else if(data.includes(Buffer.from('GET '))){const body=Buffer.from('HTTP/1.0 200 OK\r\nContent-Length: 0\r\n\r\n');const header=Buffer.alloc(4);header.writeUInt32BE(body.length);setImmediate(()=>pipe.emit('data',Buffer.concat([header,body,Buffer.alloc(4)])))}return true};
 pipe.destroy=()=>{if(!destroyed){destroyed=true;setImmediate(()=>pipe.emit('close'))}};pipe.end=()=>{ended=true};pipe.pause=()=>{};pipe.resume=()=>{};
 const bridge=createBridge({secret:Buffer.alloc(32),connectPipe:()=>{setImmediate(()=>pipe.emit('connect'));return pipe},timeoutMs:1000});
 await new Promise(r=>bridge.listen(0,'127.0.0.1',r));const c=net.connect(bridge.address().port,'127.0.0.1');c.on('error',()=>{});
 c.on('connect',()=>c.write('GET /health HTTP/1.0\r\n\r\n'));await new Promise(r=>setTimeout(r,100));
 c.destroy();await new Promise(r=>bridge.close(r));assert.equal(destroyed,true);assert.equal(ended,false);
})().catch(e=>{console.error(e);process.exit(1)});
'''
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=5, check=False)
    assert result.returncode == 0, result.stderr

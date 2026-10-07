import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {coworkerKeyFromEnv,dataDir,isHosted,mpsRuntimeToken} from './runtime-env.mjs';
import {coworkerApiKey} from './sokosumi-runtime.mjs';
import {graphBaseUrl} from './client.mjs';
import {listenAddress} from './agent-api.mjs';
import {parseWorkerTargets,routeTasks} from './worker-targets.mjs';
const ORG='01a109d1-32a9-71a3-a0e3-658b2a7987cd',CW='cw-1';

test('DATA_DIR defaults to .local and follows the env',()=>{
 assert.equal(dataDir({}),'.local');assert.equal(dataDir({DATA_DIR:'  '}),'.local');
 assert.equal(dataDir({DATA_DIR:'/data'}),'/data');
});

test('MPS runtime token: env wins, else DATA_DIR/mps-runtime.env, else undefined',()=>{
 const dir=mkdtempSync(join(tmpdir(),'deploy-'));
 try{
  assert.equal(mpsRuntimeToken({DATA_DIR:dir}),undefined);
  writeFileSync(join(dir,'mps-runtime.env'),'MPS_RUNTIME_TOKEN=from-file\n');
  assert.equal(mpsRuntimeToken({DATA_DIR:dir}),'from-file');
  assert.equal(mpsRuntimeToken({DATA_DIR:dir,MPS_RUNTIME_TOKEN:'from-env'}),'from-env');
 }finally{rmSync(dir,{recursive:true})}
});

test('coworkerApiKey prefers SOKOSUMI_COWORKER_API_KEY, else the OS vault credential',async()=>{
 let vaultReads=0;const load=async()=>({readRuntimeCredential:id=>{vaultReads++;return `vault-${id}`}});
 assert.equal(await coworkerApiKey({SOKOSUMI_COWORKER_API_KEY:' coworker_env ',COWORKER_ID:'c'},load),'coworker_env');
 assert.equal(vaultReads,0);
 assert.equal(await coworkerApiKey({COWORKER_ID:'c'},load),'vault-c');
 assert.equal(coworkerKeyFromEnv({SOKOSUMI_COWORKER_API_KEY:''}),undefined);
});

test('CREST_GRAPH_URL is strict loopback unless HOSTED=1',()=>{
 assert.equal(graphBaseUrl({}),'http://127.0.0.1:21951');
 assert.throws(()=>graphBaseUrl({CREST_GRAPH_URL:'http://graph.railway.internal:8080'}),/127\.0\.0\.1/);
 assert.throws(()=>graphBaseUrl({CREST_GRAPH_URL:'http://localhost:21951'}),/127\.0\.0\.1/);
 const hosted={HOSTED:'1'};
 assert.equal(isHosted(hosted),true);assert.equal(isHosted({HOSTED:'0'}),false);
 assert.equal(graphBaseUrl({...hosted,CREST_GRAPH_URL:'http://graph.railway.internal:8080'}),'http://graph.railway.internal:8080');
 assert.equal(graphBaseUrl({...hosted,CREST_GRAPH_URL:'https://graph-x.up.railway.app'}),'https://graph-x.up.railway.app');
 for(const bad of ['ftp://graph:21','http://u:p@graph:8080','http://graph:8080/path','http://graph:8080/?q=1'])
  assert.throws(()=>graphBaseUrl({...hosted,CREST_GRAPH_URL:bad}),/origin/);
});

test('agent-api binds loopback by default; AGENT_API_HOST and PORT override',()=>{
 assert.deepEqual(listenAddress({}),{host:'127.0.0.1',port:21950});
 assert.deepEqual(listenAddress({AGENT_API_PORT:'32123'}),{host:'127.0.0.1',port:32123});
 assert.deepEqual(listenAddress({AGENT_API_HOST:'0.0.0.0',PORT:'8080'}),{host:'0.0.0.0',port:8080});
 assert.throws(()=>listenAddress({PORT:'nope'}),/integer/);
});

test('coworker-key listing maps organizationId null to personal and org ids to org targets',()=>{
 const targets=parseWorkerTargets();
 const skipped=[];
 const tasks=[{id:'p',coworkerId:CW,organizationId:null},{id:'o',coworkerId:CW,organizationId:ORG},
  {id:'u',coworkerId:null,organizationId:null},{id:'x',coworkerId:'other',organizationId:null},
  {id:'z',coworkerId:CW,organizationId:'unknown-org'},{id:'p',coworkerId:CW,organizationId:ORG},{id:null}];
 const got=routeTasks(tasks,targets,CW,t=>skipped.push(t.id));
 assert.deepEqual(got.map(({task,target})=>[task.id,target.kind]),[['p','personal'],['o','org'],['u','personal']]);
 assert.deepEqual(got.find(r=>r.task.id==='o').target.runtimeArgs,['--organization-id',ORG]);
 assert.deepEqual(got.find(r=>r.task.id==='p').target.runtimeArgs,['--personal']);
 assert.deepEqual(skipped,['z']);
 // Personal-only targets skip org Tasks.
 assert.deepEqual(routeTasks(tasks,parseWorkerTargets('personal'),CW).map(r=>r.task.id),['p','u']);
});

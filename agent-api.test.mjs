import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createServer} from 'node:http';
import {createAgentApi,schema,STAGES,validateInputData,jobPrompt,normalizeStage} from './agent-api.mjs';
import {inputHash} from './standard-hash.mjs';

const NONCE='aabbccddeeff0011';
async function withApi(options,fn){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'agent-api-test-'));
 const api=createAgentApi({jobsDir:dir,registry:()=>({registrationState:'RegistrationConfirmed',agentIdentifier:'agent-1',sellerVkey:'vkey-1',supportedPaymentSourceIndex:0}),...options});
 const server=createServer(api.handler);await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const base=`http://127.0.0.1:${server.address().port}`;
 try{await fn({base,api,dir})}finally{await new Promise(r=>server.close(r));fs.rmSync(dir,{recursive:true,force:true})}
}
const t0=Date.parse('2026-10-07T00:00:00Z');
const paymentFor=body=>({blockchainIdentifier:'bc-1',payByTime:String(Date.parse(body.payByTime)),submitResultTime:String(Date.parse(body.submitResultTime)),unlockTime:String(Date.parse(body.unlockTime)),externalDisputeUnlockTime:String(Date.parse(body.externalDisputeUnlockTime))});
const startJob=(base,input_data,nonce=NONCE)=>fetch(`${base}/start_job`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({identifier_from_purchaser:nonce,input_data})});

test('input_schema follows MIP-003 input_data format with stage and brief',async()=>{
 await withApi({},async({base})=>{
 const res=await fetch(`${base}/input_schema`);assert.equal(res.status,200);
 const body=await res.json();assert.deepEqual(body,schema);
 assert.deepEqual(Object.keys(body),['input_data']);
 const [stage,brief]=body.input_data;
 assert.equal(stage.id,'stage');assert.equal(stage.type,'option');assert.equal(typeof stage.name,'string');
 assert.deepEqual(stage.data.values,['create','schedule','engage','analyze']);
 assert.deepEqual(stage.validations,[{validation:'min',value:'1'},{validation:'max',value:'1'}]);
 assert.equal(brief.id,'brief');assert.equal(brief.type,'textarea');assert.equal(typeof brief.name,'string');
 assert.ok(brief.validations.some(v=>v.validation==='max'&&v.value==='8000'));
 assert.ok(!body.input_data.some(f=>f.validations?.some(v=>v.validation==='optional')),'all fields required');
 for(const f of body.input_data)for(const v of f.validations??[])assert.equal(typeof v.value,'string');
 assert.equal(new Set(body.input_data.map(f=>f.id)).size,body.input_data.length);
 });
});

test('availability reports masumi-agent',async()=>{
 await withApi({},async({base})=>{
 const body=await (await fetch(`${base}/availability`)).json();
 assert.equal(body.status,'available');assert.equal(body.type,'masumi-agent');
 });
});

test('input validation accepts stage forms and legacy prompt, rejects bad input',()=>{
 for(const s of STAGES)assert.equal(validateInputData({stage:s,brief:'x'}),null);
 assert.equal(validateInputData({stage:['engage'],brief:'x'}),null);
 assert.equal(validateInputData({stage:[3],brief:'x'}),null);
 assert.equal(normalizeStage([3]),'analyze');assert.equal(normalizeStage('Create'),'create');
 assert.equal(validateInputData({prompt:'legacy'}),null);
 assert.match(validateInputData({stage:'publish',brief:'x'}),/stage/);
 assert.match(validateInputData({stage:['create','engage'],brief:'x'}),/stage/);
 assert.match(validateInputData({stage:'create',brief:'   '}),/brief/);
 assert.match(validateInputData({stage:'create',brief:'x'.repeat(8001)}),/brief/);
 assert.equal(validateInputData({stage:'create',brief:'x'.repeat(8000)}),null);
 assert.match(validateInputData({stage:'create'}),/brief/);
 assert.match(validateInputData({stage:'create',brief:'x',extra:1}),/only/);
 assert.match(validateInputData({prompt:'a',stage:'create',brief:'x'}),/only/);
 assert.match(validateInputData(null),/object/);
});

test('jobPrompt routes stage and keeps legacy prompt',()=>{
 assert.equal(jobPrompt({stage:'schedule',brief:'Plan next week'}),'[stage:schedule] Plan next week');
 assert.equal(jobPrompt({stage:[1],brief:'b'}),'[stage:schedule] b');
 assert.equal(jobPrompt({prompt:'old job'}),'old job');
});

test('start_job returns input_hash and inputHash, status accepts job_id and jobId, stage routes to answer',async()=>{
 const calls=[];const answers=[];let resolveState='FundsLocked';
 const mps=async(p,body)=>{calls.push(p);
 if(p==='/payment')return paymentFor(body);
 if(p==='/payment/resolve-blockchain-identifier')return {blockchainIdentifier:'bc-1',onChainState:resolveState,submitResultTime:String(t0+20*60000),CurrentTransaction:{status:'Confirmed',newOnChainState:resolveState},resultHash:undefined};
 if(p==='/payment/submit-result')return {};
 throw new Error('unexpected '+p);
 };
 const answer=async(input,journal,deadline)=>{answers.push({input,deadline});return 'Drafted 3 posts';};
 await withApi({mps,answer,now:()=>t0},async({base,api})=>{
 const input_data={stage:'create',brief:'Launch week posts for @nova'};
 const res=await startJob(base,input_data);assert.equal(res.status,200);
 const body=await res.json();
 const expected=inputHash(input_data,NONCE);
 assert.equal(body.input_hash,expected);assert.equal(body.inputHash,expected);
 assert.equal(body.identifierFromPurchaser,NONCE);assert.equal(body.blockchainIdentifier,'bc-1');
 assert.equal(body.agentIdentifier,'agent-1');assert.equal(body.sellerVKey,'vkey-1');
 for(const k of ['payByTime','submitResultTime','unlockTime','externalDisputeUnlockTime'])assert.equal(typeof body[k],'number');

 for(const q of [`job_id=${body.id}`,`jobId=${body.id}`]){
 const s=await fetch(`${base}/status?${q}`);assert.equal(s.status,200);
 const sb=await s.json();assert.equal(sb.id,body.id);assert.equal(sb.status,'awaiting_payment');assert.equal(sb.result,undefined);
 }
 assert.equal((await fetch(`${base}/status`)).status,400);
 assert.equal((await fetch(`${base}/status?jobId=00000000-0000-0000-0000-000000000000`)).status,404);

 // Replay with same nonce and input is idempotent and keeps both hash spellings.
 const replay=await (await startJob(base,input_data)).json();
 assert.equal(replay.id,body.id);assert.equal(replay.inputHash,expected);
 assert.equal((await startJob(base,{stage:'engage',brief:'other'})).status,409);

 await api.tick();
 assert.deepEqual(answers.map(a=>a.input),['[stage:create] Launch week posts for @nova']);
 assert.ok(calls.includes('/payment/submit-result'));
 const running=await (await fetch(`${base}/status?jobId=${body.id}`)).json();
 assert.equal(running.status,'running');
 });
});

test('start_job rejects schema violations with 400',async()=>{
 await withApi({mps:async()=>{throw new Error('must not be called')}},async({base})=>{
 assert.equal((await startJob(base,{stage:'publish',brief:'x'})).status,400);
 assert.equal((await startJob(base,{stage:'create',brief:'x'.repeat(8001)})).status,400);
 assert.equal((await startJob(base,{stage:'create',brief:'ok'},'not-hex')).status,400);
 const bad=await fetch(`${base}/start_job`,{method:'POST',body:'{not json'});assert.equal(bad.status,400);
 });
});

test('legacy prompt job still runs the prompt verbatim',async()=>{
 const answers=[];
 const mps=async(p,body)=>p==='/payment'?paymentFor(body):p==='/payment/resolve-blockchain-identifier'?{onChainState:'FundsLocked',submitResultTime:String(t0+20*60000),CurrentTransaction:{status:'Confirmed',newOnChainState:'FundsLocked'}}:{};
 await withApi({mps,answer:async i=>{answers.push(i);return 'ok'},now:()=>t0},async({base,api})=>{
 const body=await (await startJob(base,{prompt:'Old style brief'})).json();
 assert.equal(body.inputHash,inputHash({prompt:'Old style brief'},NONCE));
 await api.tick();assert.deepEqual(answers,['Old style brief']);
 });
});

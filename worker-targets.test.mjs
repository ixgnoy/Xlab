import test from 'node:test';
import assert from 'node:assert/strict';
import {DEFAULT_WORKER_TARGETS,collectTasks,parseTarget,parseWorkerTargets,resolveTaskTarget,wantsPayment} from './worker-targets.mjs';
const ORG='01a109d1-32a9-71a3-a0e3-658b2a7987cd',SLUG='token2049-origins-hackathon-2026-nws2r7',CW='cw-1';

test('default targets are personal plus the TOKEN2049 organization',()=>{
 for(const value of [undefined,'','  ']){
  const [p,o]=parseWorkerTargets(value);
  assert.deepEqual(p.runtimeArgs,['--personal']);assert.deepEqual(p.listArgs,[]);assert.equal(p.organizationId,null);
  assert.equal(o.kind,'org');assert.deepEqual(o.listArgs,['--organization-slug',SLUG]);assert.deepEqual(o.runtimeArgs,['--organization-id',ORG]);
 }
 assert.equal(parseWorkerTargets(DEFAULT_WORKER_TARGETS).length,2);
});

test('org runtime args never include --personal and personal never includes org flags',()=>{
 for(const t of parseWorkerTargets()){
  const flags=[...t.listArgs,...t.runtimeArgs];
  assert.ok(!(flags.includes('--personal')&&(flags.includes('--organization-id')||flags.includes('--organization-slug'))));
 }
});

test('parses custom lists, dedupes, and rejects bad entries',()=>{
 assert.deepEqual(parseWorkerTargets('personal, personal').map(t=>t.kind),['personal']);
 assert.deepEqual(parseWorkerTargets(`org:${ORG}:${SLUG}`).map(t=>t.kind),['org']);
 assert.throws(()=>parseTarget('org:onlyid'),/Invalid WORKER_TARGETS/);
 assert.throws(()=>parseTarget('workspace'),/Invalid WORKER_TARGETS/);
 assert.throws(()=>parseTarget(`org:${ORG}:bad slug!`),/Invalid/);
 assert.throws(()=>parseWorkerTargets(','),/no targets/);
});

test('collectTasks filters by coworker and organization, dedupes by id, survives a failing target',()=>{
 const targets=parseWorkerTargets();
 const lists={personal:[{id:'a',coworkerId:CW,organizationId:null},{id:'x',coworkerId:'other',organizationId:null},{id:'o2',coworkerId:CW,organizationId:ORG}],
  org:[{id:'b',coworkerId:CW,organizationId:ORG},{id:'a',coworkerId:CW,organizationId:null}]};
 const got=collectTasks(targets,t=>lists[t.kind],CW);
 assert.deepEqual(got.map(({task,target})=>[task.id,target.kind]),[['a','personal'],['b','org']]);
 const errors=[];
 const partial=collectTasks(targets,t=>{if(t.kind==='personal')throw new Error('down');return lists.org;},CW,(t,e)=>errors.push([t.kind,e.message]));
 assert.deepEqual(partial.map(r=>r.task.id),['b']);assert.deepEqual(errors,[['personal','down']]);
});

test('resumed Tasks reuse the journal target; legacy journals are personal',()=>{
 const [personal,org]=parseWorkerTargets();
 assert.equal(resolveTaskTarget({phase:'started',target:org.spec},personal).kind,'org');
 assert.deepEqual(resolveTaskTarget({phase:'result-saved',target:org.spec},personal).runtimeArgs,['--organization-id',ORG]);
 assert.equal(resolveTaskTarget({phase:'started'},org).kind,'personal');
 assert.equal(resolveTaskTarget({},org),org);
});
test('payment: personal when enabled; organization only with PAID_ORG_TASKS and a [paid] title',()=>{
 const personal=parseTarget('personal'),org=parseTarget('org:o1:token2049');
 const on={PAID_TASKS_ENABLED:'true'},both={PAID_TASKS_ENABLED:'true',PAID_ORG_TASKS:'true'};
 assert.equal(wantsPayment({name:'x'},personal,on),true);
 assert.equal(wantsPayment({name:'x'},personal,{}),false);
 assert.equal(wantsPayment({name:'Trends [paid]'},org,on),false);
 assert.equal(wantsPayment({name:'Trends'},org,both),false);
 assert.equal(wantsPayment({name:'Trends [PAID]'},org,both),true);
 assert.equal(wantsPayment({name:'Trends [paid]'},org,{PAID_ORG_TASKS:'true'}),false);
});

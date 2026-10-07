import {runSokosumi} from './sokosumi-cli.mjs';
import {existsSync,readFileSync,writeFileSync} from 'node:fs';
import {acquireWorkerLock} from './worker-lock.mjs';
import {answer,client} from './client.mjs';
import {reply} from './comments.mjs';
import {createPaidAdapter,isPaidReady} from './paid-task.mjs';
import {collectTasks,parseWorkerTargets,resolveTaskTarget} from './worker-targets.mjs';
const id=process.env.COWORKER_ID;
const targets=parseWorkerTargets();
const releaseLock=acquireWorkerLock();
process.once('exit',releaseLock);
for(const signal of ['SIGINT','SIGTERM'])process.once(signal,()=>{releaseLock();process.exit(0)});
function cli(args){return JSON.parse(runSokosumi(['--preprod',...args,'--json']));}
await client.health();
const paid=await createPaidAdapter({answer,save:async(taskId,state)=>writeFileSync(`.local/${taskId}.json`,JSON.stringify(state),{mode:0o600})});
console.log('Continuous worker running',process.pid,'targets',targets.map(t=>t.kind==='org'?`org:${t.slug}`:t.kind).join(','));
while(true){
 try{
 const polled=collectTasks(targets,target=>cli(['tasks','list',...target.listArgs,'--coworker-id',id]).tasks,id,(target,e)=>console.error('Polling read failed',target.spec,e.message.slice(0,200)));
 for(const {task:t,target:polledTarget} of polled){
 try{
 const journal=`.local/${t.id}.json`,resultFile=`.local/${t.id}.txt`;
 let state=existsSync(journal)?JSON.parse(readFileSync(journal,'utf8')):{};
 // Paid flow is personal-only; organization Tasks always take the unpaid path.
 const target=resolveTaskTarget(state,polledTarget);
 if(t.status==='READY'&&!state.phase){writeFileSync(journal,JSON.stringify({phase:'starting',target:target.spec}),{mode:0o600});const started=cli(['runtime','start',t.id,...target.runtimeArgs,'--coworker-id',id]);state={phase:'started',target:target.spec,input:started.description};writeFileSync(journal,JSON.stringify(state),{mode:0o600});}
 if(state.paid&&process.env.PAID_TASKS_ENABLED!=='true')continue;
 if(state.paid||(state.phase==='started'&&target.kind==='personal'&&process.env.PAID_TASKS_ENABLED==='true'&&isPaidReady())){state=await paid.advance(t,state);if(state.phase==='completed')await reply(t.id);continue;}
 if(state.phase==='started'){
 writeFileSync(journal,JSON.stringify({...state,phase:'model-pending'}),{mode:0o600});
 const result=await answer(state.input,`.local/${t.id}-session.json`);
 writeFileSync(resultFile,result,{mode:0o600});state={...state,phase:'result-saved'};writeFileSync(journal,JSON.stringify(state),{mode:0o600});
 }
 if(state.phase==='result-saved'){
 writeFileSync(journal,JSON.stringify({...state,phase:'complete-pending'}),{mode:0o600});
 const completed=cli(['runtime','complete',t.id,...target.runtimeArgs,'--coworker-id',id,'--result-file',resultFile]);
 writeFileSync(journal,JSON.stringify({...state,phase:'completed',completion:completed}),{mode:0o600});console.log('Completed',t.id);
 }
 if(state.phase==='completed')await reply(t.id);
 }catch(e){console.error('Task blocked',t.id,e.message.slice(0,200))}
 }
 }catch(e){console.error('Polling read failed',e.message.slice(0,200))}
 await new Promise(r=>setTimeout(r,5000));
}

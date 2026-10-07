// Workspace targets the worker polls. Human Task commands select an organization with --organization-slug;
// runtime start/complete select it with --organization-id. --personal is never combined with either.
export const DEFAULT_WORKER_TARGETS='personal,org:01a109d1-32a9-71a3-a0e3-658b2a7987cd:token2049-origins-hackathon-2026-nws2r7';
const SLUG=/^[a-z0-9][a-z0-9-]*$/i;
export function parseTarget(spec){
 const s=String(spec).trim();
 if(s==='personal')return {kind:'personal',spec:s,organizationId:null,listArgs:[],runtimeArgs:['--personal']};
 const m=/^org:([^:\s]+):([^:\s]+)$/.exec(s);
 if(!m)throw new Error(`Invalid WORKER_TARGETS entry "${s}". Use personal or org:ORG_ID:SLUG`);
 const [,organizationId,slug]=m;
 if(!SLUG.test(slug))throw new Error(`Invalid organization slug "${slug}"`);
 return {kind:'org',spec:s,organizationId,slug,listArgs:['--organization-slug',slug],runtimeArgs:['--organization-id',organizationId]};
}
export function parseWorkerTargets(value=process.env.WORKER_TARGETS){
 const raw=value===undefined||!String(value).trim()?DEFAULT_WORKER_TARGETS:String(value);
 const seen=new Set(),targets=[];
 for(const part of raw.split(',').map(p=>p.trim()).filter(Boolean)){
  const t=parseTarget(part);if(seen.has(t.spec))continue;seen.add(t.spec);targets.push(t);
 }
 if(!targets.length)throw new Error('WORKER_TARGETS selects no targets');
 return targets;
}
// The Task's own organizationId must match the target; runtime start rejects a mismatch anyway.
export function taskMatchesTarget(task,target){return (task.organizationId??null)===target.organizationId;}
// Polls every target, keeps this Coworker's Tasks that belong to that target, first target wins on duplicate IDs.
export function collectTasks(targets,listTasks,coworkerId,onError=()=>{}){
 const byId=new Map();
 for(const target of targets){
  let tasks;
  try{tasks=listTasks(target);}catch(e){onError(target,e);continue;}
  for(const t of tasks??[]){
   if(!t?.id||t.coworkerId!==coworkerId||!taskMatchesTarget(t,target)||byId.has(t.id))continue;
   byId.set(t.id,{task:t,target});
  }
 }
 return [...byId.values()];
}
// A resumed Task keeps the target recorded in its journal. Journals written before targets existed were personal.
export function resolveTaskTarget(state,polledTarget){
 if(state?.target)return parseTarget(state.target);
 return state?.phase?parseTarget('personal'):polledTarget;
}

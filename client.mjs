import {randomUUID} from 'node:crypto';
import {readFileSync,writeFileSync} from 'node:fs';
// Agent client: the PersonaLab LangGraph service (crest-graph) replaces eve. Same exported interface as before.
const base=()=>{const url=new URL(process.env.CREST_GRAPH_URL??'http://127.0.0.1:21951');if(url.protocol!=='http:'||url.hostname!=='127.0.0.1')throw new Error('CREST_GRAPH_URL must be http://127.0.0.1:PORT');return url.origin;};
const token=()=>{const t=process.env.CREST_GRAPH_TOKEN;if(!t)throw new Error('CREST_GRAPH_TOKEN is not configured');return t;};
async function run(input,threadId,timeoutMs=Number(process.env.CREST_GRAPH_TIMEOUT_MS??600000)){
 const response=await fetch(`${base()}/run`,{method:'POST',headers:{'content-type':'application/json',authorization:`Bearer ${token()}`},body:JSON.stringify({input,thread_id:threadId}),signal:AbortSignal.timeout(timeoutMs)});
 if(!response.ok)throw new Error(`Agent turn failed with HTTP ${response.status}`);
 const body=await response.json();
 if(typeof body.output!=='string'||!body.output.trim())throw new Error('Turn did not return a final answer');
 return body;
}
export const client={
 async health(){const r=await fetch(`${base()}/health`,{signal:AbortSignal.timeout(10000)});if(!r.ok)throw new Error('Agent service is not healthy');const h=await r.json();if(!h.model_configured)throw new Error('Agent service has no model configured');return h;},
};
export async function answer(input,journal,deadline){
 if(typeof input!=='string'||!input.trim()||input.length>16000) throw new Error('Input must contain 1 to 16000 characters');
 const sessionId=randomUUID();
 writeFileSync(journal,JSON.stringify({sessionId,phase:'sending'}),{mode:0o600});
 if(deadline!==undefined&&Date.now()>=deadline)throw new Error('Result deadline expired before model send');
 const {output}=await run(input,sessionId);
 writeFileSync(journal,JSON.stringify({sessionId,phase:'answered',result:output}),{mode:0o600});
 return output;
}
// Follow-up on a delivered Task: revise the saved result using the human's comment, in the same thread.
export async function followUp(journal,comment){
 const {sessionId,result}=JSON.parse(readFileSync(journal,'utf8'));
 if(typeof result!=='string')throw new Error('No delivered result to revise');
 const {output}=await run(`Revise or answer about your previous deliverable. Keep everything the user did not ask to change.\n\nPrevious deliverable:\n${result.slice(0,12000)}\n\nUser comment:\n${comment.slice(0,3500)}`,sessionId);
 return output;
}

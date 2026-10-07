import {createServer} from 'node:http';
import {randomUUID} from 'node:crypto';
import {existsSync,readFileSync,writeFileSync,mkdirSync,readdirSync} from 'node:fs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {answer as defaultAnswer} from './client.mjs';
import {inputHash,resultHash,sha256} from './standard-hash.mjs';
import {confirmedState} from './paid-task.mjs';
export async function mps(path,body){
 const response=await fetch(process.env.MPS_URL+'/api/v1'+path,{method:body?'POST':'GET',headers:{token:process.env.MPS_RUNTIME_TOKEN,'content-type':'application/json'},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(30000)});
 const data=await response.json();if(!response.ok)throw new Error(`Payment service HTTP ${response.status}`);return data.data;
}
// PersonaLab studio stages, in display order. Index order matters if a client submits option indices.
export const STAGES=['create','schedule','engage','analyze','trends','scripts'];
export const BRIEF_MAX=8000;
// MIP-003 input schema (Attachment 01 format). Fields are required unless marked `optional`.
export const schema={input_data:[
 {id:'stage',type:'option',name:'Studio stage',data:{values:STAGES,description:'Create: persona content drafts. Schedule: a posting calendar. Engage: comment and DM replies. Analyze: performance insights and next steps. Trends: what is hot on TikTok & Reels, with cited sources. Scripts: trend-based Reel/TikTok scripts.'},validations:[{validation:'min',value:'1'},{validation:'max',value:'1'}]},
 {id:'brief',type:'textarea',name:'Brief',data:{placeholder:'Persona, audience, goal, and any constraints or source material.',description:'What PersonaLab should do for your AI influencer in the chosen stage.'},validations:[{validation:'min',value:'1'},{validation:'max',value:String(BRIEF_MAX)},{validation:'format',value:'nonempty'}]},
]};
// Option fields may arrive as a value, a one-item array, or an index (form clients differ). Returns a stage name or null.
export function normalizeStage(raw){
 const v=Array.isArray(raw)?(raw.length===1?raw[0]:undefined):raw;
 if(typeof v==='string'){const s=v.trim().toLowerCase();return STAGES.includes(s)?s:null;}
 if(Number.isInteger(v)&&v>=0&&v<STAGES.length)return STAGES[v];
 return null;
}
// Returns null when valid, else an error string. Legacy {prompt} jobs stay accepted for backward compatibility.
export function validateInputData(data){
 if(!data||typeof data!=='object'||Array.isArray(data))return 'input_data must be an object';
 const keys=Object.keys(data);
 if(keys.length===1&&keys[0]==='prompt')return typeof data.prompt==='string'&&data.prompt.trim()&&data.prompt.length<=16000?null:'input_data.prompt must contain 1 to 16000 characters';
 if(keys.some(k=>k!=='stage'&&k!=='brief'))return 'input_data accepts only stage and brief';
 if(!normalizeStage(data.stage))return `input_data.stage must be one of ${STAGES.join(', ')}`;
 if(typeof data.brief!=='string'||!data.brief.trim()||data.brief.length>BRIEF_MAX)return `input_data.brief must contain 1 to ${BRIEF_MAX} characters`;
 return null;
}
// The text sent to the LangGraph service for a stored job input.
export function jobPrompt(input){
 if(typeof input?.prompt==='string'&&input.stage===undefined)return input.prompt;
 return `[stage:${normalizeStage(input.stage)}] ${input.brief}`;
}
const respond=(res,status,data)=>{res.writeHead(status,{'content-type':'application/json'});res.end(JSON.stringify(data))};
// Sokosumi reads camelCase inputHash; MIP-003 specifies input_hash. Return both, including on idempotent replays.
// MIP-003 sellerVKey: prefer the payment's own wallet, then the registry record shapes MPS returns.
export const sellerVkeyOf=(reg,payment)=>payment?.SmartContractWallet?.walletVkey??reg?.sellerVkey??reg?.registration?.SmartContractWallet?.walletVkey??reg?.request?.sellingWalletVkey;
const withHashAliases=r=>r.input_hash&&!r.inputHash?{...r,inputHash:r.input_hash}:r;
export function createAgentApi({jobsDir='.local/standard-jobs',answer=defaultAnswer,mps:callMps=mps,registry=()=>JSON.parse(readFileSync('docs/registration-state.json','utf8')),now=Date.now}={}){
 mkdirSync(jobsDir,{recursive:true,mode:0o700});
 const save=job=>writeFileSync(`${jobsDir}/${job.id}.json`,JSON.stringify(job),{mode:0o600});
 const load=id=>JSON.parse(readFileSync(`${jobsDir}/${id}.json`,'utf8'));
 const jobFiles=()=>readdirSync(jobsDir).filter(x=>/^[0-9a-f-]{36}\.json$/.test(x));
 async function handler(req,res){
 try{
 const url=new URL(req.url,'http://127.0.0.1');
 if(req.method==='GET'&&url.pathname==='/availability')return respond(res,200,{status:'available',type:'masumi-agent',message:'PersonaLab is ready to accept jobs'});
 if(req.method==='GET'&&url.pathname==='/input_schema')return respond(res,200,schema);
 if(req.method==='GET'&&url.pathname==='/status'){
 const id=url.searchParams.get('job_id')??url.searchParams.get('jobId');if(!/^[0-9a-f-]{36}$/.test(id||''))return respond(res,400,{error:'Invalid job_id'});
 if(!existsSync(`${jobsDir}/${id}.json`))return respond(res,404,{error:'Job not found'});
 const job=load(id);return respond(res,200,{id,job_id:id,status:job.status,result:job.status==='completed'?job.result:undefined});
 }
 if(req.method!=='POST'||url.pathname!=='/start_job')return respond(res,404,{error:'Route not found'});
 let bytes=0,body='';for await(const part of req){bytes+=part.length;if(bytes>20000)return respond(res,413,{error:'Request too large'});body+=part}
 let input;try{input=JSON.parse(body)}catch{return respond(res,400,{error:'Invalid JSON body'})}
 const nonce=input?.identifier_from_purchaser??input?.identifierFromPurchaser;
 if(!/^[a-fA-F0-9]{14,26}$/.test(nonce||''))return respond(res,400,{error:'Expected hex identifier_from_purchaser (14-26 chars)'});
 const invalid=validateInputData(input.input_data);if(invalid)return respond(res,400,{error:invalid});
 const reg=registry();if(reg.registrationState!=='RegistrationConfirmed'&&reg.registration?.state!=='RegistrationConfirmed')return respond(res,503,{error:'Registration not confirmed'});
 // Persist before the payment write. Unknown outcomes require inspection, never automatic replay.
 const key=sha256(nonce);const hash=inputHash(input.input_data,nonce);let job=jobFiles().map(x=>load(x.replace('.json',''))).find(j=>j.nonceKey===key);
 if(job){if(job.inputHash!==hash)return respond(res,409,{error:'Nonce already used with another input'});return respond(res,job.response?200:409,job.response?withHashAliases(job.response):{error:'Payment outcome requires inspection'});}
 const t=now();const minute=60000;
 job={id:randomUUID(),nonceKey:key,nonce,input:input.input_data,inputHash:hash,status:'awaiting_payment',phase:'payment-pending'};save(job);
 const payment=await callMps('/payment',{network:'Preprod',paymentSourceType:'Web3CardanoV2',supportedPaymentSourceIndex:reg.supportedPaymentSourceIndex,inputHash:job.inputHash,agentIdentifier:reg.agentIdentifier,identifierFromPurchaser:nonce,RequestedFunds:[{unit:'16a55b2a349361ff88c03788f93e1e966e5d689605d044fef722ddde0014df10745553444d',amount:'1000000'}],payByTime:new Date(t+10*minute).toISOString(),submitResultTime:new Date(t+20*minute).toISOString(),unlockTime:new Date(t+36*minute).toISOString(),externalDisputeUnlockTime:new Date(t+52*minute).toISOString()});
 job.payment=payment;job.phase='waiting-payment';job.response={id:job.id,input_hash:job.inputHash,inputHash:job.inputHash,identifierFromPurchaser:nonce,blockchainIdentifier:payment.blockchainIdentifier,agentIdentifier:reg.agentIdentifier,sellerVKey:sellerVkeyOf(reg,payment),paymentSourceType:'Web3CardanoV2',supportedPaymentSourceIndex:reg.supportedPaymentSourceIndex,payByTime:Number(payment.payByTime),submitResultTime:Number(payment.submitResultTime),unlockTime:Number(payment.unlockTime),externalDisputeUnlockTime:Number(payment.externalDisputeUnlockTime)};save(job);return respond(res,200,job.response);
 }catch(e){respond(res,500,{error:'Request failed. Inspect the saved job state before retrying.'})}
 }
 let busy=false;
 async function tick(){
 if(busy)return;busy=true;
 try{for(const file of jobFiles()){
 const job=load(file.replace('.json',''));try{
 if(!['waiting-payment','awaiting-result'].includes(job.phase))continue;
 const payment=await callMps('/payment/resolve-blockchain-identifier',{network:'Preprod',blockchainIdentifier:job.payment.blockchainIdentifier,includeHistory:'true'});
 if(job.phase==='awaiting-result'){if(payment.onChainState==='ResultSubmitted'&&payment.resultHash===job.resultHash&&confirmedState(payment,'ResultSubmitted')){job.phase='result-confirmed';job.status='completed';save(job)}continue;}
 if(payment.onChainState!=='FundsLocked'||!confirmedState(payment,'FundsLocked'))continue;
 if(Number(payment.submitResultTime)<=now()+120000){job.phase='deadline-blocked';job.status='failed';save(job);continue;}
 job.phase='model-pending';job.status='running';save(job);
 if(Number(payment.submitResultTime)<=now()+120000)continue;
 job.result=await answer(jobPrompt(job.input),`${jobsDir}/${job.id}-session`,Number(payment.submitResultTime));
 writeFileSync(`${jobsDir}/${job.id}.txt`,job.result,{mode:0o600});job.resultHash=resultHash(job.result,job.nonce);job.phase='submit-pending';save(job);
 if(Number(payment.submitResultTime)<=now()){job.phase='deadline-blocked';job.status='failed';save(job);continue;}
 await callMps('/payment/submit-result',{network:'Preprod',blockchainIdentifier:payment.blockchainIdentifier,submitResultHash:job.resultHash});
 job.phase='awaiting-result';save(job);
 }catch(e){console.error('Standard job needs inspection',job.id)}
 }}finally{busy=false}
 }
 return {handler,tick};
}
if(process.argv[1]&&pathToFileURL(resolve(process.argv[1])).href===import.meta.url){
 const port=Number(process.env.AGENT_API_PORT||21950);
 const {handler,tick}=createAgentApi();
 createServer(handler).listen(port,'127.0.0.1',()=>console.log('Agent API running',port));
 setInterval(tick,5000);
}

import {spawn} from 'node:child_process';
import {dirname,join,resolve} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
// Starts the PersonaLab LangGraph service (crest-graph) on 127.0.0.1 with this project's env files.
const here=dirname(fileURLToPath(import.meta.url));
export function graphAddress(env){
 const url=env.CREST_GRAPH_URL?new URL(env.CREST_GRAPH_URL):null;
 const port=Number(env.CREST_GRAPH_PORT??url?.port);
 if(!Number.isInteger(port)||port<1||port>65535)throw new Error('CREST_GRAPH_PORT must be an integer from 1 to 65535');
 if(url&&(url.protocol!=='http:'||url.hostname!=='127.0.0.1'||Number(url.port)!==port||url.username||url.password||url.pathname!=='/'||url.search||url.hash))throw new Error('CREST_GRAPH_URL must match http://127.0.0.1:CREST_GRAPH_PORT');
 return {port,url:`http://127.0.0.1:${port}`};
}
if(process.argv[1]&&import.meta.url===pathToFileURL(resolve(process.argv[1])).href){
 const {port,url}=graphAddress(process.env);
 const child=spawn('uv',['run','--project',join(here,'crest-graph'),'python','-m','crest_graph.server'],{cwd:join(here,'crest-graph'),stdio:'inherit',env:{...process.env,CREST_GRAPH_PORT:String(port),CREST_GRAPH_URL:url}});
 child.on('error',()=>{console.error('PersonaLab graph could not start (is uv installed?)');process.exitCode=1;});
 child.on('exit',(code,signal)=>{process.exitCode=code??(signal?1:0);});
 for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>child.kill(signal));
}

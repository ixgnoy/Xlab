import {dirname,join,isAbsolute,basename} from 'node:path';
import {pathToFileURL} from 'node:url';
import {runSokosumi} from './sokosumi-cli.mjs';
import {coworkerKeyFromEnv} from './runtime-env.mjs';
let loaded;
export function sokosumiRoot(run=(command,args)=>runSokosumi(args)){
 const skillsPath=run('sokosumi',['skills','path']).trim();
 if(!isAbsolute(skillsPath)||basename(skillsPath)!=='skills')throw new Error('sokosumi skills path returned an invalid package path');
 return join(dirname(skillsPath),'dist','src');
}
export async function loadSokosumiRuntime(){
 if(!loaded){const root=sokosumiRoot();
  loaded=Promise.all(['coworker/runtime-credentials.js','api/http-client.js','api/services/task-service.js'].map(p=>import(pathToFileURL(join(root,p)).href))).then(modules=>Object.assign({},...modules));
 }
 return loaded;
}
// Coworker key for Core calls: hosted deployments pass SOKOSUMI_COWORKER_API_KEY; locally the OS vault holds it.
export async function coworkerApiKey(env=process.env,load=loadSokosumiRuntime){
 const key=coworkerKeyFromEnv(env);
 if(key)return key;
 const {readRuntimeCredential}=await load();
 return readRuntimeCredential(env.COWORKER_ID);
}

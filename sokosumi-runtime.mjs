import {dirname,join,isAbsolute,basename} from 'node:path';
import {pathToFileURL} from 'node:url';
import {runSokosumi} from './sokosumi-cli.mjs';
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

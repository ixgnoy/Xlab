import {execFileSync,execSync} from 'node:child_process';
import {existsSync,readFileSync} from 'node:fs';
import {join} from 'node:path';
// Runs the installed Sokosumi CLI through its JS entry so Windows .cmd shims and shell quoting are never involved.
let entry;
export function sokosumiPackageDir(){
 const root=process.env.SOKOSUMI_CLI_ROOT||execSync('npm root -g',{encoding:'utf8',timeout:30000}).trim();
 const dir=join(root,'@masumi_network','sokosumi');
 if(!existsSync(join(dir,'package.json')))throw new Error('Sokosumi CLI is not installed globally');
 return dir;
}
export function sokosumiEntry(){
 if(!entry){const dir=sokosumiPackageDir();const bin=JSON.parse(readFileSync(join(dir,'package.json'),'utf8')).bin?.sokosumi;
  if(typeof bin!=='string')throw new Error('Sokosumi package has no CLI entry');entry=join(dir,bin);}
 return entry;
}
export function runSokosumi(args,options={}){
 return execFileSync(process.execPath,[sokosumiEntry(),...args],{encoding:'utf8',timeout:30000,maxBuffer:4*1024*1024,windowsHide:true,...options});
}

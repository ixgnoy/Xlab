import {existsSync,readFileSync} from 'node:fs';
import {join} from 'node:path';
import {parseEnv} from 'node:util';
// Deployment knobs shared by the worker and the Standard API. Defaults keep local behaviour unchanged.
// DATA_DIR holds journals, the worker lock, standard jobs and mps-runtime.env (a mounted volume when hosted).
export const dataDir=(env=process.env)=>String(env.DATA_DIR??'').trim()||'.local';
export const dataPath=(...parts)=>join(dataDir(),...parts);
export const isHosted=(env=process.env)=>['1','true'].includes(String(env.HOSTED??'').trim().toLowerCase());
// Coworker runtime key from the environment (hosted). Absent locally, where the OS vault / OAuth CLI is used.
export const coworkerKeyFromEnv=(env=process.env)=>String(env.SOKOSUMI_COWORKER_API_KEY??'').trim()||undefined;
// MPS runtime token: env MPS_RUNTIME_TOKEN wins, else DATA_DIR/mps-runtime.env written by payment-registration.mjs.
export function mpsRuntimeTokenFile(env=process.env){return join(dataDir(env),'mps-runtime.env');}
export function mpsRuntimeToken(env=process.env){
 const direct=String(env.MPS_RUNTIME_TOKEN??'').trim();
 if(direct)return direct;
 const file=mpsRuntimeTokenFile(env);
 if(!existsSync(file))return undefined;
 return String(parseEnv(readFileSync(file,'utf8')).MPS_RUNTIME_TOKEN??'').trim()||undefined;
}

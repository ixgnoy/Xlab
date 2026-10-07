import {mkdirSync} from 'node:fs';
import {answer,client} from './client.mjs';
// Real model turn through the running graph service. Prints only the stage heading and size, not secrets.
mkdirSync('.local',{recursive:true,mode:0o700});
try{
 await client.health();
 const started=Date.now();
 const out=await answer('[stage:create] Niche: home workouts for busy parents. Audience: parents 28-40. Look: friendly animated fitness coach, not photorealistic. Voice: upbeat. Platform: Instagram Reels. Goal: followers.','.local/smoke-session.json');
 const sections=[...out.matchAll(/^##\s+(.+)$/gm)].map(m=>m[1]);
 console.log(JSON.stringify({ok:true,heading:out.split('\n')[0],sections,chars:out.length,seconds:Math.round((Date.now()-started)/1000)}));
}catch(error){console.error(JSON.stringify({ok:false,error:error.message}));process.exitCode=1;}

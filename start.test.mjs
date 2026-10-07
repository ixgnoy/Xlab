import {test} from 'node:test';
import assert from 'node:assert/strict';
import {graphAddress} from './start.mjs';
import {sokosumiRoot} from './sokosumi-runtime.mjs';
import {join} from 'node:path';
test('graph service rejects a mismatched port or exposed listener',()=>{
 assert.throws(()=>graphAddress({CREST_GRAPH_PORT:'21951',CREST_GRAPH_URL:'http://127.0.0.1:21952'}),/must match/);
 assert.throws(()=>graphAddress({CREST_GRAPH_URL:'http://0.0.0.0:21951'}),/must match/);
 assert.throws(()=>graphAddress({CREST_GRAPH_PORT:'0'}),/integer/);
 assert.deepEqual(graphAddress({CREST_GRAPH_URL:'http://127.0.0.1:21951'}),{port:21951,url:'http://127.0.0.1:21951'});
});
test('runtime root derives from supported installed CLI output',()=>{
 assert.equal(sokosumiRoot((command,args)=>{assert.equal(command,'sokosumi');assert.deepEqual(args,['skills','path']);return join('/opt','node_modules','@masumi_network','sokosumi','skills')+'\n';}),join('/opt','node_modules','@masumi_network','sokosumi','dist','src'));
 assert.throws(()=>sokosumiRoot(()=>'/unrelated'),/invalid package path/);
});

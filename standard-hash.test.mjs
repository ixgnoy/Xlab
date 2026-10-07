import {test} from 'node:test';
import assert from 'node:assert/strict';
import {inputHash,resultHash,canonicalJson,sha256} from './standard-hash.mjs';
test('fixed input shape uses canonical JSON and UTF-8',()=>{
 assert.equal(inputHash({prompt:'Cardano payments'},'aabbccddeeff0011'),'25f3afe66b39b0582711c9faf53930c7b6a6feffd10294750ec77be47fd63080');
});
test('Standard result uses raw newline bytes',()=>{
 assert.equal(resultHash('Line 1\nLine 2','aabbccddeeff0011'),'6fa3bfa69364318f78619b87652c725d705c90f18f8bdcb5d7041c17b73ea57a');
 assert.notEqual(resultHash('Line 1\nLine 2','aabbccddeeff0011'),resultHash('Line 1\\nLine 2','aabbccddeeff0011'));
});
test('MIP-004 input hash uses JCS: sorted keys, no whitespace',()=>{
 assert.equal(canonicalJson({stage:'create',brief:'Hi é "q"\n'}),String.raw`{"brief":"Hi é \"q\"\n","stage":"create"}`);
 assert.equal(inputHash({stage:'create',brief:'b'},'aabbccddeeff0011'),inputHash({brief:'b',stage:'create'},'aabbccddeeff0011'));
 assert.equal(inputHash({stage:'create',brief:'b'},'aabbccddeeff0011'),sha256('aabbccddeeff0011;{"brief":"b","stage":"create"}'));
 assert.equal(canonicalJson({b:[1,true,null],a:{d:1,c:'x'}}),'{"a":{"c":"x","d":1},"b":[1,true,null]}');
 assert.throws(()=>canonicalJson({a:undefined}));
});

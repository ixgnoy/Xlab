import {createHash} from 'node:crypto';
export const sha256=text=>createHash('sha256').update(text,'utf8').digest('hex');
// MIP-004 input canonicalization: JCS (RFC 8785). Object keys sorted by UTF-16 code units, no whitespace,
// strings/numbers serialized as ECMAScript JSON.stringify does. Only JSON-safe values are accepted.
export function canonicalJson(value){
 if(value===null||typeof value==='string'||typeof value==='boolean')return JSON.stringify(value);
 if(typeof value==='number'){if(!Number.isFinite(value))throw new TypeError('Non-finite number in input');return JSON.stringify(value);}
 if(Array.isArray(value))return `[${value.map(canonicalJson).join(',')}]`;
 if(typeof value==='object')return `{${Object.keys(value).sort().map(k=>`${JSON.stringify(k)}:${canonicalJson(value[k])}`).join(',')}}`;
 throw new TypeError(`Unsupported input value type: ${typeof value}`);
}
export const inputHash=(input,nonce)=>sha256(`${nonce};${canonicalJson(input)}`);
export const resultHash=(result,nonce)=>sha256(`${nonce};${result}`);

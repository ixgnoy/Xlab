import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { registrationUrl, requireSavedRuntimeToken, agentApiBaseUrl, registrationBody } from './registration-config.mjs';
test('registration uses the configured loopback port', () => {
 assert.equal(registrationUrl('32123'), 'http://127.0.0.1:32123');
 assert.equal(registrationUrl(), 'http://127.0.0.1:21950');
 for (const value of ['0','65536','abc','21950.5','']) assert.throws(() => registrationUrl(value));
});
test('saved key requires its private unmasked token', () => {
 const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'registration-test-'));
 const file = path.join(dir, 'runtime.env');
 try {
 assert.throws(() => requireSavedRuntimeToken(file), /recovery required/);
 for (const value of ['', '*****masked']) {
 fs.writeFileSync(file, `MPS_RUNTIME_TOKEN=${value}\n`);
 assert.throws(() => requireSavedRuntimeToken(file), /recovery required/);
 }
 fs.writeFileSync(file, 'MPS_RUNTIME_TOKEN=test-token\n');
 assert.equal(requireSavedRuntimeToken(file), 'test-token');
 } finally { fs.rmSync(dir, { recursive: true }); }
});
test('apiBaseUrl prefers AGENT_API_PUBLIC_URL and falls back to loopback port', () => {
 assert.equal(agentApiBaseUrl({}), 'http://127.0.0.1:21950');
 assert.equal(agentApiBaseUrl({ AGENT_API_PORT: '32123' }), 'http://127.0.0.1:32123');
 assert.equal(agentApiBaseUrl({ AGENT_API_PUBLIC_URL: '  ' , AGENT_API_PORT: '32123' }), 'http://127.0.0.1:32123');
 assert.equal(agentApiBaseUrl({ AGENT_API_PUBLIC_URL: 'https://personalab.example.com/' }), 'https://personalab.example.com');
 assert.equal(agentApiBaseUrl({ AGENT_API_PUBLIC_URL: 'https://x.example.com/agent/' }), 'https://x.example.com/agent');
 for (const bad of ['not a url', 'http://public.example.com', 'ftp://x.example.com', 'https://u:p@x.example.com', 'https://x.example.com/?a=1']) assert.throws(() => agentApiBaseUrl({ AGENT_API_PUBLIC_URL: bad }));
});
test('registration body describes PersonaLab with unchanged pricing and payment source', () => {
 const body = registrationBody({ walletVkey: 'vk', smartContractAddress: 'addr_test1x', env: { ZAI_MODEL: 'glm', AGENT_API_PUBLIC_URL: 'https://personalab.example.com' } });
 assert.equal(body.name, 'PersonaLab');
 assert.deepEqual(body.Tags, ['ai-influencer', 'social-media', 'content', 'langgraph', 'token2049']);
 for (const word of ['Create', 'Schedule', 'Engage', 'Analyze']) assert.match(body.description, new RegExp(word));
 assert.equal(body.network, 'Preprod'); assert.equal(body.type, 'Standard'); assert.equal(body.sellingWalletVkey, 'vk');
 assert.deepEqual(body.supportedPaymentSources, [{ chain: 'Cardano', network: 'Preprod', paymentSourceType: 'Web3CardanoV2', address: 'addr_test1x', pricing: { pricingType: 'Dynamic' } }]);
 assert.deepEqual(body.Capability, { name: 'glm', version: '1' });
 assert.equal(typeof body.Author.name, 'string'); assert.ok(body.Author.name);
 assert.equal(body.apiBaseUrl, 'https://personalab.example.com');
 assert.equal(registrationBody({ walletVkey: 'vk', smartContractAddress: 'a', env: {} }).apiBaseUrl, 'http://127.0.0.1:21950');
 assert.throws(() => registrationBody({ walletVkey: '', smartContractAddress: 'a', env: {} }));
});

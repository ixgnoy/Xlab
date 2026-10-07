import fs from 'node:fs';
import { parseEnv } from 'node:util';
export function registrationUrl(port = '21950') {
 if (!/^\d+$/.test(String(port)) || Number(port) < 1 || Number(port) > 65535) throw Error('AGENT_API_PORT must be an integer between 1 and 65535');
 return `http://127.0.0.1:${Number(port)}`;
}
// Public base URL announced on MPS. Sokosumi must reach it, so non-loopback URLs must be HTTPS.
export function agentApiBaseUrl(env = process.env) {
 const raw = env.AGENT_API_PUBLIC_URL?.trim();
 if (!raw) return registrationUrl(env.AGENT_API_PORT);
 let url;
 try { url = new URL(raw); } catch { throw Error('AGENT_API_PUBLIC_URL must be an absolute URL'); }
 const loopback = ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname);
 if (url.protocol !== 'https:' && !(loopback && url.protocol === 'http:')) throw Error('AGENT_API_PUBLIC_URL must use https (http only for loopback)');
 if (url.search || url.hash || url.username || url.password) throw Error('AGENT_API_PUBLIC_URL must not contain credentials, query or fragment');
 return url.href.replace(/\/+$/, '');
}
export const AGENT_PROFILE = {
 name: 'PersonaLab',
 description: 'PersonaLab is an AI-influencer studio. Pick a stage and send a brief: Create drafts on-brand persona posts and captions, Schedule builds a posting calendar, Engage writes comment and DM replies, and Analyze turns performance data into insights and next steps.',
 tags: ['ai-influencer', 'social-media', 'content', 'langgraph', 'token2049'],
};
// MPS POST /registry body. Pricing and payment source are fixed: Dynamic pricing on Preprod Web3CardanoV2.
export function registrationBody({ walletVkey, smartContractAddress, env = process.env }) {
 if (!walletVkey || !smartContractAddress) throw Error('Selling wallet vkey and payment source address are required');
 return {
  network: 'Preprod', type: 'Standard', sellingWalletVkey: walletVkey,
  supportedPaymentSources: [{ chain: 'Cardano', network: 'Preprod', paymentSourceType: 'Web3CardanoV2', address: smartContractAddress, pricing: { pricingType: 'Dynamic' } }],
  ExampleOutputs: [], Tags: AGENT_PROFILE.tags, name: AGENT_PROFILE.name, description: AGENT_PROFILE.description,
  Capability: { name: env.ZAI_MODEL || 'personalab-langgraph', version: '1' },
  Author: { name: env.AGENT_AUTHOR_NAME || 'PersonaLab' },
  apiBaseUrl: agentApiBaseUrl(env),
 };
}
export function requireSavedRuntimeToken(path) {
 let token;
 try { token = parseEnv(fs.readFileSync(path, 'utf8')).MPS_RUNTIME_TOKEN; } catch { throw Error('Runtime key recovery required: private token file is missing or unreadable'); }
 if (!token || token.startsWith('*****')) throw Error('Runtime key recovery required: private token is missing or masked');
 return token;
}

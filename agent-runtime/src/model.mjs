import { ModelRuntime } from '@earendil-works/pi-coding-agent';
import { InMemoryCredentialStore, createAssistantMessageEventStream } from '@earendil-works/pi-ai';

// Keep only a possible credential prefix between deltas, never the whole answer.
export function credentialFilter(secret) {
  let pending = '';
  return (text = '', final = false) => {
    pending += text;
    pending = pending.split(secret).join('[REDACTED]');
    let hold = 0;
    if (!final) for (let n = 1; n < secret.length && n <= pending.length; n++) {
      if (pending.endsWith(secret.slice(0, n))) hold = n;
    }
    const result = pending.slice(0, pending.length - hold);
    pending = pending.slice(pending.length - hold);
    return result;
  };
}

function redact(value, secret) {
  if (typeof value === 'string') return value.split(secret).join('[REDACTED]');
  if (Array.isArray(value)) return value.map(v => redact(v, secret));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k,v]) => [k.split(secret).join('[REDACTED]'), redact(v, secret)]));
  return value;
}

export async function createModelRuntime(config, secret, {vision = false, beforeRequest, afterResponse} = {}) {
  const runtime = await ModelRuntime.create({ credentials: new InMemoryCredentialStore(), modelsPath: null, refreshOnCreate: false, allowModelNetwork: false });
  runtime.registerProvider('workbench', {
    baseUrl: config.url, api: config.api || 'openai-completions', authHeader: true,
    models: [{ id: config.model, name: config.model, reasoning: false, input: vision ? ['text','image'] : ['text'], contextWindow: 128000, maxTokens: 8192, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }],
  });
  await runtime.setRuntimeApiKey('workbench', secret);
  const stream = runtime.streamSimple.bind(runtime);
  runtime.streamSimple = (...args) => {
    const output = createAssistantMessageEventStream();
    void (async () => {
      const filters = new Map();
      let requested=false,reported=false;
      try {
        await beforeRequest?.();
        requested=true;
        for await (const raw of stream(...args)) {
          const event = redact(raw, secret);
          if ((event.type === 'done' || event.type === 'error') && !reported) {
            reported=true;
            afterResponse?.((event.message || event.error)?.usage);
          }
          if (event.type.endsWith('_delta') && typeof event.delta === 'string') {
            const key = `${event.type}:${event.contentIndex}`;
            if (!filters.has(key)) filters.set(key, {filter: credentialFilter(secret), event});
            const state = filters.get(key);
            state.event = event;
            event.delta = state.filter(raw.delta);
            if (event.delta) output.push(event);
            continue;
          }
          // Flush held suffixes before block ends or terminal messages.
          if (event.type.endsWith('_end') || event.type === 'done' || event.type === 'error') {
            for (const [key, state] of filters) {
              if (event.type.endsWith('_end') && state.event.contentIndex !== event.contentIndex) continue;
              const delta = state.filter('', true);
              if (delta) output.push({...state.event, delta});
              filters.delete(key);
            }
          }
          output.push(event);
        }
        output.end();
      } catch {
        if(requested&&!reported){reported=true;try{afterResponse?.(null);}catch{}}
        output.push({type: 'error', reason: 'error', error: {role: 'assistant', content: [], api: config.api || 'openai-completions', provider: 'workbench', model: config.model, stopReason: 'error', errorMessage: 'Provider stream failed', timestamp: Date.now(), usage: {input:0,output:0,cacheRead:0,cacheWrite:0,totalTokens:0,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}}}});
        output.end();
      }
    })();
    return output;
  };
  return runtime;
}

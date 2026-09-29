/* Mount-aware URL handling for this first-party app. Stored media paths stay canonical. */
'use strict';
(() => {
  const base = document.querySelector('meta[name="sqa-base-path"]')?.content || '';
  const localPath = value => {
    if (typeof value !== 'string' || !base || !value.startsWith('/') || value.startsWith('//')) return value;
    return value === base || value.startsWith(base + '/') ? value : base + value;
  };
  const mediaFields = new Set(['src', 'originalSrc', 'masterSrc', 'cover']);
  const translateMedia = (value, inbound) => {
    if (Array.isArray(value)) return value.map(item => translateMedia(item, inbound));
    if (!value || typeof value !== 'object') return value;
    for (const [key, item] of Object.entries(value)) {
      if (mediaFields.has(key) && typeof item === 'string') {
        if (inbound && base && (item.startsWith(base + '/api/') || item.startsWith(base + '/images/'))) value[key] = item.slice(base.length);
        else if (!inbound && (item.startsWith('/api/') || item.startsWith('/images/'))) value[key] = localPath(item);
      } else if (item && typeof item === 'object') value[key] = translateMedia(item, inbound);
    }
    return value;
  };
  window.sqaUrl = localPath;
  if (!base) return;

  const nativeFetch = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    let target = input;
    if (typeof input === 'string' || input instanceof URL) target = localPath(String(input));
    const options = {...init};
    if (typeof options.body === 'string' && options.headers && (options.headers instanceof Headers ? options.headers.get('Content-Type') : options.headers['Content-Type'] || options.headers['content-type'])?.includes('json')) {
      try { options.body = JSON.stringify(translateMedia(JSON.parse(options.body), true)); } catch {}
    }
    return nativeFetch(target, options).then(response => {
      if (response.headers.get('Content-Type')?.includes('application/json')) {
        const json = response.json.bind(response);
        response.json = async () => translateMedia(await json(), false);
      }
      return response;
    });
  };
})();

const dns = require('node:dns');
const http = require('node:http');
const https = require('node:https');

// Set global agent timeouts to 60 seconds
http.globalAgent.options.timeout = 60000;
https.globalAgent.options.timeout = 60000;

// 1. DNS Lookup Override
const originalLookup = dns.lookup;
const HOSTS_MAP = {
  'accounts.shopify.com': '23.227.39.20',
  'destinations.shopifysvc.com': '23.227.39.20',
  'app.shopify.com': '34.144.193.86'
};

dns.lookup = function(hostname, options, callback) {
  let actualOptions = options;
  let actualCallback = callback;
  
  if (typeof options === 'function') {
    actualCallback = options;
    actualOptions = {};
  } else if (!options) {
    actualOptions = {};
  }
  
  if (HOSTS_MAP[hostname]) {
    const ip = HOSTS_MAP[hostname];
    const family = 4;
    console.log(`[DNS Override] Resolved ${hostname} -> ${ip}`);
    
    if (actualOptions.all) {
      const addresses = [{ address: ip, family }];
      if (actualCallback) {
        process.nextTick(() => actualCallback(null, addresses));
        return;
      }
      return addresses;
    } else {
      if (actualCallback) {
        process.nextTick(() => actualCallback(null, ip, family));
        return;
      }
      return { address: ip, family };
    }
  }
  
  // Log normal lookups too
  if (actualCallback) {
    const originalCallback = actualCallback;
    actualCallback = function(err, address, family) {
      console.log(`[DNS Normal] Resolved ${hostname} -> ${address} (err: ${err})`);
      originalCallback(err, address, family);
    };
  }
  return originalLookup.call(dns, hostname, options, callback);
};

// 2. HTTP/HTTPS Request Override (for User-Agent and Timeouts)
const BROWSER_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36';

function overrideHeaders(obj) {
  if (obj && typeof obj === 'object' && !(obj instanceof URL)) {
    if (!obj.headers) {
      obj.headers = {};
    }
    const uaKey = Object.keys(obj.headers).find(k => k.toLowerCase() === 'user-agent');
    if (uaKey) {
      obj.headers[uaKey] = BROWSER_USER_AGENT;
    } else {
      obj.headers['User-Agent'] = BROWSER_USER_AGENT;
    }
    obj.timeout = 60000;
  }
}

const originalHttpRequest = http.request;
http.request = function(...args) {
  for (const arg of args) {
    overrideHeaders(arg);
  }
  return originalHttpRequest.apply(http, args);
};

const originalHttpsRequest = https.request;
https.request = function(...args) {
  for (const arg of args) {
    overrideHeaders(arg);
  }
  return originalHttpsRequest.apply(https, args);
};

// 3. Global Fetch Override (Transparently overrides User-Agent and delegates to native fetch)
if (global.fetch) {
  const originalFetch = global.fetch;
  global.fetch = function(url, init = {}) {
    const parsedUrl = typeof url === 'string' ? new URL(url) : url;
    
    if (parsedUrl.hostname && (parsedUrl.hostname.includes('shopify') || parsedUrl.hostname.includes('shopifysvc'))) {
      const newInit = { ...init };
      let headers = {};
      
      if (init.headers) {
        if (init.headers instanceof Headers) {
          for (const [key, val] of init.headers.entries()) {
            headers[key] = val;
          }
        } else if (Array.isArray(init.headers)) {
          for (const [key, val] of init.headers) {
            headers[key] = val;
          }
        } else {
          headers = { ...init.headers };
        }
      }
      
      const uaKey = Object.keys(headers).find(k => k.toLowerCase() === 'user-agent');
      if (uaKey) {
        headers[uaKey] = BROWSER_USER_AGENT;
      } else {
        headers['User-Agent'] = BROWSER_USER_AGENT;
      }
      
      newInit.headers = headers;
      return originalFetch.call(global, url, newInit);
    }
    
    return originalFetch.call(global, url, init);
  };
}

console.log("[DNS, UA & Fetch Override Active] Shopify network pipeline fully stabilized.");

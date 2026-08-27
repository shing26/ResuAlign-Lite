/* Small in-memory cache with TTL for repeated GET responses. */

export const API_CACHE_TTL = 30_000;

export class CacheManager {
  constructor({ ttl = API_CACHE_TTL } = {}) {
    this.ttl = ttl;
    this.store = new Map();
  }

  get(key) {
    this.prune();
    const entry = this.store.get(String(key));
    return entry ? entry.value : undefined;
  }

  set(key, value, ttl = this.ttl) {
    if (value === undefined) return;
    const expiresAt = Date.now() + Math.max(0, Number(ttl) || 0);
    this.store.set(String(key), { value, expiresAt });
  }

  has(key) {
    this.prune();
    return this.store.has(String(key));
  }

  delete(key) {
    return this.store.delete(String(key));
  }

  clear() {
    this.store.clear();
  }

  prune() {
    const now = Date.now();
    for (const [key, entry] of this.store.entries()) {
      if (entry.expiresAt <= now) this.store.delete(key);
    }
  }

  get size() {
    this.prune();
    return this.store.size;
  }
}

export const apiCache = new CacheManager();

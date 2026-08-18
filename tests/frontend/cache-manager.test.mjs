import test from "node:test";
import assert from "node:assert/strict";
import {
  API_CACHE_TTL,
  CacheManager,
  apiCache,
} from "../../src/resualign/static/app/cache-manager.js";

test("API_CACHE_TTL defaults to 30 seconds", () => {
  assert.equal(API_CACHE_TTL, 30_000);
});

test("CacheManager returns values and respects TTL", async () => {
  const cache = new CacheManager({ ttl: 10 });
  cache.set("a", { ok: 1 });
  assert.equal(cache.get("a").ok, 1);
  await new Promise((resolve) => setTimeout(resolve, 15));
  assert.equal(cache.get("a"), undefined);
});

test("CacheManager supports has/delete/clear and prunes expired entries", () => {
  const cache = new CacheManager({ ttl: 5 });
  cache.set("a", 1);
  cache.set("b", 2);
  assert.equal(cache.has("a"), true);
  cache.delete("a");
  assert.equal(cache.has("a"), false);
  cache.clear();
  assert.equal(cache.size, 0);
});

test("apiCache remains a shared singleton", () => {
  assert.ok(apiCache instanceof CacheManager);
});

/// Simple ETS-based cache with TTL.
/// Caches API responses to avoid rate limiting transport.opendata.ch.

/// Initialize the cache table. Call once at startup.
@external(erlang, "tl_backend_cache_ffi", "init")
pub fn init() -> Nil

/// Get a cached value. Returns Ok(value) if found and not expired, Error(Nil) otherwise.
@external(erlang, "tl_backend_cache_ffi", "get")
pub fn get(key: String) -> Result(String, Nil)

/// Store a value in cache with TTL in seconds.
@external(erlang, "tl_backend_cache_ffi", "put")
pub fn put(key: String, value: String, ttl_seconds: Int) -> Nil

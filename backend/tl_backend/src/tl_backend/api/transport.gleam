/// Shared transport.opendata.ch API client with caching.
import gleam/http/request
import gleam/httpc
import tl_backend/cache

/// Cache TTL in seconds. With 7 stops, 60s TTL = 7 req/min = 10080/day (exactly the limit)
const cache_ttl = 60

/// Fetch stationboard JSON for a stop, with caching.
pub fn fetch_stationboard(stop_id: String) -> Result(String, String) {
  let cache_key = "stationboard_" <> stop_id

  case cache.get(cache_key) {
    Ok(cached) -> Ok(cached)
    Error(_) -> {
      let url =
        "https://transport.opendata.ch/v1/stationboard?id="
        <> stop_id
        <> "&limit=15"

      let assert Ok(req) = request.to(url)

      case httpc.send(req) {
        Ok(resp) -> {
          cache.put(cache_key, resp.body, cache_ttl)
          Ok(resp.body)
        }
        Error(_) -> Error("HTTP request failed for stop " <> stop_id)
      }
    }
  }
}

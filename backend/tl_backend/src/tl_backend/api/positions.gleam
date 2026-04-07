import gleam/dict
import gleam/dynamic/decode
import gleam/float
import gleam/http
import gleam/httpc
import gleam/http/request
import gleam/http/response
import gleam/int
import gleam/json
import gleam/list
import gleam/option.{type Option, None, Some}
import gleam/result
import gleam/string
import simplifile
import wisp.{type Request, type Response}

/// Stops we monitor for active trips
const monitored_stops = [
  #("8592209", "Renens VD, Censuy"),
  #("8592218", "Renens VD, Caudray"),
  #("8593866", "Chavannes-R., Préfaully"),
  #("8595534", "Renens VD, piscine"),
  #("8510422", "Chavannes-R., Talluchet"),
  #("8592213", "Renens VD, Hôtel-de-Ville/ECAL"),
  #("8592221", "Renens VD, Sous l'Eglise"),
]

pub type StopTime {
  StopTime(
    stop_id: String,
    name: String,
    lat: Float,
    lon: Float,
    arrival: String,
    departure: String,
  )
}

pub type RouteStops {
  RouteStops(stops: List(StopTime))
}

pub type BusPosition {
  BusPosition(
    lat: Float,
    lon: Float,
    line: String,
    destination: String,
    progress: Float,
  )
}

pub fn handle(req: Request, static_dir: String) -> Response {
  use <- wisp.require_method(req, http.Get)

  // Load route stops data
  let route_stops_path = static_dir <> "/route_stops.json"
  case simplifile.read(route_stops_path) {
    Ok(route_data) -> {
      case compute_positions(route_data) {
        Ok(positions) -> {
          let geojson = encode_positions_geojson(positions)
          wisp.json_response(json.to_string(geojson), 200)
        }
        Error(msg) -> {
          wisp.log_error("Position computation failed: " <> msg)
          // Return empty GeoJSON on error
          wisp.json_response(
            "{\"type\":\"FeatureCollection\",\"features\":[]}",
            200,
          )
        }
      }
    }
    Error(_) -> {
      wisp.log_error("Could not read route_stops.json")
      wisp.internal_server_error()
    }
  }
}

fn compute_positions(
  route_data_json: String,
) -> Result(List(BusPosition), String) {
  // Get current departures from all monitored stops
  let departures_result =
    monitored_stops
    |> list.map(fn(stop) {
      let #(id, _name) = stop
      fetch_stationboard_raw(id)
    })
    |> result.all
    |> result.map(list.flatten)

  case departures_result {
    Ok(departures) -> {
      // Parse route stops
      case parse_route_stops(route_data_json) {
        Ok(route_stops) -> {
          // For each departure, try to interpolate position
          let positions =
            departures
            |> list.filter_map(fn(dep) {
              interpolate_bus(dep, route_stops)
            })
          Ok(positions)
        }
        Error(e) -> Error(e)
      }
    }
    Error(e) -> Error(e)
  }
}

pub type RawDeparture {
  RawDeparture(
    stop_name: String,
    stop_id: String,
    line: String,
    destination: String,
    departure_time: String,
    delay: Option(Int),
    stop_lat: Float,
    stop_lon: Float,
  )
}

fn fetch_stationboard_raw(
  stop_id: String,
) -> Result(List(RawDeparture), String) {
  let url =
    "https://transport.opendata.ch/v1/stationboard?id="
    <> stop_id
    <> "&limit=15"

  let assert Ok(req) = request.to(url)

  case httpc.send(req) {
    Ok(resp) -> parse_raw_departures(resp, stop_id)
    Error(_) -> Error("HTTP request failed for stop " <> stop_id)
  }
}

fn parse_raw_departures(
  resp: response.Response(String),
  stop_id: String,
) -> Result(List(RawDeparture), String) {
  let decoder = {
    use departures <- decode.field(
      "stationboard",
      decode.list(raw_departure_decoder(stop_id)),
    )
    decode.success(departures)
  }

  case json.parse(resp.body, decoder) {
    Ok(departures) -> Ok(departures)
    Error(_) -> Error("Failed to parse stationboard for " <> stop_id)
  }
}

fn raw_departure_decoder(
  stop_id: String,
) -> decode.Decoder(RawDeparture) {
  use stop_name <- decode.subfield(
    ["stop", "station", "name"],
    decode.string,
  )
  use number <- decode.field("number", decode.string)
  use to <- decode.field("to", decode.string)
  use departure <- decode.subfield(["stop", "departure"], decode.string)
  use delay <- decode.subfield(
    ["stop", "delay"],
    decode.optional(decode.int),
  )
  use lat <- decode.subfield(
    ["stop", "station", "coordinate", "x"],
    decode.float,
  )
  use lon <- decode.subfield(
    ["stop", "station", "coordinate", "y"],
    decode.float,
  )
  decode.success(RawDeparture(
    stop_name: stop_name,
    stop_id: stop_id,
    line: number,
    destination: to,
    departure_time: departure,
    delay: delay,
    stop_lat: lat,
    stop_lon: lon,
  ))
}

/// Parse the route_stops.json into a lookup
fn parse_route_stops(
  json_str: String,
) -> Result(List(#(String, List(StopTime))), String) {
  let decoder =
    decode.dict(decode.string, decode.list(stop_time_decoder()))

  case json.parse(json_str, decoder) {
    Ok(d) -> Ok(dict.to_list(d))
    Error(_) -> Error("Failed to parse route_stops.json")
  }
}

fn stop_time_decoder() -> decode.Decoder(StopTime) {
  use stop_id <- decode.field("stop_id", decode.string)
  use name <- decode.field("name", decode.string)
  use lat <- decode.field("lat", decode.float)
  use lon <- decode.field("lon", decode.float)
  use arrival <- decode.field("arrival", decode.string)
  use departure <- decode.field("departure", decode.string)
  decode.success(StopTime(
    stop_id: stop_id,
    name: name,
    lat: lat,
    lon: lon,
    arrival: arrival,
    departure: departure,
  ))
}

/// Try to interpolate where a bus is based on its departure info
fn interpolate_bus(
  dep: RawDeparture,
  route_stops: List(#(String, List(StopTime))),
) -> Result(BusPosition, Nil) {
  // Find matching route: same line, destination matches headsign
  let matching_route =
    route_stops
    |> list.find(fn(entry) {
      let #(key, _stops) = entry
      // key is like "25_Pully, gare"
      let parts = string.split(key, "_")
      case parts {
        [line, ..rest] -> {
          let headsign = string.join(rest, "_")
          line == dep.line && headsign == dep.destination
        }
        _ -> False
      }
    })

  case matching_route {
    Ok(#(_key, stops)) -> {
      // Build indexed triples: (prev_stop, current_stop, next_stop)
      let triples = build_stop_triples(stops)

      // Find this stop in the route
      let found =
        triples
        |> list.find(fn(triple) {
          let #(_prev, curr, _next) = triple
          curr.name == dep.stop_name
        })

      case found {
        Ok(#(prev, current_stop, next)) -> {
          let dep_seconds = time_string_to_seconds(dep.departure_time)
          let delay_seconds = option.unwrap(dep.delay, 0) * 60
          let current_seconds = dep_seconds + delay_seconds
          let now_seconds = get_current_time_seconds()
          let seconds_until = current_seconds - now_seconds

          interpolate_from_context(
            dep, prev, current_stop, next,
            current_seconds, now_seconds, seconds_until,
          )
        }
        Error(_) -> Error(Nil)
      }
    }
    Error(_) -> Error(Nil)
  }
}

/// Build triples of (prev, current, next) for each stop in a list
fn build_stop_triples(
  stops: List(StopTime),
) -> List(#(Option(StopTime), StopTime, Option(StopTime))) {
  let indexed = list.index_map(stops, fn(s, i) { #(i, s) })
  let len = list.length(stops)

  list.map(indexed, fn(pair) {
    let #(i, stop) = pair
    let prev = case i > 0 {
      True -> {
        let before = list.drop(stops, i - 1)
        case before {
          [p, ..] -> Some(p)
          _ -> None
        }
      }
      False -> None
    }
    let next = case i < len - 1 {
      True -> {
        let after = list.drop(stops, i + 1)
        case after {
          [n, ..] -> Some(n)
          _ -> None
        }
      }
      False -> None
    }
    #(prev, stop, next)
  })
}

/// Interpolate position given context around a stop
fn interpolate_from_context(
  dep: RawDeparture,
  prev: Option(StopTime),
  current: StopTime,
  next: Option(StopTime),
  current_seconds: Int,
  now_seconds: Int,
  seconds_until: Int,
) -> Result(BusPosition, Nil) {
  case seconds_until {
    // Bus approaching this stop (0-5 min away), interpolate from prev
    s if s > 0 && s < 300 -> {
      case prev {
        Some(prev_stop) -> {
          let prev_dep = time_string_to_seconds(prev_stop.departure)
          let seg = int.to_float(current_seconds - prev_dep)
          let elapsed = int.to_float(now_seconds - prev_dep)
          let t = case seg >. 0.0 {
            True -> float.min(1.0, float.max(0.0, elapsed /. seg))
            False -> 1.0
          }
          Ok(BusPosition(
            lat: prev_stop.lat +. { current.lat -. prev_stop.lat } *. t,
            lon: prev_stop.lon +. { current.lon -. prev_stop.lon } *. t,
            line: dep.line,
            destination: dep.destination,
            progress: t,
          ))
        }
        None -> {
          // First stop, just show at stop
          Ok(BusPosition(
            lat: current.lat, lon: current.lon,
            line: dep.line, destination: dep.destination, progress: 0.0,
          ))
        }
      }
    }
    // Bus at this stop (within 1 min of departure)
    s if s >= -60 && s <= 0 -> {
      Ok(BusPosition(
        lat: current.lat, lon: current.lon,
        line: dep.line, destination: dep.destination, progress: 0.0,
      ))
    }
    // Bus departed, heading to next stop
    s if s < -60 && s > -600 -> {
      case next {
        Some(next_stop) -> {
          let next_arr = time_string_to_seconds(next_stop.arrival)
          let seg = int.to_float(next_arr - current_seconds)
          let elapsed = int.to_float(now_seconds - current_seconds)
          let t = case seg >. 0.0 {
            True -> float.min(1.0, float.max(0.0, elapsed /. seg))
            False -> 0.0
          }
          Ok(BusPosition(
            lat: current.lat +. { next_stop.lat -. current.lat } *. t,
            lon: current.lon +. { next_stop.lon -. current.lon } *. t,
            line: dep.line, destination: dep.destination, progress: t,
          ))
        }
        None -> Error(Nil)
      }
    }
    _ -> Error(Nil)
  }
}

/// Parse ISO datetime or HH:MM:SS to seconds since midnight
fn time_string_to_seconds(time_str: String) -> Int {
  // Handle "2026-04-07T20:15:00+0200" format
  let time_part = case string.contains(time_str, "T") {
    True -> {
      let parts = string.split(time_str, "T")
      case parts {
        [_, rest] -> {
          // Take just HH:MM:SS, strip timezone
          string.slice(rest, 0, 8)
        }
        _ -> time_str
      }
    }
    False -> time_str
  }

  let parts = string.split(time_part, ":")
  case parts {
    [h, m, s] -> {
      let hours = result.unwrap(int.parse(h), 0)
      let minutes = result.unwrap(int.parse(m), 0)
      let seconds = result.unwrap(int.parse(s), 0)
      hours * 3600 + minutes * 60 + seconds
    }
    [h, m] -> {
      let hours = result.unwrap(int.parse(h), 0)
      let minutes = result.unwrap(int.parse(m), 0)
      hours * 3600 + minutes * 60
    }
    _ -> 0
  }
}

/// Get current time as seconds since midnight (local time)
@external(erlang, "tl_backend_time", "now_seconds")
fn get_current_time_seconds() -> Int

fn encode_positions_geojson(positions: List(BusPosition)) -> json.Json {
  json.object([
    #("type", json.string("FeatureCollection")),
    #(
      "features",
      json.array(positions, fn(pos) {
        json.object([
          #("type", json.string("Feature")),
          #(
            "geometry",
            json.object([
              #("type", json.string("Point")),
              #(
                "coordinates",
                json.array([pos.lon, pos.lat], json.float),
              ),
            ]),
          ),
          #(
            "properties",
            json.object([
              #("line", json.string(pos.line)),
              #("destination", json.string(pos.destination)),
            ]),
          ),
        ])
      }),
    ),
  ])
}

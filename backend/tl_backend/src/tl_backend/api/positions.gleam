import gleam/dict
import gleam/dynamic/decode
import gleam/http
import gleam/int
import gleam/json
import gleam/list
import gleam/option.{type Option}
import gleam/result
import gleam/string
import simplifile
import tl_backend/api/transport
import wisp.{type Request, type Response}

/// Stops we monitor for active trips
const monitored_stops = [
  #("8592209", "Renens VD, Censuy"),
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

/// A bus trajectory: the full path with timestamps at each stop
pub type Trajectory {
  Trajectory(
    line: String,
    destination: String,
    route_key: String,
    waypoints: List(Waypoint),
  )
}

pub type Waypoint {
  Waypoint(
    /// Fraction along the route (0.0 = first stop, 1.0 = last stop)
    d: Float,
    /// Unix timestamp (seconds) when the bus is at this point
    t: Int,
  )
}

pub fn handle(req: Request, static_dir: String) -> Response {
  use <- wisp.require_method(req, http.Get)

  let route_stops_path = static_dir <> "/route_stops.json"
  case simplifile.read(route_stops_path) {
    Ok(route_data) -> {
      case compute_trajectories(route_data) {
        Ok(trajectories) -> {
          let body = encode_trajectories(trajectories)
          wisp.json_response(json.to_string(body), 200)
        }
        Error(_) -> wisp.json_response("{\"trajectories\":[]}", 200)
      }
    }
    Error(_) -> wisp.internal_server_error()
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

fn compute_trajectories(
  route_data_json: String,
) -> Result(List(Trajectory), String) {
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
      case parse_route_stops(route_data_json) {
        Ok(route_stops) -> {
          let now_secs = get_current_time_seconds()
          let today_base = get_today_unix_base()
          let deduped = deduplicate_departures(departures, now_secs)

          let trajectories =
            deduped
            |> list.filter_map(fn(dep) {
              build_trajectory(dep, route_stops, now_secs, today_base)
            })

          Ok(trajectories)
        }
        Error(e) -> Error(e)
      }
    }
    Error(e) -> Error(e)
  }
}

fn fetch_stationboard_raw(stop_id: String) -> Result(List(RawDeparture), String) {
  case transport.fetch_stationboard(stop_id) {
    Ok(body) ->
      case parse_raw_departures(body, stop_id) {
        Ok(deps) -> Ok(deps)
        Error(_) -> Ok([])
      }
    Error(_) -> Ok([])
  }
}

fn parse_raw_departures(
  body: String,
  stop_id: String,
) -> Result(List(RawDeparture), String) {
  let decoder = {
    use departures <- decode.field(
      "stationboard",
      decode.list(raw_departure_decoder(stop_id)),
    )
    decode.success(departures)
  }

  case json.parse(body, decoder) {
    Ok(departures) -> Ok(departures)
    Error(_) -> Error("Failed to parse stationboard for " <> stop_id)
  }
}

fn raw_departure_decoder(stop_id: String) -> decode.Decoder(RawDeparture) {
  use stop_name <- decode.subfield(["stop", "station", "name"], decode.string)
  use number <- decode.field("number", decode.string)
  use to <- decode.field("to", decode.string)
  use departure <- decode.subfield(["stop", "departure"], decode.string)
  use delay <- decode.subfield(["stop", "delay"], decode.optional(decode.int))
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

fn parse_route_stops(
  json_str: String,
) -> Result(List(#(String, List(StopTime))), String) {
  let decoder = decode.dict(decode.string, decode.list(stop_time_decoder()))

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

/// Deduplicate departures by (line, destination, 5-min time bucket)
fn deduplicate_departures(
  departures: List(RawDeparture),
  now_secs: Int,
) -> List(RawDeparture) {
  departures
  |> list.sort(fn(a, b) {
    let a_secs =
      int.absolute_value(
        time_string_to_seconds(a.departure_time)
        + option.unwrap(a.delay, 0)
        * 60
        - now_secs,
      )
    let b_secs =
      int.absolute_value(
        time_string_to_seconds(b.departure_time)
        + option.unwrap(b.delay, 0)
        * 60
        - now_secs,
      )
    int.compare(a_secs, b_secs)
  })
  |> list.fold([], fn(acc, dep) {
    let dep_secs =
      time_string_to_seconds(dep.departure_time)
      + option.unwrap(dep.delay, 0)
      * 60
    let bucket = dep_secs / 300

    let dominated =
      list.any(acc, fn(existing: RawDeparture) {
        let ex_secs =
          time_string_to_seconds(existing.departure_time)
          + option.unwrap(existing.delay, 0)
          * 60
        let ex_bucket = ex_secs / 300

        existing.line == dep.line
        && existing.destination == dep.destination
        && bucket == ex_bucket
      })

    case dominated {
      True -> acc
      False -> [dep, ..acc]
    }
  })
  |> list.reverse
}

/// Build a full trajectory for a bus
fn build_trajectory(
  dep: RawDeparture,
  route_stops: List(#(String, List(StopTime))),
  now_secs: Int,
  today_base: Int,
) -> Result(Trajectory, Nil) {
  // Find matching route
  let candidates =
    route_stops
    |> list.filter(fn(entry) {
      let #(key, route_stop_list) = entry
      let parts = string.split(key, "_")
      case parts {
        [line, ..] ->
          line == dep.line
          && list.any(route_stop_list, fn(s) { s.name == dep.stop_name })
        _ -> False
      }
    })

  let matching_route = {
    let direction_match =
      candidates
      |> list.find(fn(entry) {
        let #(key, _) = entry
        let parts = string.split(key, "_")
        case parts {
          [_, ..rest] -> {
            let headsign = string.join(rest, "_")
            string.contains(headsign, dep.destination)
            || string.ends_with(headsign, dep.destination)
          }
          _ -> False
        }
      })
    case direction_match {
      Ok(route) -> Ok(route)
      Error(_) -> list.first(candidates)
    }
  }

  case matching_route {
    Ok(#(route_key, stops)) -> {
      // Find this monitored stop in the route to compute delay offset
      let stop_match =
        stops
        |> list.find(fn(s) { s.name == dep.stop_name })

      case stop_match {
        Ok(matched_stop) -> {
          // Real departure time at this stop (unix seconds)
          let real_dep_secs =
            time_string_to_seconds(dep.departure_time)
            + option.unwrap(dep.delay, 0)
            * 60

          // Template departure time at this stop (seconds since midnight)
          let template_dep_secs = time_string_to_seconds(matched_stop.departure)

          // Delay offset: how many seconds late this bus is
          let delay_offset = real_dep_secs - template_dep_secs

          // Total number of stops for computing distance fractions
          let num_stops = list.length(stops)

          // Build waypoints for every stop on the route
          let waypoints =
            stops
            |> list.index_map(fn(stop, idx) {
              let template_secs = time_string_to_seconds(stop.departure)
              let estimated_unix = today_base + template_secs + delay_offset
              let d = case num_stops > 1 {
                True -> int.to_float(idx) /. int.to_float(num_stops - 1)
                False -> 0.0
              }
              Waypoint(d: d, t: estimated_unix)
            })

          // Only include if the bus is within 10 min of a monitored stop
          let seconds_until = real_dep_secs - now_secs
          case seconds_until > -600 && seconds_until < 600 {
            True ->
              Ok(Trajectory(
                line: dep.line,
                destination: dep.destination,
                route_key: route_key,
                waypoints: waypoints,
              ))
            False -> Error(Nil)
          }
        }
        Error(_) -> Error(Nil)
      }
    }
    Error(_) -> Error(Nil)
  }
}

/// Parse time from ISO datetime or HH:MM:SS to seconds since midnight
fn time_string_to_seconds(time_str: String) -> Int {
  let time_part = case string.contains(time_str, "T") {
    True -> {
      let parts = string.split(time_str, "T")
      case parts {
        [_, rest] -> string.slice(rest, 0, 8)
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

@external(erlang, "tl_backend_time", "now_seconds")
fn get_current_time_seconds() -> Int

@external(erlang, "tl_backend_time", "today_unix_base")
fn get_today_unix_base() -> Int

fn encode_trajectories(trajectories: List(Trajectory)) -> json.Json {
  json.object([
    #(
      "trajectories",
      json.array(trajectories, fn(traj) {
        json.object([
          #("line", json.string(traj.line)),
          #("destination", json.string(traj.destination)),
          #("route_key", json.string(traj.route_key)),
          #(
            "waypoints",
            json.array(traj.waypoints, fn(wp) {
              json.object([
                #("d", json.float(wp.d)),
                #("t", json.int(wp.t)),
              ])
            }),
          ),
        ])
      }),
    ),
  ])
}

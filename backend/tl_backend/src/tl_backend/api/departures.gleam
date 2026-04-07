import gleam/http
import gleam/httpc
import gleam/http/request
import gleam/http/response
import gleam/json
import gleam/dynamic/decode
import gleam/list
import gleam/option.{type Option, None, Some}
import gleam/result
import wisp.{type Request, type Response}

/// Nearby stops around Censuy to aggregate departures from
const stops = [
  #("8592209", "Renens VD, Censuy"),
  #("8592218", "Renens VD, Caudray"),
  #("8593866", "Chavannes-R., Préfaully"),
]

pub fn handle(req: Request) -> Response {
  use <- wisp.require_method(req, http.Get)

  case fetch_all_departures() {
    Ok(departures) -> {
      let body =
        json.object([
          #("departures", json.array(departures, encode_departure)),
        ])
        |> json.to_string
      wisp.json_response(body, 200)
    }
    Error(_) -> {
      wisp.log_error("Failed to fetch departures")
      wisp.internal_server_error()
    }
  }
}

pub type Departure {
  Departure(
    stop_name: String,
    stop_id: String,
    line: String,
    destination: String,
    departure: String,
    delay: Option(Int),
  )
}

fn fetch_all_departures() -> Result(List(Departure), String) {
  stops
  |> list.map(fn(stop) {
    let #(id, _name) = stop
    fetch_stationboard(id)
  })
  |> result.all
  |> result.map(list.flatten)
}

fn fetch_stationboard(stop_id: String) -> Result(List(Departure), String) {
  let url =
    "https://transport.opendata.ch/v1/stationboard?id="
    <> stop_id
    <> "&limit=10"

  let assert Ok(req) = request.to(url)

  case httpc.send(req) {
    Ok(resp) -> parse_stationboard_response(resp, stop_id)
    Error(_) -> Error("HTTP request failed for stop " <> stop_id)
  }
}

fn parse_stationboard_response(
  resp: response.Response(String),
  stop_id: String,
) -> Result(List(Departure), String) {
  let decoder = {
    use departures <- decode.field(
      "stationboard",
      decode.list(departure_decoder(stop_id)),
    )
    decode.success(departures)
  }

  case json.parse(resp.body, decoder) {
    Ok(departures) -> Ok(departures)
    Error(_) -> Error("Failed to parse response for stop " <> stop_id)
  }
}

fn departure_decoder(stop_id stop_id: String) -> decode.Decoder(Departure) {
  use stop_name <- decode.subfield(
    ["stop", "station", "name"],
    decode.string,
  )
  use number <- decode.field("number", decode.string)
  use to <- decode.field("to", decode.string)
  use departure <- decode.subfield(["stop", "departure"], decode.string)
  use delay <- decode.subfield(["stop", "delay"], decode.optional(decode.int))
  decode.success(Departure(
    stop_name: stop_name,
    stop_id: stop_id,
    line: number,
    destination: to,
    departure: departure,
    delay: delay,
  ))
}

fn encode_departure(departure: Departure) -> json.Json {
  json.object([
    #("stop_name", json.string(departure.stop_name)),
    #("stop_id", json.string(departure.stop_id)),
    #("line", json.string(departure.line)),
    #("destination", json.string(departure.destination)),
    #("departure", json.string(departure.departure)),
    #(
      "delay",
      case departure.delay {
        Some(d) -> json.int(d)
        None -> json.null()
      },
    ),
  ])
}

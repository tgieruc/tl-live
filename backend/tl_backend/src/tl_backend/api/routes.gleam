import gleam/http
import simplifile
import wisp.{type Request, type Response}

pub fn handle(req: Request, static_dir: String) -> Response {
  use <- wisp.require_method(req, http.Get)

  let path = static_dir <> "/routes.geojson"
  case simplifile.read(path) {
    Ok(content) -> wisp.json_response(content, 200)
    Error(_) -> {
      wisp.log_error("Could not read routes.geojson")
      wisp.internal_server_error()
    }
  }
}

pub fn handle_stops(req: Request, static_dir: String) -> Response {
  use <- wisp.require_method(req, http.Get)

  let path = static_dir <> "/stops.geojson"
  case simplifile.read(path) {
    Ok(content) -> wisp.json_response(content, 200)
    Error(_) -> {
      wisp.log_error("Could not read stops.geojson")
      wisp.internal_server_error()
    }
  }
}

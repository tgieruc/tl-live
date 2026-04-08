import gleam/http
import tl_backend/api/departures
import tl_backend/api/positions
import tl_backend/api/routes
import tl_backend/context.{type Context}
import wisp.{type Request, type Response}

pub fn handle_request(req: Request, ctx: Context) -> Response {
  use req <- middleware(req, ctx)

  case wisp.path_segments(req) {
    ["api", "departures"] -> departures.handle(req)
    ["api", "routes"] -> routes.handle(req, ctx.static_directory)
    ["api", "stops"] -> routes.handle_stops(req, ctx.static_directory)
    ["api", "positions"] -> positions.handle(req, ctx.static_directory)
    _ -> wisp.not_found()
  }
}

fn middleware(
  req: Request,
  ctx: Context,
  handle_request: fn(Request) -> Response,
) -> Response {
  let req = wisp.method_override(req)
  use <- wisp.log_request(req)
  use <- wisp.rescue_crashes
  use <- wisp.serve_static(req, under: "/static", from: ctx.static_directory)

  use <- cors(req)

  handle_request(req)
}

fn cors(req: Request, next: fn() -> Response) -> Response {
  case req.method {
    http.Options ->
      wisp.ok()
      |> wisp.set_header("access-control-allow-origin", "*")
      |> wisp.set_header("access-control-allow-methods", "GET, OPTIONS")
      |> wisp.set_header("access-control-allow-headers", "content-type")
    _ -> {
      let resp = next()
      resp
      |> wisp.set_header("access-control-allow-origin", "*")
    }
  }
}

import gleam/erlang/process
import mist
import wisp
import wisp/wisp_mist
import tl_backend/router
import tl_backend/cache
import tl_backend/context.{Context}

pub fn main() {
  wisp.configure_logger()
  cache.init()

  let secret_key_base = wisp.random_string(64)
  let ctx = Context(static_directory: static_directory())

  let assert Ok(_) =
    router.handle_request(_, ctx)
    |> wisp_mist.handler(secret_key_base)
    |> mist.new
    |> mist.port(3000)
    |> mist.start

  wisp.log_info("Server started on http://localhost:3000")
  process.sleep_forever()
}

fn static_directory() -> String {
  let assert Ok(priv) = wisp.priv_directory("tl_backend")
  priv <> "/static"
}

-module(tl_backend_time).
-export([now_seconds/0]).

now_seconds() ->
    {H, M, S} = erlang:time(),
    H * 3600 + M * 60 + S.

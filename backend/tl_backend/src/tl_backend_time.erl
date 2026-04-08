-module(tl_backend_time).
-export([now_seconds/0, today_unix_base/0]).

now_seconds() ->
    {H, M, S} = erlang:time(),
    H * 3600 + M * 60 + S.

%% Unix timestamp of today at midnight (local time)
today_unix_base() ->
    erlang:system_time(second) - now_seconds().

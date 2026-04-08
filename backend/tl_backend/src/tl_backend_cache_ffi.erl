-module(tl_backend_cache_ffi).
-export([init/0, get/1, put/3]).

init() ->
    case ets:whereis(tl_cache) of
        undefined ->
            ets:new(tl_cache, [named_table, public, set]),
            nil;
        _ ->
            nil
    end.

get(Key) ->
    case ets:lookup(tl_cache, Key) of
        [{Key, Value, Expiry}] ->
            Now = erlang:system_time(second),
            case Now < Expiry of
                true -> {ok, Value};
                false ->
                    ets:delete(tl_cache, Key),
                    {error, nil}
            end;
        [] ->
            {error, nil}
    end.

put(Key, Value, TtlSeconds) ->
    Expiry = erlang:system_time(second) + TtlSeconds,
    ets:insert(tl_cache, {Key, Value, Expiry}),
    nil.

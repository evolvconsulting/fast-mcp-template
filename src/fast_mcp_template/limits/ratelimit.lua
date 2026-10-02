-- Token bucket. One atomic script per take.
-- KEYS[1] = bucket key (hash: tokens, ts)
-- ARGV[1] = capacity, ARGV[2] = refill period in seconds, ARGV[3] = now in ms
-- Returns {allowed (0/1), tokens left after the take, as text}.
-- Refill is capacity / period per second, capped at capacity. A refusal takes nothing.
local capacity = tonumber(ARGV[1])
local period_ms = tonumber(ARGV[2]) * 1000
local now = tonumber(ARGV[3])

local state = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts = tonumber(state[2])
if tokens == nil or ts == nil then
  tokens = capacity
  ts = now
end

-- A clock that steps backwards refills nothing and never rewinds the stored ts.
local elapsed = math.max(0, now - ts)
tokens = math.min(capacity, tokens + elapsed * capacity / period_ms)

local allowed = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
end

redis.call('HSET', KEYS[1], 'tokens', string.format('%.9f', tokens), 'ts', tostring(math.max(ts, now)))
redis.call('PEXPIRE', KEYS[1], period_ms * 2)
return {allowed, string.format('%.9f', tokens)}

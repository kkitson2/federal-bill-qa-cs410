# Government API rate limits

Last checked November 8, 2026. These published limits can change. The linked service documentation and response headers should guide future runs.

## Personal API key

One api.data.gov key can access both services. The service-specific published limits are listed below. These allowances apply across requests to a service, rather than separately to each endpoint.

| Service | Published limits | Official documentation |
| --- | --- | --- |
| Congress.gov | 5,000 requests per hour | [Congress.gov rate limit](https://github.com/LibraryOfCongress/api.congress.gov#rate-limit) |
| GovInfo | 36,000 requests per hour, 1,200 per minute, and 40 per second | [GovInfo key and rate-limit documentation](https://github.com/usgpo/api#keys) |

GovInfo's shorter-window limits apply alongside its hourly limit. A large remaining hourly allowance does not permit exceeding the per-second or per-minute limit.

api.data.gov documents a generic default of 1,000 requests per hour, while individual services can configure different limits. The table above uses the service-specific documentation. See the [api.data.gov developer manual](https://api.data.gov/docs/developer-manual/#web-service-rate-limits).

## Rolling windows and throttling

- Hourly usage expires on a rolling basis. It does not all reset at the start of the next clock hour.
- Exceeding a rate limit produces HTTP **429 (Too Many Requests)**.
- Inspect `X-RateLimit-Limit` and `X-RateLimit-Remaining` in responses to track the allowance reported by the service.
- Multiple processes using the same key consume its allowance together. Coordinate concurrent collection runs.

Source: [api.data.gov rate-limit behavior and response headers](https://api.data.gov/docs/developer-manual/#web-service-rate-limits).

## Public demo key

The published `DEMO_KEY` limits are **30 requests per IP address per hour** and **50 per IP address per day**. Use a personal key for collection runs. Source: [demo-key limits](https://api.data.gov/docs/developer-manual/#demo_key-rate-limits).

## Pipeline operating notes (data maintainer)

- Keep API keys in local environment configuration, outside Git and exported data.
- Congress.gov uses the `api_key` query parameter; GovInfo uses `X-Api-Key`. Saved URLs omit keys, and echoed keys are redacted.
- A shared limiter spaces request starts at least 0.8 seconds apart within the process. Each resource gets up to six attempts. Transient errors honor `Retry-After` or use exponential backoff; delays above 60 seconds leave a resumable error.
- Successful responses are compressed with receipts and checksums. Rerunning against `data/raw/` reuses verified responses; it does not refresh them. To fetch current sources, move the existing raw folder aside. Use one ingestion process at a time.
- Staging, modeling, publication and database export make no API requests.
- Responses above 25 MB produce an explicit error rather than truncated text. A legitimate larger source requires reviewing that bound before collection.

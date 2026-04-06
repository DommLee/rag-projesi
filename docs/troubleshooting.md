# Troubleshooting

## API not opening
- Check `docker compose ps`
- If port busy, `30_run_api.bat` auto-selects fallback from `18000,18001,18002,8088`
- Check printed `API_HOST_PORT`

## Weaviate unavailable
- In strict mode (`WEAVIATE_STRICT_MODE=true`), queries fail if Weaviate is down.
- For local demo, set strict mode to `false` and use fallback.

## Evaluation reports low citation coverage
- Run ingestion first with real sources.
- Ensure question set has reachable documents in selected date range.
- Switch eval mode to `hybrid` or `real`.

## Crawler blocks/robots disallow
- Legal-safe policy intentionally blocks disallowed routes.
- Use RSS/API/manual PDF fallback sources.

## Docker build issues
- Re-run `00_setup.bat`
- For eval dependencies, `50_eval.bat` installs `requirements-eval.txt` optionally.

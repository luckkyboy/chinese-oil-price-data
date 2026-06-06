# GitHub Actions self-hosted runner for oil price fetch

This runner is designed for `daily-fetch.yml`, which targets:

```yaml
runs-on: [self-hosted, oilprice]
```

The container keeps state in one Docker volume:

- `runner-data`: mounted to `/runner-data`

Inside that volume:

- `/runner-data/actions-runner`: GitHub runner binary and registration
- `/runner-data/_work`: GitHub Actions work directory
- `/runner-data/home`: user cache, including PaddleOCR and CloakBrowser
- `/runner-data/venv`: Python virtual environment used by workflow commands

## Start

1. In GitHub, open the repository:

   `Settings -> Actions -> Runners -> New self-hosted runner`

2. Copy the registration token.

3. Create `.env` from the example:

   ```bash
   cd ops/github-runner
   cp .env.example .env
   ```

4. Edit `.env`:

   ```bash
   GH_REPOSITORY_URL=https://github.com/<owner>/chinese-oil-price-data
   GH_RUNNER_TOKEN=<token from GitHub>
   GH_RUNNER_NAME=oilprice-runner-1
   GH_RUNNER_LABELS=oilprice
   ```

5. Build and start:

   ```bash
   docker compose up -d --build
   ```

6. Check logs:

   ```bash
   docker compose logs -f oilprice-runner
   ```

The first run downloads the GitHub runner, installs Python dependencies, installs CloakBrowser, and warms PaddleOCR models. Later runs reuse Docker volumes and should be much faster.

## Stop

```bash
docker compose stop
```

## Upgrade runner version

Edit `RUNNER_VERSION` in `.env`, then recreate:

```bash
docker compose up -d --build --force-recreate
```

If you remove the `runner-data` volume, you need a fresh `GH_RUNNER_TOKEN` because GitHub registration tokens expire quickly.

## Security

Only run trusted workflows on this runner. Do not allow untrusted pull requests to execute on a self-hosted runner because workflow code runs on your server.

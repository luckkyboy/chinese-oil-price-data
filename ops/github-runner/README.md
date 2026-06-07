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

3. Start the runner with the registration token:

   ```bash
   cd ops/github-runner
   ./github-runner.sh <token from GitHub>
   ```

4. Check logs:

   ```bash
   docker logs -f oilprice-github-runner
   ```

The first run downloads the GitHub runner, installs Python dependencies, installs CloakBrowser, and warms PaddleOCR models. Later runs reuse Docker volumes and should be much faster.

## Stop

```bash
docker stop oilprice-github-runner
```

## Upgrade runner version

Edit `RUNNER_VERSION` in `github-runner.sh`, then recreate:

```bash
./github-runner.sh <token from GitHub>
```

If you remove the runner data directory, you need a fresh registration token because GitHub registration tokens expire quickly.

## Security

Only run trusted workflows on this runner. Do not allow untrusted pull requests to execute on a self-hosted runner because workflow code runs on your server.

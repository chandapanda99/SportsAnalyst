# Container deployment on an Oracle Cloud VM

This is the small personal-hosting path for Open Sports Analyst. It keeps long-lived data in Cloudflare R2, active jobs in Neon PostgreSQL, and only disposable caches on the
VM. The container files are separate from the Windows desktop packaging.

## 1. Prepare the VM

Create an Oracle Cloud Always Free Ampere A1 Ubuntu VM with enough memory for NBA processing. A practical starting point is the full free allocation of 4 OCPUs and 24 GB RAM
when it is available in your region; the Compose limits reserve up to 8 GB for the worker and 2 GB for the API. Keep SSH restricted to your IP. The application does not need
an inbound HTTP port because Cloudflare Tunnel makes outbound connections.

Install Docker Engine and the Compose plugin using Docker's Ubuntu instructions. Confirm the architecture and runtime:

```bash
uname -m
docker version
docker compose version
```

`uname -m` should report `aarch64` on Ampere. Add your user to the `docker` group only if you understand that membership grants root-equivalent access; otherwise use `sudo`
with the Docker commands below.

## 2. Clone and configure the application

```bash
git clone YOUR_REPOSITORY_URL SportsAnalyst
cd SportsAnalyst
cp .env.production.example .env.production
chmod 600 .env.production
```

Edit `.env.production` and set:

- the model provider and credentials;
- the existing Cloudflare R2 endpoint, bucket, access key, and secret;
- Neon's pooled URL in `DATABASE_URL` and direct URL in `DATABASE_MIGRATION_URL`;
- the token for a remotely managed Cloudflare Tunnel in `TUNNEL_TOKEN`.

Keep `PERSISTENCE_BACKEND=s3` and `JOB_BACKEND=postgres`. The API and worker must use the same R2 prefix, database, model settings, and application revision. Do not commit the
populated environment file.

Before adding cloud credentials, you can validate the complete image locally from the repository root:

```bash
bash packaging/container/smoke.sh
```

This uses local disposable storage and verifies the API health endpoint and compiled frontend. It does not exercise Neon, R2, Cloudflare, or the configured model.

## 3. Configure Cloudflare Tunnel

In Cloudflare Zero Trust, create a remotely managed tunnel and add a public hostname for the application. Set its service type to HTTP and its URL to:

```text
http://api:8080
```

Copy the tunnel token—not a general Cloudflare API token—into `TUNNEL_TOKEN`. The API has no host port mapping, so it is reachable from the public internet only through the
`cloudflared` container. Add Cloudflare Access authentication if the hostname should be private to you or a few invited users.

## 4. Build, migrate, and start

```bash
docker compose build
docker compose run --rm api alembic upgrade head
docker compose up -d
docker compose ps
```

The image build performs an application capability/import smoke check. At runtime, Docker also checks `/api/health`. Wait for `api` to become healthy and confirm that
`worker` and `cloudflared` remain running:

```bash
docker compose logs --tail=100 api worker cloudflared
docker compose exec api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/api/health').read().decode())"
docker image inspect open-sports-analyst:local --format '{{.Architecture}}'
```

The last command should report `arm64` when built on the Ampere VM. Then open the Cloudflare hostname and run one small sync and investigation before loading many NBA seasons.

## 5. Operate and update

The named `api-cache` and `worker-cache` volumes are performance caches, not backups. R2 and Neon are the durable systems of record. Recreating either cache must not remove
synced datasets, completed reports, or queued jobs.

To deploy a new revision:

```bash
git pull --ff-only
docker compose build
docker compose run --rm api alembic upgrade head
docker compose up -d --remove-orphans
docker image prune -f
```

Before stopping the stack, inspect running work with `docker compose logs worker`. A graceful stop gives the worker 45 seconds; interrupted jobs can be reclaimed after their
Neon lease expires. Useful commands:

```bash
docker compose ps
docker compose logs -f --tail=100 worker
docker compose restart worker
docker compose down
```

Do not add `-v` to `docker compose down` unless you intentionally want to discard both local caches. Rotate the R2, Neon, model-provider, or tunnel credential immediately if
the environment file is exposed.

## Resource tuning

The default Compose limits are conservative for a 12 GB-or-larger VM: 2 GB for the API, 8 GB for the worker, and 256 MB for `cloudflared`. The worker processes one durable job
at a time. If Oracle gives the VM less memory, reduce the worker limit only after testing the largest intended NBA analysis; lowering it too far can cause the kernel to kill
the worker child. Keep `DATASET_CACHE_MB` materially below the API limit because dataframe conversion, charts, and report generation also need memory.

See [Durable cloud jobs](durable-jobs.md) for queue semantics, retries, leases, and Neon schema management.

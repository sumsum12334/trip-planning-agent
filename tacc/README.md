# TACC deployment package

Docker is intended only for local debugging. TACC deployment uses the two
independent jobs in this package:

- `qwen-public-serve/`: GPU model service.
- Repository root: application/API/UI client job, configured by the root
  `tuxiv.conf`, `job.sh`, and `server-url.txt`.

## Deployment

1. Submit the model service and wait until it prints its `SERVICE_BASE_URL`:

   ```bash
   cd tacc/qwen-public-serve
   tcloud submit
   tcloud ps -j MODEL_JOB_ID
   tcloud cat slurm_log/qwen-public-serve-MODEL_JOB_ID.log
   ```

2. From the repository root, replace `NODE` in `server-url.txt` with the
   service URL, then submit the application:

   ```bash
   cd /path/to/trip-planning-agent
   tcloud submit
   tcloud ps -j APP_JOB_ID
   tcloud cat slurm_log/trip-planning-agent-APP_JOB_ID.log
   ```

3. Open the logged `APP_BASE_URL` from a machine that can reach the TACC node.
   The UI is served by FastAPI; `/health`, `/docs`, `/`, `/api/chat`, and
   `/plan` are all available from the same job.

The application job installs dependencies from `requirements.txt` after
activating the course environment. Keep the model job running while the
application is running. Stop both jobs with `tcloud cancel -j JOB_ID`.

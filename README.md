# Stochastix AI Backend

FastAPI backend for Stochastix AI.

## Deploying to Vercel

Import this repository as a separate Vercel project with the repository root as the project root. The included `vercel.json` packages the runtime `config/`, `data/`, and downloaded Piper voice files, downloads the configured voice during the build, and sets the function duration to the plan's maximum.

Set `NVIDIA_API_KEY` in the Vercel project's Production environment variables for the configured NVIDIA LLM provider. Add any other provider credentials only if you intend to use those providers. Never commit API keys.

The frontend Vercel project proxies `/api/*` to this backend. Use the backend's `stochastix-backend.vercel.app` domain, or change the frontend rewrite destination to the domain assigned by Vercel.

## Vercel runtime considerations

Vercel runs FastAPI as serverless functions, not as the Docker container in `Dockerfile`. The existing upload, order, chat, voice, and video job stores are in memory and are not durable or shared across function instances. Video rendering runs in a background thread, which is not guaranteed to continue after a serverless response. For dependable multi-user or long-running video workflows, move job state and generated files to durable storage and a persistent worker/queue.

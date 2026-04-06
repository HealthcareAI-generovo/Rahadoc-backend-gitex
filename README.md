# RahaDoc AI Backend

FastAPI backend service for RahaDoc AI features: MedScribe, Clinical Copilot, Rx Guard, Patient 360, and Smart Alerts.

## Features

- **MedScribe** - Audio transcription + consultation structuring
- **Clinical Copilot** - Diagnostic assistance with ranked hypotheses
- **Rx Guard** - Three-layer prescription safety checking
- **Patient 360** - AI-generated patient history summaries
- **Smart Alerts** - Automated operational and clinical alerts

## Tech Stack

- **Framework**: FastAPI
- **Python**: 3.11+
- **AI Provider**: Azure OpenAI (GPT-4 + Whisper)
- **Database**: PostgreSQL (shared with Next.js via asyncpg)
- **Settings**: pydantic-settings

## Setup

### 1. Install Dependencies

```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Environment Variables

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

**Required variables:**

- `AZURE_OPENAI_API_KEY` - Your Azure OpenAI API key
- `AZURE_OPENAI_ENDPOINT` - Azure OpenAI endpoint URL
- `AZURE_OPENAI_DEPLOYMENT` - GPT-4 deployment name
- `DATABASE_URL` - PostgreSQL connection string (same as Next.js)
- `INTERNAL_API_SECRET` - Shared secret with Next.js (generate with `openssl rand -base64 32`)
- `CRON_SECRET` - Secret for cron endpoints (generate with `openssl rand -base64 32`)

### 3. Run Locally

```bash
uvicorn app.main:app --reload --port 8000
```

Access:
- API: http://localhost:8000
- Docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

### 4. Run with Docker

```bash
docker build -t rahadoc-ai-backend .
docker run -p 8000:8000 --env-file .env rahadoc-ai-backend
```

## API Endpoints

### MedScribe

- `POST /api/v1/scribe/dictation` - Process post-dictation audio
- `POST /api/v1/scribe/stream` - Ambient mode streaming (SSE)

### Clinical Copilot

- `POST /api/v1/diagnostic/hypotheses` - Generate diagnostic hypotheses

### Rx Guard

- `POST /api/v1/rx-guard/local` - Layer 1+2 checks (fast, no AI)
- `POST /api/v1/rx-guard/ai` - Layer 3 AI-powered checks

### Patient 360

- `POST /api/v1/patient-360/summary` - Generate patient summary

### Smart Alerts

- `POST /api/v1/alerts/process` - Process alerts (cron endpoint)

## Security

All endpoints require `X-Internal-Secret` header with the shared secret.

The alerts endpoint requires `X-Cron-Secret` header.

## Architecture

```
backend/
├── app/
│   ├── main.py                  # FastAPI app
│   ├── config.py                # Settings
│   ├── dependencies.py          # Auth dependencies
│   │
│   ├── api/v1/                  # API routes
│   ├── services/                # Business logic
│   ├── prompts/                 # AI prompts
│   ├── models/                  # Pydantic models
│   ├── rules/                   # Rx Guard rules (JSON)
│   └── db/                      # Database queries
│
├── requirements.txt
├── Dockerfile
└── README.md
```

## Deployment on Railway

1. Create a new Railway project
2. Add this backend as a service
3. Set all environment variables in Railway dashboard
4. Deploy

Railway will automatically detect the Dockerfile and deploy the service.

## Cron Setup (Railway)

Add a cron trigger in Railway:

- **Schedule**: `0 */6 * * *` (every 6 hours)
- **URL**: `/api/v1/alerts/process`
- **Method**: POST
- **Headers**: `X-Cron-Secret: your-cron-secret`

## Development

### Logging

Logs are output to stdout in JSON format suitable for Railway/production.

### Testing

```bash
pytest tests/
```

### Code Quality

```bash
black app/
ruff check app/
mypy app/
```

## License

Proprietary - RahaDoc SaaS

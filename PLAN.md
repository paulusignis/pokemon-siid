# Pokemon TCG ID Analyzer — Architecture & Plan

## What This Does

Scrapes a live Pokemon TCG tournament pairings page, runs a probability simulation,
and tells each player in the "Name" column whether it is statistically safe to
**Intentional Draw (ID)** the upcoming round to secure a top-8 finish.

---

## Architecture

```
GitHub (source) ──► CodePipeline ──► CodeBuild
                                         │
                      ┌──────────────────┼──────────────────┐
                      ▼                  ▼                   ▼
                  Lambda zips       CloudFormation      S3 sync +
                  to S3            deploy/update       CloudFront
                                                       invalidation

User Browser ──► CloudFront ──► S3 (static frontend HTML/JS)
                     │
                     └──► API Gateway ──► API Lambda ──► DynamoDB (cache)
                                               │ (if stale)
                                               └──► Scraper Lambda (live)
                                                          │
                                                    pairings page (HTTP GET)

EventBridge (every 5 min) ──► Scraper Lambda ──► DynamoDB (upsert)
```

---

## AWS Services — All Free Tier

| Service | Purpose | Free Tier |
|---|---|---|
| S3 (2 buckets) | Frontend + pipeline artifacts | 5 GB, 20K GETs |
| CloudFront | HTTPS CDN | 1 TB transfer, 10M req (12 mo) |
| Lambda ×2 | Scraper + API | 1M req/mo, 400K GB-sec (always free) |
| API Gateway v2 | HTTP endpoint | 1M calls/mo (12 mo) |
| DynamoDB | Single-item JSON cache | 1M on-demand req/mo (always free) |
| EventBridge | 5-min cron schedule | Always free |
| CodePipeline | CI/CD from GitHub | 1 free pipeline |
| CodeBuild | Build + deploy | 100 min/mo |
| CloudFormation | IaC | Always free |

---

## Repository Layout

```
pokemon-siid/
├── frontend/
│   ├── index.html        Static page shell
│   ├── style.css         Dark-theme UI
│   └── app.js            Fetches /api/analysis, renders division cards
├── backend/
│   ├── scraper/
│   │   ├── handler.py    Lambda entrypoint (EventBridge + sync invoke)
│   │   ├── scraper.py    HTML fetch + parse (BeautifulSoup)
│   │   ├── computation.py  ID probability simulation
│   │   └── requirements.txt
│   └── api/
│       └── handler.py    API Gateway Lambda (cache check → scraper invoke)
├── backend/tests/
│   ├── test_scraper.py
│   ├── test_computation.py
│   └── test_api_handler.py
├── infrastructure/
│   └── template.yaml     CloudFormation (all resources)
├── buildspec.yml         CodeBuild CI/CD steps
└── PLAN.md               This file
```

---

## ID Analysis Algorithm

For each pairing in a division:

1. Collect **other matches** in the same division.
2. **Simulate** all round outcomes:
   - `n_other ≤ 10` → exhaustive enumeration (`2^n` scenarios)
   - `n_other > 10` → Monte Carlo (10,000 random 50/50 samples)
3. For each scenario compute two sub-scenarios:
   - **ID**: target player +1 pt, opponent +1 pt
   - **Win**: target player +3 pts, opponent +0 pts
4. Rank all players by total points (dense rank; ties share the better rank).
5. Count scenarios where target player finishes top 8 → probability.
6. **Recommend ID** if `P(top8 | ID) − P(top8 | Win) ≥ 0.02`.

---

## Data Format — Pairings Page

HTML tables; each data row has ≥4 cells:

| Col 0 | Col 1 (Name player) | Col 2 | Col 3 (Opponent) |
|---|---|---|---|
| Table # | `Alice Chen, 5-1-0, 15, MA` | _(blank)_ | `Bob Martinez, 5-1-0, 15, MA` |

Cell format: `"name, W-L-T, points, division"`
Divisions: `MA` (Masters), `SR` (Seniors), `JR` (Juniors)
Points: Win=3, Loss=0, Tie=1

---

## DynamoDB Cache Schema

Single item at `pk = "latest"`:

```
pk              "latest"
timestamp       ISO 8601 UTC string
timestamp_epoch Unix epoch integer (used for staleness check)
ttl             epoch + 3600 (DynamoDB auto-expiry)
pairings_url    string
data            JSON string (full analysis result)
scrape_status   "success" | "error"
```

---

## One-Time Manual Setup

**Before running `aws cloudformation deploy`:**

1. **Create CodeStar GitHub Connection**
   - AWS Console → Developer Tools → Connections → Create connection → GitHub
   - Authorize the GitHub App on your repo
   - Wait for status = "Available"
   - Copy the Connection ARN

2. **Create Artifacts S3 bucket** (once):
   ```bash
   aws s3 mb s3://pokemon-siid-artifacts-$(aws sts get-caller-identity --query Account --output text) \
     --region us-west-2
   aws s3api put-bucket-versioning \
     --bucket pokemon-siid-artifacts-ACCOUNTID \
     --versioning-configuration Status=Enabled
   ```

3. **Initial CloudFormation deploy** (after this, CI/CD takes over):
   ```bash
   aws cloudformation deploy \
     --template-file infrastructure/template.yaml \
     --stack-name pokemon-siid \
     --capabilities CAPABILITY_NAMED_IAM \
     --parameter-overrides \
       CodeStarConnectionArn=arn:aws:codestar-connections:REGION:ACCOUNTID:connection/XXXX \
       GitHubOwner=YOUR_GITHUB_USERNAME \
       GitHubRepo=pokemon-siid \
       ArtifactsBucketName=pokemon-siid-artifacts-ACCOUNTID \
       PairingsUrl=https://tabletopvillage.github.io \
     --region us-west-2
   ```

4. **Push to GitHub** — CodePipeline auto-triggers and runs CodeBuild which deploys the real Lambda code.

---

## Post-Deploy Verification

```
[ ] CloudFront distribution status = "Deployed" (can take 5-10 min)
[ ] Visit https://{cloudfront-domain} — see the ID Analyzer page
[ ] Browser console: fetch /api/analysis returns 200 JSON
[ ] AWS Console → EventBridge → Rules → schedule rule is ENABLED
[ ] CloudWatch Logs → /aws/lambda/pokemon-siid-scraper — first scheduled run logged
[ ] DynamoDB → pokemon-siid-cache → item with pk="latest" exists
```

---

## Local Testing

```bash
# Install deps
pip install requests beautifulsoup4 boto3 moto pytest

# Run unit tests
python -m pytest backend/tests/ -v

# Manual integration test (requires internet)
cd backend/scraper
PAIRINGS_URL=https://tabletopvillage.github.io \
CACHE_TABLE_NAME=local-test \
python -c "
from scraper import fetch_pairings, parse_pairings
from computation import compute_id_analysis
import json
html = fetch_pairings('https://tabletopvillage.github.io')
pairings = parse_pairings(html)
print(f'Parsed {len(pairings)} pairings')
print(json.dumps(compute_id_analysis(pairings), indent=2)[:3000])
"
```

---

## Free Tier Watch Points

- **Lambda GB-seconds**: Scraper (256MB×60s=15 GB-sec) × 8,640 invokes/mo ≈ 130K GB-sec. Free limit: 400K. Safe.
- **CodeBuild**: 100 min/mo free. Typical build: 2-3 min → ~33 free deploys/month.
- **CloudFront + API Gateway**: free for 12 months. After that: ~$1/mo at modest traffic.
- **DynamoDB**: PAY_PER_REQUEST, 1M free ops/mo. Single-item pattern stays well within limits.

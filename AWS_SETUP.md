# AWS Account Setup Guide

How to create an IAM user specifically for this project with minimal permissions,
no access to billing or account settings, and budget guardrails to stay within
the AWS free tier.

---

## Step 1 — Secure the Root Account

Before creating any IAM users, harden the root account. Sign into the AWS Console
as root, then go to **IAM → Security recommendations** and complete the following:

- Enable **MFA on root** (use an authenticator app such as Google Authenticator or Authy)
- Do **not** create access keys for root
- From this point on, never use root for day-to-day work

---

## Step 2 — Create the IAM User

In the AWS Console, go to **IAM → Users → Create user**:

| Field | Value |
|---|---|
| Username | `pokemon-siid-deploy` |
| Access type | Access key (for CLI use) |
| Groups | None |
| Permissions | Custom inline policy (see Step 3) |

Save the **Access Key ID** and **Secret Access Key** — you will need these for the
AWS CLI and CodeBuild.

---

## Step 3 — Attach a Minimal IAM Policy

In the user's **Permissions** tab, choose **Add inline policy** and paste the
following JSON. It grants only the services this project uses and explicitly
**denies billing, account, and IAM user/group management**.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ProjectServices",
      "Effect": "Allow",
      "Action": [
        "cloudformation:*",
        "s3:*",
        "lambda:*",
        "apigateway:*",
        "dynamodb:*",
        "events:*",
        "cloudfront:*",
        "codepipeline:*",
        "codebuild:*",
        "codestar-connections:*",
        "logs:*",
        "cloudwatch:*"
      ],
      "Resource": "*"
    },
    {
      "Sid": "IamScopedToProject",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:GetRole",
        "iam:PassRole",
        "iam:PutRolePolicy",
        "iam:DeleteRolePolicy",
        "iam:GetRolePolicy",
        "iam:AttachRolePolicy",
        "iam:DetachRolePolicy",
        "iam:ListRoles",
        "iam:ListRolePolicies",
        "iam:ListAttachedRolePolicies"
      ],
      "Resource": "arn:aws:iam::*:role/pokemon-siid-*"
    },
    {
      "Sid": "DenyBillingAndAccount",
      "Effect": "Deny",
      "Action": [
        "aws-portal:*",
        "billing:*",
        "account:*",
        "organizations:*",
        "support:*",
        "iam:CreateUser",
        "iam:DeleteUser",
        "iam:CreateGroup",
        "iam:DeleteGroup"
      ],
      "Resource": "*"
    }
  ]
}
```

### Why each section exists

**`ProjectServices`** — allows the exact AWS services the project deploys:
S3, CloudFront, Lambda, API Gateway, DynamoDB, EventBridge, CodePipeline,
CodeBuild, CodeStar Connections, and CloudWatch Logs.

**`IamScopedToProject`** — CloudFormation needs to create IAM roles for the
Lambda functions. This allows IAM role management but scoped to role names
that start with `pokemon-siid-*`, matching what the CloudFormation template
creates. It cannot create or modify any other IAM roles.

**`DenyBillingAndAccount`** — explicitly blocks billing console access, account
settings, AWS Organizations, support plan changes, and creation/deletion of
other IAM users or groups. Deny always overrides Allow in AWS IAM.

---

## Step 4 — Free Tier Protection via AWS Budgets

AWS does not hard-stop services when free tier limits are hit — there is no
such built-in feature. Budgets with Budget Actions are the closest equivalent.

### Create a billing alert

Go to **Billing → Budgets → Create budget**:

| Setting | Value |
|---|---|
| Budget type | Cost budget |
| Period | Monthly |
| Budgeted amount | $1.00 |
| Alert threshold | 100% of actual spend |
| Notification | Your email address |

This sends an email the moment any charge appears on your account.

### Add a Budget Action (hard stop)

Under the same budget, add a **Budget Action**:

1. Trigger: actual spend reaches 100% of budget ($1.00)
2. Action type: **Apply IAM policy**
3. Create and attach a policy that denies all actions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EmergencyFreeze",
      "Effect": "Deny",
      "Action": "*",
      "Resource": "*"
    }
  ]
}
```

When triggered, this policy is attached to the `pokemon-siid-deploy` user,
effectively freezing it until you manually remove the policy from the IAM console
(using your root or admin account).

---

## Step 5 — Configure the AWS CLI

```bash
aws configure --profile pokemon-siid
# AWS Access Key ID:     paste from Step 2
# AWS Secret Access Key: paste from Step 2
# Default region:        us-west-2
# Default output format: json
```

Use the `--profile pokemon-siid` flag on all CLI commands for this project:

```bash
aws cloudformation deploy \
  --template-file infrastructure/template.yaml \
  --stack-name pokemon-siid \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    CodeStarConnectionArn=arn:aws:codestar-connections:... \
    GitHubOwner=paulusignis \
    GitHubRepo=pokemon-siid \
    ArtifactsBucketName=pokemon-siid-artifacts-ACCOUNTID \
    PairingsUrl=https://tabletopvillage.github.io \
  --profile pokemon-siid \
  --region us-west-2
```

---

## Free Tier Limits Reference

The table below shows what this project uses against the AWS free tier limits.
All figures are monthly.

| Service | This project uses | Free tier limit | Risk |
|---|---|---|---|
| Lambda invocations | ~8,640 (EventBridge) + API calls | 1M requests | Low |
| Lambda GB-seconds | ~130K (scraper) | 400K | Low |
| DynamoDB requests | ~10K reads + 8,640 writes | 1M on-demand | Low |
| S3 storage | < 5 MB | 5 GB | Low |
| CloudFront requests | Traffic-dependent | 10M (12 mo only) | Low |
| API Gateway calls | Traffic-dependent | 1M (12 mo only) | Low |
| CodeBuild minutes | ~3 min per deploy | 100 min | Medium* |

\* If you push to GitHub more than ~33 times a month, CodeBuild minutes will
exceed the free tier. Each additional minute costs $0.005 — negligible in
practice.

### After 12 months

CloudFront and API Gateway leave the free tier after the first 12 months.
At modest traffic the combined cost is approximately $1–2/month. Set a
calendar reminder at the 11-month mark to review.

---

## Important Caveat

The IAM policy in Step 3 prevents the `pokemon-siid-deploy` user from
provisioning expensive services (RDS, EC2, SageMaker, etc.), but it cannot
enforce free tier usage limits on the services it *can* use. The Budget
Action in Step 4 is your emergency brake if usage unexpectedly exceeds
free tier thresholds.

# AWS Bedrock Models — FedRAMP & DoD Tracker

Unofficial daily tracker of which [Amazon Bedrock models](https://aws.amazon.com/compliance/services-in-scope/FedRAMP/amazon-bedrock-models/)
are certified for regulated environments:

- **U.S. East/West** — FedRAMP Class C (formerly Moderate)
- **U.S. GovCloud** — FedRAMP Class D (formerly High)
- **DoD** — CSP SRG IL4/IL5

🌐 **Site:** https://zarguell.github.io/aws-bedrock-models

## Feeds

One RSS feed per environment plus a combined feed — a new item appears the
morning a model gains availability:

- [All environments](https://zarguell.github.io/aws-bedrock-models/feeds/feed-all.xml)
- [U.S. E/W](https://zarguell.github.io/aws-bedrock-models/feeds/feed-us-ew.xml)
- [GovCloud](https://zarguell.github.io/aws-bedrock-models/feeds/feed-govcloud.xml)
- [DoD](https://zarguell.github.io/aws-bedrock-models/feeds/feed-dod.xml)

Silence means nothing changed. Baseline: August 25, 2026.

## How it works

A scheduled job fetches the AWS page every morning, parses its embedded table
deterministically (no AI — byte-identical input means no output), and republishes
this site only when a model newly appears. See `AGENTS.md` for the repo layout
and `data/` policy.

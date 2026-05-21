# Maintaining an AWS scaled deployment

Day-2 operations for operators who maintain **profile: scaled** infrastructure: upgrades, scaling, backups, Terraform changes, and incident habits. Pair with [Components explained](aws-components.md) and [First-time deploy](aws-first-deploy.md).

## Operating mindset

| Activity | How often | Tool |
|----------|-----------|------|
| Check Dagster runs / Slack alerts | Daily | Dagster UI, Slack |
| Review AWS Cost Explorer | Weekly | AWS Console |
| Apply security patches (OS/AMI) | Monthly | SSM Patch Manager or rebuild |
| Terraform `plan` before changes | Every infra change | Terraform |
| Aurora minor version | Automatic (if enabled) | RDS console |
| Framework Docker image deploy | Ad hoc (~monthly) | ECR + orchestrator |

Keep a simple **runbook** doc in your org (who to call, AWS account ID, `terraform output` file location).

## Aurora PostgreSQL

### Automatic minor upgrades

In RDS → your cluster → **Maintenance**:

- Enable **Auto minor version upgrade** for low-friction security patches.
- Set a **maintenance window** (e.g. Sunday early morning) that matches low API traffic.

Major version jumps (15 → 16) are **manual** and need a test window.

### Scaling capacity

| Signal | Action |
|--------|--------|
| Slow loads / high CPU on writer | Increase `aurora_instance_class` in `terraform.tfvars`, `terraform apply` |
| Disk growth | Aurora storage auto-scales; watch **Cost Explorer** storage line item |
| API read pressure | Add **Aurora reader** instance (Terraform change) or tune API/query patterns |

**Brief downtime** is acceptable in the reference design — resizing the writer may cause a short failover.

### PostGIS and extensions

After major upgrades, verify:

```sql
SELECT PostGIS_Version();
```

Re-run framework provisioning if new schemas were added to `definitions.yml`.

### Backups

- **Backup retention** is set in Terraform (`aurora_backup_retention_days`, default 7).
- Test a **restore to a new cluster** annually in a staging account or snapshot experiment.
- Document restore steps before you need them.

## S3 landing bucket

### Lifecycle and cost

- Objects under `extract/` and `derived/` expire per `landing_lifecycle_expire_days`.
- **Lowering retention** (e.g. 90 → 30 days) reduces storage cost; only do this if you do not need old CSVs for reprocessing.
- One-off long archival for a small dataset can use a separate bucket or prefix without lifecycle.

### Growth drivers

Storage grows with:

- **Number of dataset runs per day** × **CSV size** × **retention days**
- Derived job output size × frequency

Monitor **S3 bucket size** metric in CloudWatch.

## EKS worker capacity

### When to add nodes

| Signal | Action |
|--------|--------|
| Overnight jobs miss SLA | Increase `eks_node_max_size`, `desired_size`, or use larger `eks_node_instance_types` |
| Jobs pending (`Pending`) long time | Cluster autoscaler or manual node group scale |
| Daytime cluster mostly idle | Lower `desired_size` to 0–1 outside batch window |

Steps 21–22 submit **Kubernetes Jobs**; nodes can scale horizontally for **parallel** extract.

### Kubernetes upgrades

- EKS **control plane** version: upgrade one minor at a time in Terraform (`eks_cluster_version`), plan 30+ minutes.
- **Node group** AMI/version follows cluster — drain and roll nodes after control plane upgrade.

### IRSA and service accounts

If landing bucket policies change, update Terraform `modules/eks` IRSA policy and re-apply. Pods need `serviceAccountName` with the annotated role (application Step 21–22).

## EC2 orchestrator and API hosts

### Framework image updates

```bash
docker build -t opendata-etl:<tag> .
docker push <ecr_url>:<tag>
# On instance: docker pull && docker stop/start dagster container
```

Pin tags in production (`:prod`, not `:latest`).

### OS updates

- Prefer **new AMI** + replace instance via Terraform over manual `yum` drift.
- Or use **SSM Patch Manager** for security patches without rebuilding.

### Dagster metadata

Persist `OPENDATA_DEFINITIONS_WORK_DIR` on a volume if you store run history locally; back up if you rely on it for audits.

## Terraform workflow (safe changes)

You are **not** expected to memorize Terraform — follow a checklist:

```bash
cd infra/aws
git pull   # get latest module changes
terraform init -upgrade
terraform plan -out=tfplan
# Review: destroys (red), replaces (yellow), adds (green)
terraform apply tfplan
```

### Change window checklist

1. Notify team (Slack) — maintenance window.
2. Export current outputs: `terraform output > outputs-before.txt`.
3. Run `plan`; if destroy of Aurora or state bucket appears, **stop** and ask for review.
4. Apply during low traffic.
5. Run smoke tests from [First-time deploy](aws-first-deploy.md#part-3--terraform-init-plan-apply).
6. Watch Dagster + API for 24 hours.

### Rollback

- Terraform **does not** auto-rollback — keep previous `tfplan` or re-apply old git commit.
- RDS: restore from snapshot if a bad change affected data.
- Application: redeploy previous Docker tag.

### Remote state

If using S3 backend, **never** delete the state bucket. Enable versioning on the state bucket for recovery.

## Secrets (SSM)

| Task | Steps |
|------|-------|
| Rotate Aurora password | RDS modify master password + update SSM + update `DATABASE_URL` on hosts + restart containers |
| Update API keys table | Framework migration / admin script — separate from infra |
| New `definitions.yml` location | Update SSM `definitions/manifest_s3_uri` parameter |

## Monitoring and Slack

Minimum viable observability:

| Source | Alert on |
|--------|----------|
| CloudWatch | RDS CPU > 80%, free storage low, EKS node NotReady |
| AWS Budget | 80% / 100% of monthly budget |
| Dagster + Slack sensor | Run failures (framework Step 12) |
| API | 5xx rate, latency (ALB or load balancer metrics) |

## Security hygiene

- Tighten `admin_cidr_blocks` if Dagster was opened too wide during setup.
- Review **security group** rules quarterly.
- Rotate IAM access keys if any were created for humans (prefer SSO).
- Audit S3 bucket policy — no public reads on landing or protected copies.

## When to change instance types (quick reference)

| Component | Scale up when | Scale down when |
|-----------|---------------|-----------------|
| Aurora writer | Load CPU high, slow COPY, connection limits | Over-provisioned CPU < 20% always |
| EKS nodes | Job queue backlog overnight | Nodes idle 24/7 |
| Orchestrator EC2 | Dagster UI sluggish, load assets OOM | Only scheduling, load moved to server-side COPY |
| API EC2 | High latency, CPU pegged under public traffic | Low query volume |

## Related

- [Components explained](aws-components.md)
- [First-time deploy](aws-first-deploy.md)
- [Deployment profiles](../deployment-profiles.md)

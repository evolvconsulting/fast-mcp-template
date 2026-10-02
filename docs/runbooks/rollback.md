# Runbook: roll back a deploy

Template runbook (EC-639). Edit the names to your gateway. Every command here is a WRITE to AWS:
run it as the person the deploy role's trust pins, and record the run in the ticket.

## When

- the deploy workflow printed a failure, or the circuit breaker already rolled the service back
  (check first: it may have done the job);
- `/health/ready` is 503 or the 401 / 429 / 5xx rate rose after a stage.

## The rollback target is printed BEFORE the deploy

`deploy.yml` writes "rollback target (the live revision before this deploy)" to the run summary
before it registers anything. If it is gone, read it from the stage file's `rollback_revision`
(record it there after every stage) or from the service history:

```bash
aws ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" \
  --query 'services[0].deployments[].taskDefinition'
```

## Roll back

Dispatch `deploy` with ONLY `rollback_to_revision` set (a positive integer). It updates the
service to `<family>:<revision>` and waits for it to be stable. No image, no stage.

The same by hand, if the workflow cannot run:

```bash
aws ecs update-service --cluster "$CLUSTER" --service "$SERVICE" \
  --task-definition "<family>:<revision>"
aws ecs wait services-stable --cluster "$CLUSTER" --services "$SERVICE"
```

## A build that failed after the push

ECR tags are IMMUTABLE: a `sha-<sha>` tag that exists can never be pushed again. Fix with a NEW
commit; do not try to re-run the build.

## What a rollback does NOT undo

- Secrets Manager values changed during the stage (rotate them forward, see your rotation
  runbook).
- Redis keys written by the newer revision. The keycache records are signed per gateway and
  expire (`key_cache_ttl_seconds`); the stale-serve record never outlives 300 s.
- A stage that retired a credential: roll back to the stage that still accepts it
  (`1-dual` accepts both), and check the census (`infra/cloudwatch/`) before retrying.

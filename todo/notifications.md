# Job Notifications

## Overview

Add notification support for job state changes (completion, failure, etc.).

## Proposed Feature

### Notification Channels

1. **Email** (via SLURM's built-in)
2. **Slack/Discord webhooks**
3. **Desktop notifications** (when on same machine)
4. **Custom webhooks**

### Configuration

```yaml
# .slurm-kit/config.yaml
notifications:
  # Slack webhook
  slack:
    webhook_url: "${SLACK_WEBHOOK_URL}"  # From env var
    channel: "#experiments"
    events:
      - job_completed
      - job_failed
      - collection_completed

  # Discord webhook
  discord:
    webhook_url: "${DISCORD_WEBHOOK_URL}"
    events:
      - job_failed
      - collection_completed

  # Custom webhook
  custom:
    url: "https://my-server.com/webhook"
    method: POST
    headers:
      Authorization: "Bearer ${WEBHOOK_TOKEN}"
    events:
      - all
```

### CLI Commands

```bash
# Test notification setup
slurmkit notify test --channel slack

# Send manual notification
slurmkit notify send "Experiment completed!" --channel slack

# Enable notifications for a collection
slurmkit notify enable --collection my_exp --events completed,failed
```

### Notification Triggers

Events that can trigger notifications:
- `job_submitted`: Job was submitted
- `job_started`: Job started running
- `job_completed`: Job completed successfully
- `job_failed`: Job failed
- `collection_completed`: All jobs in collection done
- `collection_failed`: Any job in collection failed

### Message Templates

```yaml
notifications:
  templates:
    job_completed: |
      ✅ Job completed: {{ job_name }}
      Collection: {{ collection_name }}
      Runtime: {{ elapsed }}
      Cluster: {{ hostname }}

    job_failed: |
      ❌ Job failed: {{ job_name }}
      Collection: {{ collection_name }}
      Exit code: {{ exit_code }}
      Output: {{ output_tail }}
```

## Implementation Notes

### Notification Service

```python
# slurmkit/notifications.py
class NotificationService:
    def send_slack(self, message: str, channel: str) -> bool: ...
    def send_discord(self, message: str) -> bool: ...
    def send_webhook(self, url: str, payload: dict) -> bool: ...
```

### Integration Points

1. **On sync**: Check for state changes and notify
2. **Background daemon**: Optional service to monitor and notify
3. **Post-submit hook**: Notify on submission

### Considerations

- Rate limiting to avoid spam
- Aggregation (batch multiple notifications)
- Secure credential storage
- Retry on network failures

## Use Cases

1. **Long-running experiments**: Get notified when done
2. **Error alerting**: Immediate notification on failures
3. **Team coordination**: Slack channel for shared experiments

## Priority

Low-Medium - Useful but not essential for core functionality.

## Related

- SLURM's `--mail-type` and `--mail-user` options
- Could integrate with existing monitoring systems

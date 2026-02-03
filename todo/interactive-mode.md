# Interactive Mode

## Overview

Add an interactive TUI (Terminal User Interface) mode for browsing and managing jobs.

## Proposed Feature

### Interactive Dashboard

```bash
slurmkit interactive
# or
slurmkit tui
```

Opens a terminal UI with:
- Real-time job status updates
- Collection browser
- Log viewer
- Quick actions (cancel, resubmit)

### UI Components

```
┌─────────────────────────────────────────────────────────────────┐
│ slurmkit - my_experiment                              [q] quit  │
├─────────────────────────────────────────────────────────────────┤
│ Collections: my_exp | exp2 | default                            │
├─────────────────────────────────────────────────────────────────┤
│ Jobs (12 total: 8 completed, 2 running, 2 failed)              │
│ ─────────────────────────────────────────────────────────────── │
│ > train_lr0.001_bs32    12345678    COMPLETED    01:23:45      │
│   train_lr0.001_bs64    12345679    COMPLETED    01:45:12      │
│   train_lr0.01_bs32     12345680    RUNNING      00:30:00      │
│   train_lr0.01_bs64     12345681    FAILED       00:02:15      │
│   train_lr0.1_bs32      12345682    PENDING      --:--:--      │
├─────────────────────────────────────────────────────────────────┤
│ [Enter] View logs  [r] Resubmit  [c] Cancel  [/] Search        │
└─────────────────────────────────────────────────────────────────┘
```

### Features

- **Collection switching**: Tab or arrow keys to switch collections
- **Job list**: Scrollable, filterable job list
- **Log viewer**: Built-in log viewer with search
- **Quick actions**: Keyboard shortcuts for common operations
- **Auto-refresh**: Periodic state updates

### Log Viewer

```
┌─────────────────────────────────────────────────────────────────┐
│ Log: train_lr0.01_bs32 (12345680)                    [q] back  │
├─────────────────────────────────────────────────────────────────┤
│ Loading modules...                                              │
│ Starting training with lr=0.01, bs=32                          │
│ Epoch 1/100: loss=2.345, acc=0.456                             │
│ Epoch 2/100: loss=1.234, acc=0.567                             │
│ ...                                                             │
│ [Following tail - new output will appear]                       │
├─────────────────────────────────────────────────────────────────┤
│ [/] Search  [g] Go to line  [f] Follow  [Home] Top  [End] End  │
└─────────────────────────────────────────────────────────────────┘
```

## Implementation Notes

### Dependencies

Consider using:
- `rich` - For styled output and tables
- `textual` - For full TUI framework
- `blessed` or `curses` - For basic terminal control

### Changes Required

1. **New module**: `slurmkit/tui.py`
2. **CLI command**: `slurmkit interactive` or `slurmkit tui`
3. **Background updates**: Async job state polling

### Considerations

- Keep it optional (don't require TUI deps for basic usage)
- Support for terminals without color/Unicode
- Responsive layout for different terminal sizes
- Keyboard-only navigation

## Use Cases

1. **Monitoring**: Watch job progress in real-time
2. **Quick debugging**: View logs without leaving terminal
3. **Batch operations**: Select multiple jobs for action

## Priority

Low - Nice to have, but CLI commands cover functionality.

## Related

- `watch` command can achieve similar monitoring
- Consider `slurmkit status --watch` as simpler alternative

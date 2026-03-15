#!/bin/bash
#
# Quickstart script for slurmkit demo project
# This script demonstrates a complete workflow from setup to monitoring
#

set -e  # Exit on error

echo "=========================================="
echo "slurmkit Demo Project Quickstart"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print step headers
step() {
    echo ""
    echo -e "${BLUE}===> Step $1: $2${NC}"
    echo ""
}

# Function to print success messages
success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# Function to print warnings
warn() {
    echo -e "${YELLOW}! $1${NC}"
}

# Function to run demo commands without aborting the full quickstart.
run_demo_cmd() {
    local label="$1"
    shift
    echo "  $ $*"
    if "$@"; then
        success "$label"
    else
        warn "$label failed (continuing). Check route/env/webhook configuration."
    fi
}

# Check if slurmkit is installed
if ! command -v slurmkit &> /dev/null; then
    echo "Error: slurmkit is not installed or not in PATH"
    echo "Please install it first: pip install -e ../.."
    exit 1
fi

# =============================================================================
# Step 1: Initialize Configuration
# =============================================================================

step "1" "Initialize slurmkit configuration"

if [ -f ".slurmkit/config.yaml" ]; then
    warn "Configuration already exists. Skipping init."
else
    echo "This will create .slurmkit/config.yaml"
    echo "Press Enter to continue with default values, or Ctrl+C to cancel and run 'slurmkit init' manually"
    read -p ""

    # Note: In a real scenario, you'd run: slurmkit init
    # For this demo, we'll just note it
    warn "Run 'slurmkit init' and configure for your cluster"
fi

# =============================================================================
# Step 2: Review Job Specs
# =============================================================================

step "2" "Review job specifications"

echo "Available demo experiments:"
echo "  1. Parameter Sweep - Grid Mode (6 jobs, ~15 sec each)"
echo "     experiments/hyperparameter_sweep/job_spec.yaml"
echo "     8 combos minus 2 filtered (algo_b + small) = 6 jobs"
echo ""
echo "  2. Parameter List - List Mode (4 jobs, 10-30 sec each)"
echo "     experiments/model_comparison/job_spec.yaml"
echo "     4 explicit parameter combinations"
echo ""

read -p "Which experiment to run? [1/2]: " choice

case $choice in
    1)
        EXPERIMENT="hyperparameter_sweep"
        JOB_SPEC="experiments/hyperparameter_sweep/job_spec.yaml"
        COLLECTION="hp_sweep"
        ;;
    2)
        EXPERIMENT="model_comparison"
        JOB_SPEC="experiments/model_comparison/job_spec.yaml"
        COLLECTION="model_comp"
        ;;
    *)
        echo "Invalid choice. Using hyperparameter_sweep."
        EXPERIMENT="hyperparameter_sweep"
        JOB_SPEC="experiments/hyperparameter_sweep/job_spec.yaml"
        COLLECTION="hp_sweep"
        ;;
esac

success "Selected: $EXPERIMENT"

# =============================================================================
# Step 3: Preview Job Generation
# =============================================================================

step "3" "Preview job generation (dry run)"

slurmkit generate "$JOB_SPEC" --into "$COLLECTION" --dry-run

echo ""
read -p "Press Enter to continue with actual generation..."

# =============================================================================
# Step 4: Generate Jobs
# =============================================================================

step "4" "Generate job scripts"

slurmkit generate "$JOB_SPEC" --into "$COLLECTION"

success "Jobs generated"

# Show generated files
echo ""
echo "Generated files:"
ls -lh ".jobs/$EXPERIMENT/job_scripts/" | head -10

# =============================================================================
# Step 5: Review Collection
# =============================================================================

step "5" "Review collection"

slurmkit collections show "$COLLECTION"

# =============================================================================
# Step 6: Submit Jobs (Optional)
# =============================================================================

step "6" "Submit jobs (optional)"

echo "Do you want to submit these jobs to SLURM?"
echo "  - This will actually submit jobs to the cluster"
echo "  - You can also skip this and submit manually later"
echo ""
read -p "Submit jobs? [y/N]: " submit_choice

if [[ "$submit_choice" =~ ^[Yy]$ ]]; then
    # Dry run first
    echo ""
    echo "Dry run:"
    slurmkit submit "$COLLECTION" --dry-run

    echo ""
    read -p "Proceed with actual submission? [y/N]: " confirm

    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        slurmkit submit "$COLLECTION" --delay 2
        success "Jobs submitted!"

        echo ""
        echo "To monitor jobs:"
        echo "  slurmkit status $COLLECTION"
        echo "  slurmkit collections show $COLLECTION"
        echo "  slurmkit collections analyze $COLLECTION"
        echo "  watch -n 10 'slurmkit status $COLLECTION'"
    else
        echo "Skipped submission."
    fi
else
    echo "Skipped submission."
    echo ""
    echo "To submit later:"
    echo "  slurmkit submit $COLLECTION"
fi

# =============================================================================
# Step 7: Notification Demos (Optional)
# =============================================================================

step "7" "Notification demos (optional)"

echo "This can demo: notify test, notify job, and notify collection-final."
echo "For live delivery (non-dry-run), ensure route credentials are configured."
echo "Formatter callback demo module is available at notification_formatter_callback.py."
echo "Example:"
echo "  export DEMO_WEBHOOK_URL='https://example.com/your-webhook'"
echo "  # or for local email testing:"
echo "  #   python -m aiosmtpd -n -l 127.0.0.1:1025"
echo "  #   export TEST_SMTP_HOST=127.0.0.1 TEST_SMTP_PORT=1025"
echo ""
read -p "Run notification demo commands now? [y/N]: " notify_choice

if [[ "$notify_choice" =~ ^[Yy]$ ]]; then
    read -p "Use dry-run mode for notify commands? [Y/n]: " notify_dry_run_choice
    NOTIFY_FLAGS=()
    if [[ "$notify_dry_run_choice" =~ ^[Nn]$ ]]; then
        warn "Running notify commands without --dry-run (live delivery mode)."
    else
        NOTIFY_FLAGS+=(--dry-run)
        echo "Using --dry-run mode."
    fi

    echo ""
    echo "Preparing deterministic dummy collections..."
    if ./setup_dummy_jobs.py --include-non-terminal; then
        success "Dummy collections created"
    else
        warn "Could not create dummy collections; skipping notification commands."
        NOTIFY_SKIP=1
    fi

    if [[ -z "${NOTIFY_SKIP:-}" ]]; then
        echo ""
        echo "Running notification demos:"
        run_demo_cmd "notify test" slurmkit notify test "${NOTIFY_FLAGS[@]}"
        run_demo_cmd "notify test (local_email formatter callback route)" \
            slurmkit notify test --route local_email "${NOTIFY_FLAGS[@]}"
        run_demo_cmd "notify job (failed)" slurmkit notify job --job-id 990002 --exit-code 1 "${NOTIFY_FLAGS[@]}"
        run_demo_cmd "notify job (completed)" slurmkit notify job --job-id 990001 --exit-code 0 --on always "${NOTIFY_FLAGS[@]}"
        run_demo_cmd "notify collection-final (terminal failed)" \
            slurmkit notify collection-final --collection demo_terminal_failed --job-id 990002 --no-refresh "${NOTIFY_FLAGS[@]}"
        run_demo_cmd "notify collection-final (terminal completed)" \
            slurmkit notify collection-final --collection demo_terminal_completed --job-id 990011 --no-refresh "${NOTIFY_FLAGS[@]}"
        run_demo_cmd "notify collection-final (non-terminal skip)" \
            slurmkit notify collection-final --collection demo_in_progress --job-id 990020 --no-refresh "${NOTIFY_FLAGS[@]}"
    fi

    echo ""
    echo "Optional collection-specific notifications demo:"
    echo "  export PYTHONPATH=\"\$PWD:\$PYTHONPATH\""
    echo "  # uses spec override from experiments/hyperparameter_sweep/job_spec.yaml"
    echo "  slurmkit notify job --collection demo_terminal_failed --job-id 990002 --exit-code 1 --dry-run"
    echo "  slurmkit notify collection-final --collection demo_terminal_failed --job-id 990002 --no-refresh --dry-run"
    echo "  # fallback collection (no spec notifications block) uses .slurmkit/config.yaml"
    echo "  slurmkit notify job --collection demo_terminal_completed --job-id 990011 --exit-code 0 --on always --dry-run"
    echo "  # formatter callback demo (global + route override)"
    echo "  # set notifications.formatter.callback: notification_formatter_callback:format_notification"
    echo "  # set routes[].formatter_callback as needed (or null to opt out)"
    echo "  slurmkit notify test --route local_email --dry-run"
else
    echo "Skipped notification demos."
fi

# =============================================================================
# Summary
# =============================================================================

echo ""
echo "=========================================="
echo "Quickstart Complete!"
echo "=========================================="
echo ""
echo "What was created:"
echo "  - Collection: $COLLECTION"
echo "  - Job scripts: .jobs/$EXPERIMENT/job_scripts/"
echo "  - Collection file: .slurmkit/collections/${COLLECTION}.yaml"
echo ""
echo "Next steps:"
echo "  1. Review generated scripts:"
echo "     ls .jobs/$EXPERIMENT/job_scripts/"
echo "     cat .jobs/$EXPERIMENT/job_scripts/<job_name>.job"
echo ""
echo "  2. Submit jobs (if not done already):"
echo "     slurmkit submit $COLLECTION"
echo ""
echo "  3. Monitor progress:"
echo "     slurmkit status $COLLECTION"
echo "     slurmkit collections show $COLLECTION"
echo "     slurmkit collections analyze $COLLECTION"
echo ""
echo "  4. When jobs complete, inspect tracked output paths:"
echo "     slurmkit collections show $COLLECTION"
echo ""
echo "  5. Handle failures:"
echo "     slurmkit resubmit $COLLECTION --filter failed"
echo ""
echo "  6. Demo collection-final notifications:"
echo "     ./setup_dummy_jobs.py --include-non-terminal"
echo "     export PYTHONPATH=\"\$PWD:\$PYTHONPATH\""
echo "     # demo_terminal_failed uses spec-level notifications override"
echo "     slurmkit notify collection-final --collection demo_terminal_failed --job-id 990002 --no-refresh --dry-run"
echo "     # formatter callback demo"
echo "     slurmkit notify test --route local_email --dry-run"
echo ""
echo "See README.md for more detailed workflows and examples."
echo ""

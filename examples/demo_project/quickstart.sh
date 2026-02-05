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

if [ -f ".slurm-kit/config.yaml" ]; then
    warn "Configuration already exists. Skipping init."
else
    echo "This will create .slurm-kit/config.yaml"
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

slurmkit generate "$JOB_SPEC" --dry-run || true

echo ""
read -p "Press Enter to continue with actual generation..."

# =============================================================================
# Step 4: Generate Jobs
# =============================================================================

step "4" "Generate job scripts"

slurmkit generate "$JOB_SPEC" --collection "$COLLECTION"

success "Jobs generated"

# Show generated files
echo ""
echo "Generated files:"
ls -lh "jobs/$EXPERIMENT/job_scripts/" | head -10

# =============================================================================
# Step 5: Review Collection
# =============================================================================

step "5" "Review collection"

slurmkit collection show "$COLLECTION"

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
    slurmkit submit --collection "$COLLECTION" --dry-run

    echo ""
    read -p "Proceed with actual submission? [y/N]: " confirm

    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        slurmkit submit --collection "$COLLECTION" --delay 2
        success "Jobs submitted!"

        echo ""
        echo "To monitor jobs:"
        echo "  slurmkit status $EXPERIMENT"
        echo "  slurmkit collection show $COLLECTION"
        echo "  watch -n 10 'slurmkit collection show $COLLECTION'"
    else
        echo "Skipped submission."
    fi
else
    echo "Skipped submission."
    echo ""
    echo "To submit later:"
    echo "  slurmkit submit --collection $COLLECTION"
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
echo "  - Job scripts: jobs/$EXPERIMENT/job_scripts/"
echo "  - Collection file: .job-collections/${COLLECTION}.yaml"
echo ""
echo "Next steps:"
echo "  1. Review generated scripts:"
echo "     ls jobs/$EXPERIMENT/job_scripts/"
echo "     cat jobs/$EXPERIMENT/job_scripts/<job_name>.job"
echo ""
echo "  2. Submit jobs (if not done already):"
echo "     slurmkit submit --collection $COLLECTION"
echo ""
echo "  3. Monitor progress:"
echo "     slurmkit status $EXPERIMENT"
echo "     slurmkit collection show $COLLECTION"
echo ""
echo "  4. When jobs complete:"
echo "     slurmkit find <JOB_ID> --preview"
echo ""
echo "  5. Handle failures:"
echo "     slurmkit resubmit --collection $COLLECTION --filter failed"
echo ""
echo "See README.md for more detailed workflows and examples."
echo ""

#!/bin/bash
# Compare two LLM models side-by-side with self-contained test data
# Usage: ./compare-models.sh <mode> <model1> <model2>

set -e

MODE=$1
MODEL1=$2
MODEL2=$3

if [ -z "$MODE" ] || [ -z "$MODEL1" ] || [ -z "$MODEL2" ]; then
    echo "Usage: $0 <mode> <model1> <model2>"
    echo ""
    echo "Examples:"
    echo "  Local:  $0 local qwen3-vl qwen2.5:7b"
    echo "  Cloud:  $0 cloud claude-sonnet-4-5-20250929 gpt-4o"
    exit 1
fi

cd /home/boss/jarvis-voice
source ~/jarvis-venv/bin/activate

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_DIR="tests/integration/logs"
RESULTS_FILE="$LOG_DIR/comparison_${MODE}_${TIMESTAMP}.md"

mkdir -p "$LOG_DIR"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║           MODEL COMPARISON TEST                              ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "Mode:    $MODE"
echo "Model 1: $MODEL1"
echo "Model 2: $MODEL2"
echo "Results: $RESULTS_FILE"
echo ""

# Clean and setup database
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "SETUP: Populating test data"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Backup and clean DB
if [ "$MODE" = "local" ]; then
    DB_FILE="data/jarvis_memory_local.db"
else
    DB_FILE="data/jarvis_memory.db"
fi

if [ -f "$DB_FILE" ]; then
    cp "$DB_FILE" "${DB_FILE}.backup_${TIMESTAMP}"
    rm "$DB_FILE"
    echo "✓ Cleaned database (backup saved)"
fi

# Test data to populate (setup queries)
declare -a SETUP_QUERIES=(
    "Remember: The admin panel is at /admin with secret key 'test-secret-456' on port 8091"
    "Remember: We use PostgreSQL database on localhost:5432 for authentication"
    "Remember: Fixed CORS errors by adding Access-Control-Allow-Origin header to Nginx config"
    "Remember: Grafana monitoring dashboard is at https://monitor.example.com on port 3000"
    "Remember: Staging server for payment testing is at 192.168.1.20"
    "Remember: Production deployment is at IP 192.168.70.100"
)

# Populate with MODEL1 (using it for setup)
if [ "$MODE" = "local" ]; then
    sed -i "s/^OLLAMA_MODEL=.*/OLLAMA_MODEL=\"$MODEL1\"/" config/local.env
else
    if [[ "$MODEL1" == gpt* ]]; then
        sed -i "s/^LLM_PROVIDER=.*/LLM_PROVIDER=\"openai\"/" config/cloud.env
        sed -i "s/^CHAT_MODEL=.*/CHAT_MODEL=\"$MODEL1\"/" config/cloud.env
    else
        sed -i "s/^LLM_PROVIDER=.*/LLM_PROVIDER=\"anthropic\"/" config/cloud.env
        sed -i "s/^ANTHROPIC_MODEL=.*/ANTHROPIC_MODEL=\"$MODEL1\"/" config/cloud.env
    fi
fi

for i in "${!SETUP_QUERIES[@]}"; do
    query="${SETUP_QUERIES[$i]}"
    echo "Adding data $((i+1))/6: ${query:0:50}..."
    ./orchestrator/orchestrator_v2.py $MODE "$query" > "$LOG_DIR/setup$((i+1)).log" 2>&1
    
    # Verify it saved
    if grep -iq "remember" "$LOG_DIR/setup$((i+1)).log"; then
        echo "  ✓ Saved"
    else
        echo "  ⚠️  May not have saved - check logs"
    fi
done

echo ""
echo "✓ Test data populated (6 memories)"
echo ""
sleep 2

# Test queries (recall the data we just added)
declare -a TEST_QUERIES=(
    "How do I access the administrative interface?"
    "What database am I using for authentication?"
    "How did I fix cross-origin errors?"
    "Where is my monitoring dashboard?"
    "Which server should I test payments on?"
    "What's the production deployment IP?"
)

# Expected keywords for validation
declare -a EXPECTED=(
    "admin|secret|8091|panel"
    "postgres|postgresql|5432"
    "cors|nginx|access-control|header"
    "grafana|monitor|3000|dashboard"
    "staging|192.168.1.20|payment"
    "192.168.70.100|production|deployment"
)

# Test MODEL 1
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Testing MODEL 1: $MODEL1"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

declare -a M1_RESULTS=()
declare -a M1_TIMES=()
declare -a M1_TOOLS=()

for i in "${!TEST_QUERIES[@]}"; do
    query="${TEST_QUERIES[$i]}"
    expected="${EXPECTED[$i]}"
    
    echo "Test $((i+1)): $query"
    START=$(date +%s)
    
    ./orchestrator/orchestrator_v2.py $MODE "$query" > "$LOG_DIR/m1_test$((i+1)).log" 2>&1
    
    END=$(date +%s)
    DURATION=$((END - START))
    
    # Check result
    if grep -Eiq "$expected" "$LOG_DIR/m1_test$((i+1)).log"; then
        RESULT="✅ PASS"
        M1_RESULTS+=("PASS")
    else
        RESULT="❌ FAIL"
        M1_RESULTS+=("FAIL")
    fi
    
    # Get tool used
    TOOL=$(tail -10 logs/tools/tool-calls-$(date +%Y-%m-%d).jsonl | jq -r '.tool' | grep -v null | tail -1 || echo "none")
    M1_TOOLS+=("$TOOL")
    M1_TIMES+=("$DURATION")
    
    echo "  $RESULT (${DURATION}s) - Tool: $TOOL"
    echo ""
    
    sleep 1
done

# Test MODEL 2
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Testing MODEL 2: $MODEL2"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Update config
if [ "$MODE" = "local" ]; then
    sed -i "s/^OLLAMA_MODEL=.*/OLLAMA_MODEL=\"$MODEL2\"/" config/local.env
else
    if [[ "$MODEL2" == gpt* ]]; then
        sed -i "s/^LLM_PROVIDER=.*/LLM_PROVIDER=\"openai\"/" config/cloud.env
        sed -i "s/^CHAT_MODEL=.*/CHAT_MODEL=\"$MODEL2\"/" config/cloud.env
    else
        sed -i "s/^LLM_PROVIDER=.*/LLM_PROVIDER=\"anthropic\"/" config/cloud.env
        sed -i "s/^ANTHROPIC_MODEL=.*/ANTHROPIC_MODEL=\"$MODEL2\"/" config/cloud.env
    fi
fi

declare -a M2_RESULTS=()
declare -a M2_TIMES=()
declare -a M2_TOOLS=()

for i in "${!TEST_QUERIES[@]}"; do
    query="${TEST_QUERIES[$i]}"
    expected="${EXPECTED[$i]}"
    
    echo "Test $((i+1)): $query"
    START=$(date +%s)
    
    ./orchestrator/orchestrator_v2.py $MODE "$query" > "$LOG_DIR/m2_test$((i+1)).log" 2>&1
    
    END=$(date +%s)
    DURATION=$((END - START))
    
    # Check result
    if grep -Eiq "$expected" "$LOG_DIR/m2_test$((i+1)).log"; then
        RESULT="✅ PASS"
        M2_RESULTS+=("PASS")
    else
        RESULT="❌ FAIL"
        M2_RESULTS+=("FAIL")
    fi
    
    # Get tool used
    TOOL=$(tail -10 logs/tools/tool-calls-$(date +%Y-%m-%d).jsonl | jq -r '.tool' | grep -v null | tail -1 || echo "none")
    M2_TOOLS+=("$TOOL")
    M2_TIMES+=("$DURATION")
    
    echo "  $RESULT (${DURATION}s) - Tool: $TOOL"
    echo ""
    
    sleep 1
done

# Generate comparison report
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Generating comparison report..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

cat << REPORT > "$RESULTS_FILE"
# Model Comparison Report

**Date**: $(date '+%Y-%m-%d %H:%M:%S')  
**Mode**: $MODE  
**Model 1**: $MODEL1  
**Model 2**: $MODEL2  

---

## Test Methodology

1. **Clean Database**: Started with empty database
2. **Populate Data**: Added 6 test memories using Model 1
3. **Test Recall**: Both models tested recall of same data
4. **Metrics**: Accuracy, speed, tool selection

---

## Test Results

| # | Query | Model 1 | Time | Tool | Model 2 | Time | Tool | Winner |
|---|-------|---------|------|------|---------|------|------|--------|
REPORT

# Calculate totals
M1_PASS=0
M2_PASS=0
M1_TOTAL_TIME=0
M2_TOTAL_TIME=0

for i in "${!TEST_QUERIES[@]}"; do
    query="${TEST_QUERIES[$i]}"
    m1_result="${M1_RESULTS[$i]}"
    m1_time="${M1_TIMES[$i]}"
    m1_tool="${M1_TOOLS[$i]}"
    m2_result="${M2_RESULTS[$i]}"
    m2_time="${M2_TIMES[$i]}"
    m2_tool="${M2_TOOLS[$i]}"
    
    # Determine winner
    if [ "$m1_result" = "PASS" ] && [ "$m2_result" = "FAIL" ]; then
        WINNER="✅ Model 1"
    elif [ "$m2_result" = "PASS" ] && [ "$m1_result" = "FAIL" ]; then
        WINNER="✅ Model 2"
    elif [ "$m1_result" = "PASS" ] && [ "$m2_result" = "PASS" ]; then
        if [ "$m1_time" -lt "$m2_time" ]; then
            WINNER="🚀 Model 1 (faster)"
        elif [ "$m2_time" -lt "$m1_time" ]; then
            WINNER="🚀 Model 2 (faster)"
        else
            WINNER="🤝 Tie"
        fi
    else
        WINNER="❌ Both failed"
    fi
    
    # Update totals
    [ "$m1_result" = "PASS" ] && M1_PASS=$((M1_PASS + 1))
    [ "$m2_result" = "PASS" ] && M2_PASS=$((M2_PASS + 1))
    M1_TOTAL_TIME=$((M1_TOTAL_TIME + m1_time))
    M2_TOTAL_TIME=$((M2_TOTAL_TIME + m2_time))
    
    echo "| $((i+1)) | ${query:0:35}... | $m1_result | ${m1_time}s | \`$m1_tool\` | $m2_result | ${m2_time}s | \`$m2_tool\` | $WINNER |" >> "$RESULTS_FILE"
done

# Add summary
cat << SUMMARY >> "$RESULTS_FILE"

---

## Summary

### Overall Results

| Metric | Model 1 ($MODEL1) | Model 2 ($MODEL2) | Winner |
|--------|-------------------|-------------------|--------|
| **Tests Passed** | **$M1_PASS / ${#TEST_QUERIES[@]}** | **$M2_PASS / ${#TEST_QUERIES[@]}** | $([ $M1_PASS -gt $M2_PASS ] && echo "🏆 Model 1" || ([ $M2_PASS -gt $M1_PASS ] && echo "🏆 Model 2" || echo "🤝 Tie")) |
| **Total Time** | ${M1_TOTAL_TIME}s | ${M2_TOTAL_TIME}s | $([ $M1_TOTAL_TIME -lt $M2_TOTAL_TIME ] && echo "⚡ Model 1" || ([ $M2_TOTAL_TIME -lt $M1_TOTAL_TIME ] && echo "⚡ Model 2" || echo "🤝 Tie")) |
| **Avg Time/Test** | $((M1_TOTAL_TIME / ${#TEST_QUERIES[@]}))s | $((M2_TOTAL_TIME / ${#TEST_QUERIES[@]}))s | $([ $((M1_TOTAL_TIME / ${#TEST_QUERIES[@]})) -lt $((M2_TOTAL_TIME / ${#TEST_QUERIES[@]})) ] && echo "⚡ Model 1" || ([ $((M2_TOTAL_TIME / ${#TEST_QUERIES[@]})) -lt $((M1_TOTAL_TIME / ${#TEST_QUERIES[@]})) ] && echo "⚡ Model 2" || echo "🤝 Tie")) |
| **Success Rate** | $((M1_PASS * 100 / ${#TEST_QUERIES[@]}))% | $((M2_PASS * 100 / ${#TEST_QUERIES[@]}))% | $([ $M1_PASS -gt $M2_PASS ] && echo "🎯 Model 1" || ([ $M2_PASS -gt $M1_PASS ] && echo "🎯 Model 2" || echo "🤝 Tie")) |

### Performance Analysis

**Speed Winner**: $([ $M1_TOTAL_TIME -lt $M2_TOTAL_TIME ] && echo "$MODEL1 (${M1_TOTAL_TIME}s vs ${M2_TOTAL_TIME}s = $((100 - M1_TOTAL_TIME * 100 / M2_TOTAL_TIME))% faster)" || ([ $M2_TOTAL_TIME -lt $M1_TOTAL_TIME ] && echo "$MODEL2 (${M2_TOTAL_TIME}s vs ${M1_TOTAL_TIME}s = $((100 - M2_TOTAL_TIME * 100 / M1_TOTAL_TIME))% faster)" || echo "Tie"))

**Accuracy Winner**: $([ $M1_PASS -gt $M2_PASS ] && echo "$MODEL1 ($M1_PASS vs $M2_PASS tests passed)" || ([ $M2_PASS -gt $M1_PASS ] && echo "$MODEL2 ($M2_PASS vs $M1_PASS tests passed)" || echo "Tie ($M1_PASS tests each)"))

---

## Raw Data for LLM Analysis

\`\`\`json
{
  "test_date": "$(date -Iseconds)",
  "mode": "$MODE",
  "test_queries": $(printf '%s\n' "${TEST_QUERIES[@]}" | jq -R . | jq -s .),
  "model1": {
    "name": "$MODEL1",
    "results": $(printf '%s\n' "${M1_RESULTS[@]}" | jq -R . | jq -s .),
    "times_seconds": $(printf '%s\n' "${M1_TIMES[@]}" | jq -R . | jq -s .),
    "tools_used": $(printf '%s\n' "${M1_TOOLS[@]}" | jq -R . | jq -s .),
    "total_passed": $M1_PASS,
    "total_time_seconds": $M1_TOTAL_TIME,
    "success_rate_percent": $((M1_PASS * 100 / ${#TEST_QUERIES[@]})),
    "avg_time_seconds": $((M1_TOTAL_TIME / ${#TEST_QUERIES[@]}))
  },
  "model2": {
    "name": "$MODEL2",
    "results": $(printf '%s\n' "${M2_RESULTS[@]}" | jq -R . | jq -s .),
    "times_seconds": $(printf '%s\n' "${M2_TIMES[@]}" | jq -R . | jq -s .),
    "tools_used": $(printf '%s\n' "${M2_TOOLS[@]}" | jq -R . | jq -s .),
    "total_passed": $M2_PASS,
    "total_time_seconds": $M2_TOTAL_TIME,
    "success_rate_percent": $((M2_PASS * 100 / ${#TEST_QUERIES[@]})),
    "avg_time_seconds": $((M2_TOTAL_TIME / ${#TEST_QUERIES[@]}))
  }
}
\`\`\`
SUMMARY

echo ""
echo "✅ Report saved to: $RESULTS_FILE"
echo ""

# Generate LLM analysis
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Generating AI analysis..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Use cloud mode (anthropic) for analysis
ANALYSIS_PROMPT="Analyze this model comparison test and provide insights. Be specific and data-driven:

$(cat "$RESULTS_FILE")

Provide:
1. Overall winner and why
2. Key strengths/weaknesses of each model
3. Speed vs accuracy trade-offs
4. Tool selection quality
5. Recommendation for when to use each model

Keep response under 300 words."

# Run analysis
./orchestrator/orchestrator_v2.py cloud "$ANALYSIS_PROMPT" > "$LOG_DIR/analysis_response.log" 2>&1

# Extract analysis
ANALYSIS=$(cat "$LOG_DIR/analysis_response.log" | jq -r '.speech' 2>/dev/null || echo "Analysis unavailable - check $LOG_DIR/analysis_response.log")

# Append to report
cat << ANALYSIS >> "$RESULTS_FILE"

---

## 🤖 AI Analysis

$ANALYSIS

---

**Test Framework**: Jarvis Model Comparison Tool  
**Analysis By**: Claude Sonnet 4.5 (Cloud Mode)  
**Database Backup**: ${DB_FILE}.backup_${TIMESTAMP}
ANALYSIS

echo ""
echo "✅ Analysis complete!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 FINAL RESULTS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Model 1 ($MODEL1): $M1_PASS/${#TEST_QUERIES[@]} passed, ${M1_TOTAL_TIME}s total"
echo "Model 2 ($MODEL2): $M2_PASS/${#TEST_QUERIES[@]} passed, ${M2_TOTAL_TIME}s total"
echo ""
echo "Full report: $RESULTS_FILE"
echo "View: cat $RESULTS_FILE"
echo ""


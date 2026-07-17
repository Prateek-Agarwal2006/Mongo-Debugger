package ftdc

import "time"

// ExportedFormula exposes assessment score formulas for downstream RCA agents.
type ExportedFormula struct {
	Label   string `json:"label"`
	Formula string `json:"formula"`
	Low     int    `json:"low"`
	High    int    `json:"high"`
}

// ExportedMetricStats is the JSON-safe representation of internal metricStats.
type ExportedMetricStats struct {
	Label  string  `json:"label"`
	Median float64 `json:"median"`
	P5     float64 `json:"p5"`
	P95    float64 `json:"p95"`
	Score  int     `json:"score"`
}

// ExportedDiagnosisResult preserves rule output without function fields.
type ExportedDiagnosisResult struct {
	Name        string    `json:"name"`
	Description string    `json:"description"`
	Severity    string    `json:"severity"`
	Symptoms    []string  `json:"symptoms"`
	Suggestion  string    `json:"suggestion"`
	Score       int       `json:"score"`
	DetectedAt  time.Time `json:"detected_at"`
}

// ExportedDiagnosis contains all structured data produced by the diagnosis engine.
type ExportedDiagnosis struct {
	From            time.Time                                 `json:"from"`
	To              time.Time                                 `json:"to"`
	DurationSeconds float64                                   `json:"duration_seconds"`
	ActivitySummary ActivitySummary                           `json:"activity_summary"`
	Metrics         map[string]ExportedMetricStats            `json:"metrics"`
	DiskMetrics     map[string]map[string]ExportedMetricStats `json:"disk_metrics"`
	ReplMetrics     map[string]ExportedMetricStats            `json:"repl_metrics"`
	Anomalies       []AnomalyEvent                            `json:"anomalies"`
	Findings        []ExportedDiagnosisResult                 `json:"findings"`
}

// ExportFormulas returns the assessment formula catalog with unexported fields expanded.
func ExportFormulas() map[string]ExportedFormula {
	out := make(map[string]ExportedFormula, len(FormulaMap))
	for k, v := range FormulaMap {
		out[k] = ExportedFormula{Label: v.label, Formula: v.formula, Low: v.low, High: v.high}
	}
	return out
}

// ExportDiagnosis runs diagnosis and exposes the internal metrics/anomalies used to print the report.
func ExportDiagnosis(stats FTDCStats, from time.Time, to time.Time) ExportedDiagnosis {
	d := NewDiagnosis(stats, from, to)
	results := d.Run()

	metrics := make(map[string]ExportedMetricStats, len(d.metrics))
	for k, v := range d.metrics {
		metrics[k] = exportMetricStats(v)
	}

	diskMetrics := make(map[string]map[string]ExportedMetricStats, len(d.diskMetrics))
	for disk, values := range d.diskMetrics {
		diskMetrics[disk] = make(map[string]ExportedMetricStats, len(values))
		for k, v := range values {
			diskMetrics[disk][k] = exportMetricStats(v)
		}
	}

	replMetrics := make(map[string]ExportedMetricStats, len(d.replMetrics))
	for k, v := range d.replMetrics {
		replMetrics[k] = exportMetricStats(v)
	}

	findings := make([]ExportedDiagnosisResult, 0, len(results))
	for _, r := range results {
		findings = append(findings, ExportedDiagnosisResult{
			Name:        r.Rule.Name,
			Description: r.Rule.Description,
			Severity:    r.Rule.Severity,
			Symptoms:    r.Symptoms,
			Suggestion:  r.Rule.Suggestion,
			Score:       r.Score,
			DetectedAt:  r.DetectedAt,
		})
	}

	return ExportedDiagnosis{
		From:            from,
		To:              to,
		DurationSeconds: d.duration.Seconds(),
		ActivitySummary: d.summary,
		Metrics:         metrics,
		DiskMetrics:     diskMetrics,
		ReplMetrics:     replMetrics,
		Anomalies:       d.anomalies,
		Findings:        findings,
	}
}

func exportMetricStats(v metricStats) ExportedMetricStats {
	return ExportedMetricStats{
		Label:  v.label,
		Median: v.median,
		P5:     v.p5,
		P95:    v.p95,
		Score:  v.score,
	}
}

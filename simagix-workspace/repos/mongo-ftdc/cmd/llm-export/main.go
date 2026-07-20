package main

import (
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/simagix/gox"
	ftdc "github.com/simagix/mongo-ftdc"
	"github.com/simagix/mongo-ftdc/decoder"
)

const contractVersion = "1.0.0"

type fileSummary struct {
	Path              string `json:"path"`
	Blocks            int    `json:"blocks"`
	RawMetricSeries   int    `json:"raw_metric_series"`
	ExpandedRawValues int    `json:"expanded_raw_values"`
}

type manifest struct {
	ContractVersion         string        `json:"contract_version"`
	GeneratedAt             time.Time     `json:"generated_at"`
	Input                   string        `json:"input"`
	Latest                  int           `json:"latest"`
	ExportTier              string        `json:"export_tier"`
	FilesConsidered         int           `json:"files_considered"`
	FilesExported           int           `json:"files_exported"`
	TimeRange               timeRangeInfo `json:"time_range"`
	MongoDBVersion          string        `json:"mongodb_version"`
	Host                    string        `json:"host"`
	NormalizedMetricSeries  int           `json:"normalized_metric_series"`
	DiskDevices             int           `json:"disk_devices"`
	ReplicationLagSeries    int           `json:"replication_lag_series"`
	ServerStatusSamples     int           `json:"server_status_samples"`
	SystemMetricsSamples    int           `json:"system_metrics_samples"`
	ReplSetStatusSamples    int           `json:"replset_status_samples"`
	DiagnosisFindings       int           `json:"diagnosis_findings"`
	AnomalyEvents           int           `json:"anomaly_events"`
	RawMetricSeriesExported int           `json:"raw_metric_series_exported"`
	RawValuesExported       int           `json:"raw_values_exported"`
	Files                   []fileSummary `json:"files"`
}

type timeRangeInfo struct {
	From            time.Time `json:"from"`
	To              time.Time `json:"to"`
	DurationSeconds float64   `json:"duration_seconds"`
}

type metricCatalogEntry struct {
	Name           string  `json:"name"`
	Source         string  `json:"source"`
	Points         int     `json:"points"`
	FirstTimestamp float64 `json:"first_timestamp,omitempty"`
	LastTimestamp  float64 `json:"last_timestamp,omitempty"`
}

type assessmentHighlight struct {
	Metric string  `json:"metric"`
	Label  string  `json:"label"`
	Score  int     `json:"score"`
	P95    float64 `json:"p95"`
}

type anomalyWindowSummary struct {
	Metric    string    `json:"metric"`
	Severity  string    `json:"severity"`
	Peak      float64   `json:"peak"`
	Threshold string    `json:"threshold"`
	From      time.Time `json:"from"`
	To        time.Time `json:"to"`
	DurationS float64   `json:"duration_seconds"`
}

type scoreSemantics struct {
	Range                string   `json:"range"`
	Healthy              string   `json:"100"`
	Unhealthy            string   `json:"0"`
	Interpolated         string   `json:"1_to_99"`
	NotAssessed          string   `json:"101"`
	NotAssessedReasons   []string `json:"101_reasons"`
	LLMGuidance          string   `json:"llm_guidance"`
}

type executiveContext struct {
	ContractVersion       string                         `json:"contract_version"`
	Instruction           string                         `json:"instruction"`
	ScoreSemantics        scoreSemantics                 `json:"score_semantics"`
	TimeRange             timeRangeInfo                  `json:"time_range"`
	Host                  string                         `json:"host"`
	MongoDBVersion        string                         `json:"mongodb_version"`
	ActivitySummary       ftdc.ActivitySummary           `json:"activity_summary"`
	Findings              []ftdc.ExportedDiagnosisResult `json:"findings"`
	TopAnomalyWindows     []anomalyWindowSummary         `json:"top_anomaly_windows"`
	AssessmentHighlights  []assessmentHighlight          `json:"assessment_highlights"`
	AnomalyEventCount     int                            `json:"anomaly_event_count"`
	ReadOrder             []string                       `json:"read_order"`
	FallbackFiles         map[string]string              `json:"fallback_files"`
	RecommendedMetrics    []string                       `json:"recommended_metrics"`
}

type fallbackRetrievalEntry struct {
	Metric          string        `json:"metric"`
	Source          string        `json:"source"`
	SourceFile      string        `json:"source_file"`
	Tier            string        `json:"tier"`
	Window          timeRangeInfo `json:"window,omitempty"`
	RelatedFinding  string        `json:"related_finding,omitempty"`
	Points          int           `json:"points,omitempty"`
}

type bundleIndexEntry struct {
	Path   string `json:"path"`
	Tier   string `json:"tier"`
	Size   int64  `json:"size_bytes"`
	SHA256 string `json:"sha256,omitempty"`
}

type validationResult struct {
	ContractVersion string    `json:"contract_version"`
	ValidatedAt     time.Time `json:"validated_at"`
	Valid           bool      `json:"valid"`
	ExportTier      string    `json:"export_tier"`
	Errors          []string  `json:"errors"`
	Warnings        []string  `json:"warnings"`
	Tier1Complete   bool      `json:"tier_1_complete"`
	Tier2Present    bool      `json:"tier_2_present"`
	Tier3Present    bool      `json:"tier_3_present"`
}

type rawBlockLine struct {
	SourceFile  string `json:"source_file"`
	BlockIndex  int    `json:"block_index"`
	NumDeltas   uint32 `json:"num_deltas"`
	MetricCount int    `json:"metric_count"`
}

type rawMetricLine struct {
	SourceFile string   `json:"source_file"`
	BlockIndex int      `json:"block_index"`
	Path       string   `json:"path"`
	Values     []uint64 `json:"values"`
}

type rawServerInfoLine struct {
	SourceFile string      `json:"source_file"`
	ServerInfo interface{} `json:"server_info"`
}

func main() {
	input := flag.String("input", "", "FTDC file or diagnostic.data directory")
	output := flag.String("output", "", "export output directory")
	latest := flag.Int("latest", 0, "latest n files to export; 0 means all files")
	includeRaw := flag.Bool("raw", false, "export raw decoder DataPointsMap (forensic tier)")
	tier := flag.String("tier", "normalized", "export tier: analyzed, normalized, forensic")
	flag.Parse()

	if *input == "" || *output == "" {
		fmt.Fprintln(os.Stderr, "usage: llm-export -input <diagnostic.data> -output <export-dir> [-latest 0] [-tier normalized] [-raw=false]")
		os.Exit(2)
	}

	exportTier := strings.ToLower(strings.TrimSpace(*tier))
	switch exportTier {
	case "analyzed", "normalized", "forensic":
	default:
		fmt.Fprintf(os.Stderr, "invalid -tier %q: use analyzed, normalized, or forensic\n", *tier)
		os.Exit(2)
	}
	if exportTier == "forensic" {
		*includeRaw = true
	}

	if err := run(*input, *output, *latest, exportTier, *includeRaw); err != nil {
		fmt.Fprintln(os.Stderr, "llm-export:", err)
		os.Exit(1)
	}
}

func run(input string, output string, latest int, exportTier string, includeRaw bool) error {
	files := ftdc.GetMetricsFilenames([]string{input})
	sort.Strings(files)
	filesConsidered := len(files)
	if latest > 0 && latest < len(files) {
		files = files[len(files)-latest:]
	}
	if len(files) == 0 {
		return fmt.Errorf("no metrics files found under %s", input)
	}

	if err := makeDirs(output); err != nil {
		return err
	}

	metrics := ftdc.NewMetrics()
	metrics.SetLatest(latest)
	metrics.SetVerbose(true)
	if err := metrics.ProcessFiles([]string{input}); err != nil {
		return err
	}

	stats := metrics.GetFTDCStats()
	from, to := metrics.GetTimeRange()
	tr := timeRangeInfo{From: from, To: to, DurationSeconds: to.Sub(from).Seconds()}
	diagnosis := ftdc.ExportDiagnosis(stats, from, to)
	assessment := ftdc.NewAssessment(stats)
	assessment.SetVerbose(true)

	if err := writeJSON(filepath.Join(output, "manifest.pre.json"), map[string]interface{}{
		"authoritative":    false,
		"note":             "Non-authoritative checkpoint written before export completes.",
		"contract_version": contractVersion,
		"input":            input,
		"latest":           latest,
		"export_tier":      exportTier,
		"files_considered": filesConsidered,
		"files_exported":   len(files),
		"generated_at":     time.Now().UTC(),
		"time_range":       tr,
		"mongodb_version":  stats.ServerInfo.BuildInfo.Version,
		"host":             stats.ServerInfo.HostInfo.System.Hostname,
	}); err != nil {
		return err
	}

	if exportTier != "analyzed" {
		if err := exportNormalized(output, stats); err != nil {
			return err
		}
	}

	if err := writeJSON(filepath.Join(output, "assessment", "assessment.json"), assessment.GetAssessment(from, to)); err != nil {
		return err
	}
	if err := writeJSON(filepath.Join(output, "assessment", "formulas.json"), ftdc.ExportFormulas()); err != nil {
		return err
	}
	if err := writeJSON(filepath.Join(output, "diagnosis", "diagnosis.json"), diagnosis); err != nil {
		return err
	}
	if err := writeJSON(filepath.Join(output, "diagnosis", "activity_summary.json"), diagnosis.ActivitySummary); err != nil {
		return err
	}
	if err := writeJSON(filepath.Join(output, "diagnosis", "anomaly_timeline.json"), diagnosis.Anomalies); err != nil {
		return err
	}
	if err := writeJSON(filepath.Join(output, "diagnosis", "findings.json"), diagnosis.Findings); err != nil {
		return err
	}

	rawSummaries := []fileSummary{}
	rawMetricSeries := 0
	rawValues := 0
	if includeRaw {
		var err error
		rawSummaries, rawMetricSeries, rawValues, err = exportRaw(output, files)
		if err != nil {
			return err
		}
	}

	catalog := []metricCatalogEntry{}
	if exportTier != "analyzed" {
		catalog = buildMetricCatalog(stats)
		if err := writeJSON(filepath.Join(output, "metric_catalog.json"), catalog); err != nil {
			return err
		}
	}

	topWindows := buildTopAnomalyWindows(diagnosis.Anomalies, 15)
	highlights := buildAssessmentHighlights(diagnosis)
	fallbackFiles := buildFallbackFiles(exportTier, includeRaw)

	ctx := executiveContext{
		ContractVersion: contractVersion,
		Instruction:     "Use this analyzed mongo-ftdc report as primary evidence. Do not rediscover health issues from raw metrics. Request fallback metric slices only when more proof is needed.",
		ScoreSemantics: scoreSemantics{
			Range:        "0-100 are health scores; lower is worse",
			Healthy:      "100 = metric below low watermark",
			Unhealthy:    "0 = metric above high watermark",
			Interpolated: "1-99 = proportional between watermarks",
			NotAssessed:  "101 = not assessed / unavailable (N/A sentinel — NOT healthy)",
			NotAssessedReasons: []string{
				"no scoring formula in FormulaMap (e.g. conns_active)",
				"metric missing from FTDC data",
				"NaN during score calculation",
				"insufficient data to compute score",
			},
			LLMGuidance: "Ignore score 101 for health conclusions. Use findings and anomalies for RCA.",
		},
		TimeRange:       tr,
		Host:            stats.ServerInfo.HostInfo.System.Hostname,
		MongoDBVersion:  stats.ServerInfo.BuildInfo.Version,
		ActivitySummary: diagnosis.ActivitySummary,
		Findings:        diagnosis.Findings,
		TopAnomalyWindows: topWindows,
		AssessmentHighlights: highlights,
		AnomalyEventCount: len(diagnosis.Anomalies),
		ReadOrder: []string{
			"llm/executive_context.json",
			"diagnosis/findings.json",
			"diagnosis/anomaly_timeline.json",
			"diagnosis/activity_summary.json",
			"assessment/assessment.json",
			"assessment/formulas.json",
		},
		FallbackFiles: fallbackFiles,
		RecommendedMetrics: []string{
			"replication_lags", "cpu_idle", "cpu_iowait", "write_conflicts/s",
			"txn_aborted/s", "flowctl_lagged_count", "flowctl_acquiring_us",
			"queues_read_out", "queues_write_out", "wt_cache_used", "wt_cache_dirty",
			"ticket_avail_read", "ticket_avail_write", "ops_query", "ops_update",
			"ops_command", "latency_read", "latency_write", "latency_command",
			"scan_keys", "scan_objects",
		},
	}
	if err := writeJSON(filepath.Join(output, "llm", "executive_context.json"), ctx); err != nil {
		return err
	}

	fallbackIndex := buildFallbackRetrievalIndex(catalog, diagnosis, tr, exportTier)
	if err := writeJSON(filepath.Join(output, "llm", "fallback_retrieval_index.json"), fallbackIndex); err != nil {
		return err
	}

	finalManifest := manifest{
		ContractVersion:         contractVersion,
		GeneratedAt:             time.Now().UTC(),
		Input:                   input,
		Latest:                  latest,
		ExportTier:              exportTier,
		FilesConsidered:         filesConsidered,
		FilesExported:           len(files),
		TimeRange:               tr,
		MongoDBVersion:          stats.ServerInfo.BuildInfo.Version,
		Host:                    stats.ServerInfo.HostInfo.System.Hostname,
		NormalizedMetricSeries:  len(stats.TimeSeriesData),
		DiskDevices:             len(stats.DiskStats),
		ReplicationLagSeries:    len(stats.ReplicationLags),
		ServerStatusSamples:     len(stats.ServerStatusList),
		SystemMetricsSamples:    len(stats.SystemMetricsList),
		ReplSetStatusSamples:    len(stats.ReplSetStatusList),
		DiagnosisFindings:       len(diagnosis.Findings),
		AnomalyEvents:           len(diagnosis.Anomalies),
		RawMetricSeriesExported: rawMetricSeries,
		RawValuesExported:       rawValues,
		Files:                   rawSummaries,
	}

	if err := writeJSONAtomic(filepath.Join(output, "manifest.json"), finalManifest); err != nil {
		return err
	}

	bundleIndex, err := buildBundleIndex(output, exportTier, includeRaw)
	if err != nil {
		return err
	}
	if err := writeJSON(filepath.Join(output, "bundle_index.json"), bundleIndex); err != nil {
		return err
	}

	validation := validateBundle(output, exportTier, includeRaw, finalManifest, bundleIndex)
	if err := writeJSON(filepath.Join(output, "validation.json"), validation); err != nil {
		return err
	}
	if !validation.Valid {
		return fmt.Errorf("export validation failed: %s", strings.Join(validation.Errors, "; "))
	}

	fmt.Printf("LLM export complete: %s\n", output)
	fmt.Printf("Export tier: %s\n", exportTier)
	fmt.Printf("Files exported: %d (latest=%d, considered=%d)\n", len(files), latest, filesConsidered)
	fmt.Printf("Findings: %d, anomalies: %d, top windows: %d\n", len(diagnosis.Findings), len(diagnosis.Anomalies), len(topWindows))
	if includeRaw {
		fmt.Printf("Raw metric series: %d, raw values: %d\n", rawMetricSeries, rawValues)
	}
	return nil
}

func buildFallbackFiles(exportTier string, includeRaw bool) map[string]string {
	files := map[string]string{
		"manifest":           "manifest.json",
		"bundle_index":       "bundle_index.json",
		"validation":         "validation.json",
		"fallback_index":     "llm/fallback_retrieval_index.json",
		"findings":           "diagnosis/findings.json",
		"anomaly_timeline":   "diagnosis/anomaly_timeline.json",
		"assessment":         "assessment/assessment.json",
	}
	if exportTier != "analyzed" {
		files["metric_catalog"] = "metric_catalog.json"
		files["time_series"] = "normalized/time_series.jsonl.gz"
		files["replication_lags"] = "normalized/replication_lags.json"
		files["disk_stats"] = "normalized/disk_stats.json"
	}
	if includeRaw {
		files["raw_metric_values"] = "raw/raw_metric_values.jsonl.gz"
	}
	return files
}

func buildTopAnomalyWindows(anomalies []ftdc.AnomalyEvent, limit int) []anomalyWindowSummary {
	type ranked struct {
		anomaly ftdc.AnomalyEvent
		score   float64
	}
	rankedList := make([]ranked, 0, len(anomalies))
	for _, anomaly := range anomalies {
		score := anomaly.Duration.Seconds()
		switch anomaly.Severity {
		case "critical":
			score += 1_000_000
		case "warning":
			score += 100_000
		}
		rankedList = append(rankedList, ranked{anomaly: anomaly, score: score})
	}
	sort.Slice(rankedList, func(i, j int) bool {
		return rankedList[i].score > rankedList[j].score
	})
	if limit > len(rankedList) {
		limit = len(rankedList)
	}
	out := make([]anomalyWindowSummary, 0, limit)
	for _, item := range rankedList[:limit] {
		anomaly := item.anomaly
		out = append(out, anomalyWindowSummary{
			Metric:    anomaly.Metric,
			Severity:  anomaly.Severity,
			Peak:      anomaly.Peak,
			Threshold: anomaly.Threshold,
			From:      anomaly.Timestamp,
			To:        anomaly.EndTime,
			DurationS: anomaly.Duration.Seconds(),
		})
	}
	return out
}

func buildAssessmentHighlights(diagnosis ftdc.ExportedDiagnosis) []assessmentHighlight {
	highlights := make([]assessmentHighlight, 0)
	for name, metric := range diagnosis.Metrics {
		if metric.Score >= 101 {
			continue
		}
		highlights = append(highlights, assessmentHighlight{
			Metric: name,
			Label:  metric.Label,
			Score:  metric.Score,
			P95:    metric.P95,
		})
	}
	sort.Slice(highlights, func(i, j int) bool {
		if highlights[i].Score == highlights[j].Score {
			return highlights[i].Metric < highlights[j].Metric
		}
		return highlights[i].Score < highlights[j].Score
	})
	if len(highlights) > 25 {
		highlights = highlights[:25]
	}
	return highlights
}

func buildFallbackRetrievalIndex(catalog []metricCatalogEntry, diagnosis ftdc.ExportedDiagnosis, tr timeRangeInfo, exportTier string) []fallbackRetrievalEntry {
	if exportTier == "analyzed" {
		return []fallbackRetrievalEntry{}
	}
	sourceForCatalog := map[string]string{
		"time_series":        "normalized/time_series.jsonl.gz",
		"disk_stats":         "normalized/disk_stats.json",
		"replication_lags":   "normalized/replication_lags.json",
	}
	entries := make([]fallbackRetrievalEntry, 0, len(catalog)+len(diagnosis.Anomalies))
	for _, item := range catalog {
		sourceFile, ok := sourceForCatalog[item.Source]
		if !ok {
			continue
		}
		window := timeRangeInfo{}
		if item.FirstTimestamp > 0 && item.LastTimestamp > 0 {
			window.From = time.UnixMilli(int64(item.FirstTimestamp))
			window.To = time.UnixMilli(int64(item.LastTimestamp))
			window.DurationSeconds = window.To.Sub(window.From).Seconds()
		}
		entries = append(entries, fallbackRetrievalEntry{
			Metric:     item.Name,
			Source:     item.Source,
			SourceFile: sourceFile,
			Tier:       "tier_2_normalized",
			Window:     window,
			Points:     item.Points,
		})
	}
	for _, anomaly := range buildTopAnomalyWindows(diagnosis.Anomalies, 25) {
		metricName := anomaly.Metric
		source := "time_series"
		sourceFile := "normalized/time_series.jsonl.gz"
		if strings.Contains(strings.ToLower(metricName), "repl") {
			source = "replication_lags"
			sourceFile = "normalized/replication_lags.json"
		}
		entries = append(entries, fallbackRetrievalEntry{
			Metric:         metricName,
			Source:         source,
			SourceFile:     sourceFile,
			Tier:           "tier_2_normalized",
			RelatedFinding: relatedFindingForMetric(metricName, diagnosis.Findings),
			Window: timeRangeInfo{
				From:            anomaly.From,
				To:              anomaly.To,
				DurationSeconds: anomaly.DurationS,
			},
		})
	}
	sort.Slice(entries, func(i, j int) bool {
		if entries[i].Metric == entries[j].Metric {
			return entries[i].Source < entries[j].Source
		}
		return entries[i].Metric < entries[j].Metric
	})
	return entries
}

func relatedFindingForMetric(metric string, findings []ftdc.ExportedDiagnosisResult) string {
	metricLower := strings.ToLower(metric)
	for _, finding := range findings {
		nameLower := strings.ToLower(finding.Name)
		switch {
		case strings.Contains(metricLower, "repl") && strings.Contains(nameLower, "replication"):
			return finding.Name
		case strings.Contains(metricLower, "cpu") && strings.Contains(nameLower, "cpu"):
			return finding.Name
		case strings.Contains(metricLower, "write") && strings.Contains(nameLower, "write"):
			return finding.Name
		case (strings.Contains(metricLower, "scan") || strings.Contains(metricLower, "query")) && strings.Contains(nameLower, "index"):
			return finding.Name
		}
	}
	return ""
}

func buildBundleIndex(output string, exportTier string, includeRaw bool) ([]bundleIndexEntry, error) {
	tierForPath := map[string]string{
		"llm/executive_context.json":        "tier_1_analyzed",
		"llm/fallback_retrieval_index.json": "tier_1_analyzed",
		"diagnosis/findings.json":           "tier_1_analyzed",
		"diagnosis/anomaly_timeline.json":   "tier_1_analyzed",
		"diagnosis/activity_summary.json":   "tier_1_analyzed",
		"diagnosis/diagnosis.json":          "tier_1_analyzed",
		"assessment/assessment.json":        "tier_1_analyzed",
		"assessment/formulas.json":          "tier_1_analyzed",
		"metric_catalog.json":               "tier_2_normalized",
		"normalized/time_series.jsonl.gz":   "tier_2_normalized",
		"normalized/disk_stats.json":        "tier_2_normalized",
		"normalized/replication_lags.json":  "tier_2_normalized",
		"normalized/server_info.json":       "tier_2_normalized",
		"normalized/server_status.jsonl.gz": "tier_2_normalized",
		"normalized/system_metrics.jsonl.gz": "tier_2_normalized",
		"normalized/replset_status.jsonl.gz": "tier_2_normalized",
		"raw/raw_metric_values.jsonl.gz":    "tier_3_raw",
		"raw/raw_blocks.jsonl.gz":           "tier_3_raw",
		"raw/raw_server_info.jsonl.gz":      "tier_3_raw",
		"manifest.json":                     "metadata",
		"bundle_index.json":                 "metadata",
		"validation.json":                   "metadata",
		"manifest.pre.json":                 "metadata",
	}

	var paths []string
	for rel, tier := range tierForPath {
		if exportTier == "analyzed" && strings.HasPrefix(tier, "tier_2") {
			continue
		}
		if !includeRaw && tier == "tier_3_raw" {
			continue
		}
		if rel == "bundle_index.json" {
			continue
		}
		paths = append(paths, rel)
	}
	sort.Strings(paths)

	entries := make([]bundleIndexEntry, 0, len(paths))
	for _, rel := range paths {
		fullPath := filepath.Join(output, rel)
		info, err := os.Stat(fullPath)
		if err != nil {
			if os.IsNotExist(err) {
				continue
			}
			return nil, err
		}
		hash, err := sha256File(fullPath)
		if err != nil {
			return nil, err
		}
		entries = append(entries, bundleIndexEntry{
			Path:   rel,
			Tier:   tierForPath[rel],
			Size:   info.Size(),
			SHA256: hash,
		})
	}
	return entries, nil
}

func validateBundle(output string, exportTier string, includeRaw bool, manifest manifest, bundleIndex []bundleIndexEntry) validationResult {
	result := validationResult{
		ContractVersion: contractVersion,
		ValidatedAt:     time.Now().UTC(),
		Valid:           true,
		ExportTier:      exportTier,
		Errors:          []string{},
		Warnings:        []string{},
	}

	requiredTier1 := []string{
		"llm/executive_context.json",
		"diagnosis/findings.json",
		"diagnosis/anomaly_timeline.json",
		"diagnosis/activity_summary.json",
		"assessment/assessment.json",
		"assessment/formulas.json",
	}
	for _, rel := range requiredTier1 {
		if _, err := os.Stat(filepath.Join(output, rel)); err != nil {
			result.Valid = false
			result.Errors = append(result.Errors, fmt.Sprintf("missing tier_1 file: %s", rel))
		}
	}
	result.Tier1Complete = len(result.Errors) == 0

	if exportTier != "analyzed" {
		for _, rel := range []string{"metric_catalog.json", "normalized/time_series.jsonl.gz"} {
			if _, err := os.Stat(filepath.Join(output, rel)); err != nil {
				result.Valid = false
				result.Errors = append(result.Errors, fmt.Sprintf("missing tier_2 file: %s", rel))
			}
		}
	}
	result.Tier2Present = exportTier != "analyzed"

	if includeRaw {
		if _, err := os.Stat(filepath.Join(output, "raw/raw_metric_values.jsonl.gz")); err != nil {
			result.Valid = false
			result.Errors = append(result.Errors, "missing tier_3 file: raw/raw_metric_values.jsonl.gz")
		}
	}
	result.Tier3Present = includeRaw

	if manifest.DiagnosisFindings == 0 {
		result.Warnings = append(result.Warnings, "no diagnosis findings produced")
	}
	if manifest.TimeRange.From.IsZero() || manifest.TimeRange.To.IsZero() {
		result.Valid = false
		result.Errors = append(result.Errors, "manifest time range is empty")
	}
	if len(bundleIndex) == 0 {
		result.Valid = false
		result.Errors = append(result.Errors, "bundle_index is empty")
	}
	if _, err := os.Stat(filepath.Join(output, "manifest.json")); err != nil {
		result.Valid = false
		result.Errors = append(result.Errors, "missing authoritative manifest.json")
	}

	return result
}

func sha256File(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	hasher := sha256.New()
	if _, err := io.Copy(hasher, file); err != nil {
		return "", err
	}
	return hex.EncodeToString(hasher.Sum(nil)), nil
}

func makeDirs(output string) error {
	for _, dir := range []string{
		output,
		filepath.Join(output, "raw"),
		filepath.Join(output, "normalized"),
		filepath.Join(output, "assessment"),
		filepath.Join(output, "diagnosis"),
		filepath.Join(output, "llm"),
	} {
		if err := os.MkdirAll(dir, 0755); err != nil {
			return err
		}
	}
	return nil
}

func exportNormalized(output string, stats ftdc.FTDCStats) error {
	if err := writeJSONL(filepath.Join(output, "normalized", "time_series.jsonl.gz"), sortedTimeSeries(stats.TimeSeriesData)); err != nil {
		return err
	}
	if err := writeJSON(filepath.Join(output, "normalized", "disk_stats.json"), stats.DiskStats); err != nil {
		return err
	}
	if err := writeJSON(filepath.Join(output, "normalized", "replication_lags.json"), stats.ReplicationLags); err != nil {
		return err
	}
	if err := writeJSON(filepath.Join(output, "normalized", "server_info.json"), stats.ServerInfo); err != nil {
		return err
	}
	if err := writeJSONL(filepath.Join(output, "normalized", "server_status.jsonl.gz"), stats.ServerStatusList); err != nil {
		return err
	}
	if err := writeJSONL(filepath.Join(output, "normalized", "system_metrics.jsonl.gz"), stats.SystemMetricsList); err != nil {
		return err
	}
	return writeJSONL(filepath.Join(output, "normalized", "replset_status.jsonl.gz"), stats.ReplSetStatusList)
}

func exportRaw(output string, files []string) ([]fileSummary, int, int, error) {
	blockWriter, closeBlocks, err := newJSONLWriter(filepath.Join(output, "raw", "raw_blocks.jsonl.gz"))
	if err != nil {
		return nil, 0, 0, err
	}
	defer closeBlocks()

	metricWriter, closeMetrics, err := newJSONLWriter(filepath.Join(output, "raw", "raw_metric_values.jsonl.gz"))
	if err != nil {
		return nil, 0, 0, err
	}
	defer closeMetrics()

	infoWriter, closeInfo, err := newJSONLWriter(filepath.Join(output, "raw", "raw_server_info.jsonl.gz"))
	if err != nil {
		return nil, 0, 0, err
	}
	defer closeInfo()

	summaries := make([]fileSummary, 0, len(files))
	totalSeries := 0
	totalValues := 0

	for _, filename := range files {
		metrics, err := readRawMetrics(filename)
		if err != nil {
			return summaries, totalSeries, totalValues, err
		}
		if err := infoWriter.Encode(rawServerInfoLine{SourceFile: filename, ServerInfo: metrics.Doc}); err != nil {
			return summaries, totalSeries, totalValues, err
		}

		summary := fileSummary{Path: filename, Blocks: len(metrics.Data)}
		for blockIndex, block := range metrics.Data {
			if err := blockWriter.Encode(rawBlockLine{
				SourceFile:  filename,
				BlockIndex:  blockIndex,
				NumDeltas:   block.NumDeltas,
				MetricCount: len(block.DataPointsMap),
			}); err != nil {
				return summaries, totalSeries, totalValues, err
			}

			keys := make([]string, 0, len(block.DataPointsMap))
			for k := range block.DataPointsMap {
				keys = append(keys, k)
			}
			sort.Strings(keys)

			summary.RawMetricSeries += len(keys)
			totalSeries += len(keys)
			for _, key := range keys {
				values := block.DataPointsMap[key]
				totalValues += len(values)
				summary.ExpandedRawValues += len(values)
				if err := metricWriter.Encode(rawMetricLine{
					SourceFile: filename,
					BlockIndex: blockIndex,
					Path:       key,
					Values:     values,
				}); err != nil {
					return summaries, totalSeries, totalValues, err
				}
			}
		}
		summaries = append(summaries, summary)
		fmt.Printf("raw export complete: %s blocks=%d metric_series=%d raw_values=%d\n",
			filepath.Base(filename), summary.Blocks, summary.RawMetricSeries, summary.ExpandedRawValues)
	}
	return summaries, totalSeries, totalValues, nil
}

func readRawMetrics(filename string) (*decoder.Metrics, error) {
	reader, err := gox.NewFileReader(filename)
	if err != nil {
		return nil, err
	}
	buffer, err := io.ReadAll(reader)
	if err != nil {
		return nil, err
	}
	metrics := decoder.NewMetrics()
	if err := metrics.ReadAllMetrics(&buffer); err != nil {
		return nil, err
	}
	return metrics, nil
}

func buildMetricCatalog(stats ftdc.FTDCStats) []metricCatalogEntry {
	entries := make([]metricCatalogEntry, 0, len(stats.TimeSeriesData)+len(stats.DiskStats)*6+len(stats.ReplicationLags))
	for _, ts := range sortedTimeSeries(stats.TimeSeriesData) {
		entries = append(entries, catalogEntry(ts.Target, "time_series", ts.DataPoints))
	}
	for disk, ds := range stats.DiskStats {
		entries = append(entries, catalogEntry("disk."+disk+".iops", "disk_stats", ds.IOPS.DataPoints))
		entries = append(entries, catalogEntry("disk."+disk+".io_in_progress", "disk_stats", ds.IOInProgress.DataPoints))
		entries = append(entries, catalogEntry("disk."+disk+".io_queued_ms", "disk_stats", ds.IOQueuedMS.DataPoints))
		entries = append(entries, catalogEntry("disk."+disk+".read_time_ms", "disk_stats", ds.ReadTimeMS.DataPoints))
		entries = append(entries, catalogEntry("disk."+disk+".write_time_ms", "disk_stats", ds.WriteTimeMS.DataPoints))
		entries = append(entries, catalogEntry("disk."+disk+".utilization", "disk_stats", ds.Utilization.DataPoints))
	}
	for host, ts := range stats.ReplicationLags {
		entries = append(entries, catalogEntry("replication_lag."+host, "replication_lags", ts.DataPoints))
	}
	sort.Slice(entries, func(i, j int) bool {
		if entries[i].Source == entries[j].Source {
			return entries[i].Name < entries[j].Name
		}
		return entries[i].Source < entries[j].Source
	})
	return entries
}

func catalogEntry(name string, source string, points [][]float64) metricCatalogEntry {
	entry := metricCatalogEntry{Name: name, Source: source, Points: len(points)}
	if len(points) > 0 {
		entry.FirstTimestamp = points[0][1]
		entry.LastTimestamp = points[len(points)-1][1]
	}
	return entry
}

func sortedTimeSeries(in map[string]ftdc.TimeSeriesDoc) []ftdc.TimeSeriesDoc {
	keys := make([]string, 0, len(in))
	for k := range in {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	out := make([]ftdc.TimeSeriesDoc, 0, len(keys))
	for _, k := range keys {
		ts := in[k]
		if strings.TrimSpace(ts.Target) == "" {
			ts.Target = k
		}
		out = append(out, ts)
	}
	return out
}

func writeJSON(path string, value interface{}) error {
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()
	encoder := json.NewEncoder(file)
	encoder.SetIndent("", "  ")
	return encoder.Encode(value)
}

func writeJSONAtomic(path string, value interface{}) error {
	tmpPath := path + ".tmp"
	if err := writeJSON(tmpPath, value); err != nil {
		return err
	}
	return os.Rename(tmpPath, path)
}

func writeJSONL(path string, value interface{}) error {
	encoder, closeFn, err := newJSONLWriter(path)
	if err != nil {
		return err
	}
	defer closeFn()

	bytes, err := json.Marshal(value)
	if err != nil {
		return err
	}
	var array []json.RawMessage
	if err := json.Unmarshal(bytes, &array); err != nil {
		return encoder.Encode(value)
	}
	for _, item := range array {
		if _, err := encoder.Writer.Write(item); err != nil {
			return err
		}
		if _, err := encoder.Writer.Write([]byte("\n")); err != nil {
			return err
		}
	}
	return nil
}

type jsonlEncoder struct {
	*json.Encoder
	Writer io.Writer
}

func newJSONLWriter(path string) (*jsonlEncoder, func() error, error) {
	file, err := os.Create(path)
	if err != nil {
		return nil, nil, err
	}
	gz, err := gzip.NewWriterLevel(file, gzip.BestSpeed)
	if err != nil {
		file.Close()
		return nil, nil, err
	}
	encoder := json.NewEncoder(gz)
	closeFn := func() error {
		if err := gz.Close(); err != nil {
			file.Close()
			return err
		}
		return file.Close()
	}
	return &jsonlEncoder{Encoder: encoder, Writer: gz}, closeFn, nil
}

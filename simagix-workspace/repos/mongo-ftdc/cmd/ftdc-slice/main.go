// ftdc-slice: safe windowed reader for MongoDB FTDC diagnostic data files.
//
// Reuses github.com/simagix/mongo-ftdc/decoder for delta expansion.
// Adds a safe outer BSON iterator (guarding truncated final chunks) and
// chunk-level time-window skipping (decompress reference doc only, skip
// full delta expansion for chunks outside the requested window).
//
// Modes:
//   --mode catalog  <file>
//       Decode the last valid chunk of <file>. Emit all path names,
//       plus the overall start_ts and end_ts. Used by ingest to build
//       raw_path_catalog and raw_path_prefix_map.
//
//   --mode index  <file> [file ...]
//       For each file, emit {filename, start_ts, end_ts, bytes}.
//       Used by ingest to build raw_file_index.
//
//   --mode window  --paths p1,p2,... --start S --end E  <file> [file ...]
//       Emit time series for the named paths, in the epoch-second window
//       [S, E]. Used by the get_raw_window MCP tool.
//
// All output is JSON on stdout. Errors are written to stderr.
// Truncated final chunks produce a coverage_gap entry (window mode)
// or are silently skipped in favor of the last valid chunk (catalog/index).
// Exit code 0 even on partial results; exit 1 only on hard I/O errors.
package main

import (
	"bytes"
	"compress/zlib"
	"encoding/binary"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"math"
	"os"
	"sort"
	"strings"

	"go.mongodb.org/mongo-driver/bson"
	"go.mongodb.org/mongo-driver/bson/primitive"

	"github.com/simagix/mongo-ftdc/decoder"
)

// ── output types ──────────────────────────────────────────────────────────────

type catalogOutput struct {
	PathCount int      `json:"path_count"`
	Paths     []string `json:"paths"`
	StartTS   float64  `json:"start_ts"`
	EndTS     float64  `json:"end_ts"`
}

type indexEntry struct {
	Filename string  `json:"filename"`
	StartTS  float64 `json:"start_ts"`
	EndTS    float64 `json:"end_ts"`
	Bytes    int64   `json:"bytes"`
}

type coverageGap struct {
	Reason string  `json:"reason"`
	After  float64 `json:"after"`
}

type windowOutput struct {
	Series         map[string][][2]float64 `json:"series"`
	CoverageGaps   []coverageGap           `json:"coverage_gaps"`
	FilesProcessed int                     `json:"files_processed"`
}

// ── entry point ───────────────────────────────────────────────────────────────

func main() {
	mode := flag.String("mode", "window", "catalog | index | window")
	pathsFlag := flag.String("paths", "", "comma-separated literal path names (window mode)")
	startFlag := flag.Float64("start", 0, "window start, epoch seconds inclusive (window mode)")
	endFlag := flag.Float64("end", math.MaxFloat64, "window end, epoch seconds inclusive (window mode)")
	flag.Parse()
	files := flag.Args()

	if len(files) == 0 {
		fmt.Fprintln(os.Stderr, "ftdc-slice: no files specified")
		os.Exit(1)
	}

	var err error
	switch *mode {
	case "catalog":
		err = runCatalog(files[len(files)-1])
	case "index":
		err = runIndex(files)
	case "window":
		var paths []string
		if *pathsFlag != "" {
			for _, p := range strings.Split(*pathsFlag, ",") {
				if t := strings.TrimSpace(p); t != "" {
					paths = append(paths, t)
				}
			}
		}
		err = runWindow(files, paths, *startFlag, *endFlag)
	default:
		fmt.Fprintf(os.Stderr, "ftdc-slice: unknown mode %q\n", *mode)
		os.Exit(1)
	}

	if err != nil {
		fmt.Fprintf(os.Stderr, "ftdc-slice: %v\n", err)
		os.Exit(1)
	}
}

// ── mode: catalog ─────────────────────────────────────────────────────────────

func runCatalog(filename string) error {
	buf, err := os.ReadFile(filename)
	if err != nil {
		return err
	}

	var lastDecomp []byte
	var firstTS float64 = math.NaN()
	var lastEndTS float64 = math.NaN()

	iterChunks(buf, func(decompressed []byte, startTS, endTS float64) {
		if math.IsNaN(firstTS) && !math.IsNaN(startTS) {
			firstTS = startTS
		}
		if !math.IsNaN(endTS) {
			lastEndTS = endTS
		}
		lastDecomp = decompressed
	})

	if lastDecomp == nil {
		return fmt.Errorf("no valid metric chunks in %s", filename)
	}

	// Full decode on the last chunk gives us all path names via DataPointsMap.
	// Cost: one chunk decode (~50–200 ms). Acceptable for a one-time ingest call.
	md, decErr := decoder.Decode(lastDecomp)
	if decErr != nil && len(md.DataPointsMap) == 0 {
		return fmt.Errorf("decode failed: %w", decErr)
	}

	// Derive end timestamp from the "start" series if reference doc had no "end" field.
	// "start" values are stored as milliseconds (DateTime); divide by 1000 for seconds.
	if math.IsNaN(lastEndTS) {
		if ts, ok := md.DataPointsMap["start"]; ok && len(ts) > 0 {
			lastEndTS = float64(ts[len(ts)-1]) / 1000.0
		}
	}

	paths := make([]string, 0, len(md.DataPointsMap))
	for k := range md.DataPointsMap {
		paths = append(paths, k)
	}
	sort.Strings(paths)

	return emitJSON(catalogOutput{
		PathCount: len(paths),
		Paths:     paths,
		StartTS:   nanToZero(firstTS),
		EndTS:     nanToZero(lastEndTS),
	})
}

// ── mode: index ───────────────────────────────────────────────────────────────

func runIndex(files []string) error {
	entries := make([]indexEntry, 0, len(files))
	for _, f := range files {
		e, err := indexOneFile(f)
		if err != nil {
			fmt.Fprintf(os.Stderr, "ftdc-slice: skipping %s: %v\n", f, err)
			continue
		}
		entries = append(entries, e)
	}
	return emitJSON(entries)
}

func indexOneFile(filename string) (indexEntry, error) {
	info, err := os.Stat(filename)
	if err != nil {
		return indexEntry{}, err
	}
	buf, err := os.ReadFile(filename)
	if err != nil {
		return indexEntry{}, err
	}

	var firstTS float64 = math.NaN()
	var lastEndTS float64 = math.NaN()

	iterChunks(buf, func(_ []byte, startTS, endTS float64) {
		if math.IsNaN(firstTS) && !math.IsNaN(startTS) {
			firstTS = startTS
		}
		if !math.IsNaN(endTS) {
			lastEndTS = endTS
		}
	})

	if math.IsNaN(firstTS) {
		return indexEntry{}, fmt.Errorf("no valid metric chunks found")
	}
	if math.IsNaN(lastEndTS) {
		lastEndTS = firstTS
	}

	return indexEntry{
		Filename: filename,
		StartTS:  firstTS,
		EndTS:    lastEndTS,
		Bytes:    info.Size(),
	}, nil
}

// ── mode: window ──────────────────────────────────────────────────────────────

func runWindow(files []string, paths []string, winStart, winEnd float64) error {
	pathSet := make(map[string]bool, len(paths))
	for _, p := range paths {
		pathSet[p] = true
	}
	allPaths := len(pathSet) == 0 // no filter → emit everything

	seriesMap := make(map[string][][2]float64)
	var gaps []coverageGap
	filesProcessed := 0

	for _, f := range files {
		buf, err := os.ReadFile(f)
		if err != nil {
			fmt.Fprintf(os.Stderr, "ftdc-slice: skipping %s: %v\n", f, err)
			continue
		}

		gap := iterChunksWithGap(buf, func(decompressed []byte, chunkStart, chunkEnd float64) {
			// Resolve unknown chunk bounds conservatively so we never skip a
			// chunk that might overlap the window.
			cs := chunkStart
			if math.IsNaN(cs) {
				cs = 0
			}
			ce := chunkEnd
			if math.IsNaN(ce) {
				ce = math.MaxFloat64
			}

			// Skip chunk if it cannot overlap the window.
			if cs > winEnd || ce < winStart {
				return
			}

			// Full delta expansion — unavoidable given the interleaved varint stream.
			md, decErr := decoder.Decode(decompressed)
			if decErr != nil && len(md.DataPointsMap) == 0 {
				return
			}

			// "start" holds per-sample timestamps as milliseconds (BSON DateTime).
			// Divide by 1000 to compare against epoch-second window bounds.
			timestamps, hasTimes := md.DataPointsMap["start"]
			if !hasTimes || len(timestamps) == 0 {
				return
			}

			for path, values := range md.DataPointsMap {
				if !allPaths && !pathSet[path] {
					continue
				}
				for i, rawTS := range timestamps {
					tsSeconds := float64(rawTS) / 1000.0
					if tsSeconds < winStart || tsSeconds > winEnd {
						continue
					}
					if i >= len(values) {
						break
					}
					seriesMap[path] = append(seriesMap[path], [2]float64{tsSeconds, float64(values[i])})
				}
			}
		})

		if gap != nil {
			gaps = append(gaps, *gap)
		}
		filesProcessed++
	}

	if gaps == nil {
		gaps = []coverageGap{}
	}

	return emitJSON(windowOutput{
		Series:         seriesMap,
		CoverageGaps:   gaps,
		FilesProcessed: filesProcessed,
	})
}

// ── FTDC file iteration ───────────────────────────────────────────────────────

// iterChunks calls fn for each valid decompressed type-1 chunk in buf.
// Truncated final documents are silently skipped (treated as end-of-file).
func iterChunks(buf []byte, fn func(decompressed []byte, startTS, endTS float64)) {
	iterChunksWithGap(buf, fn)
}

// iterChunksWithGap is like iterChunks but also returns the coverage gap
// produced by a truncated final document, with the last known end timestamp.
func iterChunksWithGap(buf []byte, fn func(decompressed []byte, startTS, endTS float64)) *coverageGap {
	pos := uint32(0)
	bufLen := uint32(len(buf))
	var lastEndTS float64 = math.NaN()

	for pos < bufLen {
		// Guard: need at least 4 bytes for the BSON length prefix.
		if pos+4 > bufLen {
			return &coverageGap{Reason: "truncated_tail", After: nanToZero(lastEndTS)}
		}

		length := binary.LittleEndian.Uint32(buf[pos:])

		// Minimum valid BSON document is 5 bytes ({} = size + terminator).
		if length < 5 {
			return &coverageGap{Reason: "truncated_tail", After: nanToZero(lastEndTS)}
		}

		// Guard: full document must fit in the remaining buffer.
		if pos+length > bufLen {
			return &coverageGap{Reason: "truncated_tail", After: nanToZero(lastEndTS)}
		}

		docBytes := buf[pos : pos+length]
		pos += length

		// Parse the outer BSON envelope: {type: int32, doc: ..., data: Binary}.
		var outer struct {
			Type int32              `bson:"type"`
			Data primitive.Binary   `bson:"data"`
		}
		if err := bson.Unmarshal(docBytes, &outer); err != nil {
			continue // malformed outer doc, skip
		}
		if outer.Type != 1 {
			continue // type 0 metadata doc
		}

		// Strip the 4-byte uncompressed-size prefix that precedes the zlib stream.
		rawData := outer.Data.Data
		if len(rawData) < 4 {
			continue
		}
		compressed := rawData[4:]

		decompressed, err := zlibDecompress(compressed)
		if err != nil {
			continue
		}

		startTS, endTS := peekTimestamps(decompressed)
		if !math.IsNaN(endTS) {
			lastEndTS = endTS
		}

		fn(decompressed, startTS, endTS)
	}

	return nil // clean end-of-file
}

// peekTimestamps extracts the start and end epoch-second timestamps from the
// reference BSON document at the head of a decompressed chunk buffer.
// If the "end" field is absent, it falls back to start + NumDeltas (seconds).
// Returns NaN if the buffer is malformed or the timestamp cannot be read.
func peekTimestamps(decompressed []byte) (startTS, endTS float64) {
	startTS = math.NaN()
	endTS = math.NaN()

	if len(decompressed) < 4 {
		return
	}
	docSize := binary.LittleEndian.Uint32(decompressed[0:4])
	if uint32(len(decompressed)) < docSize {
		return
	}

	var refDoc bson.M
	if err := bson.Unmarshal(decompressed[0:docSize], &refDoc); err != nil {
		return
	}

	// start/end in FTDC reference docs are BSON DateTime (milliseconds since epoch),
	// not Timestamp. The traverseDocElem DateTime case stores them as flat uint64 ms
	// values — they appear as "start" and "end" (not "start/t"+"start/i").
	if dt, ok := refDoc["start"].(primitive.DateTime); ok {
		startTS = float64(dt) / 1000.0
	}
	if dt, ok := refDoc["end"].(primitive.DateTime); ok {
		endTS = float64(dt) / 1000.0
	}

	// Fallback: end = start + NumDeltas seconds (1 Hz sampling).
	// NumDeltas is the second uint32 after the reference doc in the decompressed buffer.
	if math.IsNaN(endTS) && !math.IsNaN(startTS) && uint32(len(decompressed)) >= docSize+8 {
		numDeltas := binary.LittleEndian.Uint32(decompressed[docSize+4:])
		endTS = startTS + float64(numDeltas)
	}

	return
}

// ── helpers ───────────────────────────────────────────────────────────────────

func zlibDecompress(data []byte) ([]byte, error) {
	r, err := zlib.NewReader(bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	defer r.Close()
	return io.ReadAll(r)
}

func emitJSON(v any) error {
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	return enc.Encode(v)
}

// nanToZero converts NaN to 0.0 so JSON serialisation never produces "NaN"
// (which is not valid JSON).
func nanToZero(f float64) float64 {
	if math.IsNaN(f) {
		return 0
	}
	return f
}

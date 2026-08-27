package main

import (
	"bufio"
	"flag"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"
	"time"

	"gocat/pipeline"
	"gocat/protocol"
)

func writeTimings(w io.Writer, mode string, setup, inspect, protocolWrite, total time.Duration, processed *pipeline.ProcessedImage) {
	fmt.Fprintf(w, "gocat timings: mode=%s", mode)
	if processed != nil {
		fmt.Fprintf(w, " input=%dx%d output=%dx%d", processed.SourceWidth, processed.SourceHeight, processed.OutputWidth, processed.OutputHeight)
	}
	fmt.Fprintf(w, " setup=%s", setup)
	if inspect > 0 {
		fmt.Fprintf(w, " inspect=%s", inspect)
	}
	if processed != nil {
		fmt.Fprintf(w, " decode=%s dimensions=%s", processed.Timings.Decode, processed.Timings.Dimensions)
		if processed.Timings.Resized {
			fmt.Fprintf(w, " resize=%s", processed.Timings.Resize)
		}
		fmt.Fprintf(w, " encode=%s", processed.Timings.Encode)
	}
	fmt.Fprintf(w, " protocol=%s total=%s\n", protocolWrite, total)
}

func parseGeometry(geom string) (int, int, error) {
	if geom == "" {
		return 0, 0, nil
	}
	parts := strings.Split(strings.ToLower(geom), "x")
	if len(parts) != 2 {
		return 0, 0, fmt.Errorf("invalid geometry %q, expected WxH (e.g. 800x600)", geom)
	}
	w, err := strconv.Atoi(strings.TrimSpace(parts[0]))
	if err != nil || w < 0 {
		return 0, 0, fmt.Errorf("invalid width in geometry: %q", parts[0])
	}
	h, err := strconv.Atoi(strings.TrimSpace(parts[1]))
	if err != nil || h < 0 {
		return 0, 0, fmt.Errorf("invalid height in geometry: %q", parts[1])
	}
	return w, h, nil
}

func run(args []string, stdin io.Reader, stdout io.Writer, stderr io.Writer) int {
	totalStart := time.Now()
	flags := flag.NewFlagSet("gocat", flag.ContinueOnError)
	flags.SetOutput(stderr)

	targetFlag := flags.String("target", "", "Target bounding box in pixels, e.g. 800x600 or 720x420")
	flags.StringVar(targetFlag, "t", "", "Alias for --target")

	modeFlag := flags.String("mode", "auto", "Operation mode: auto, passthrough (t=f), fallback (t=d scalar)")
	flags.StringVar(modeFlag, "m", "auto", "Alias for --mode")

	colsFlag := flags.Int("cols", 0, "Target columns (Kitty c=N)")
	rowsFlag := flags.Int("rows", 0, "Target rows (Kitty r=N)")
	quietFlag := flags.Int("quiet", 2, "Kitty protocol quiet mode (0, 1, 2; default 2)")
	flags.IntVar(quietFlag, "q", 2, "Alias for --quiet")
	timingsFlag := flags.Bool("timings", false, "Report processing stage timings to stderr")

	flags.Usage = func() {
		fmt.Fprintf(stderr, "Usage: gocat [options] <image-file | ->\n\nOptions:\n")
		flags.PrintDefaults()
	}

	if err := flags.Parse(args); err != nil {
		return 1
	}

	remaining := flags.Args()
	var inputPath string
	if len(remaining) > 0 {
		inputPath = remaining[0]
	}

	maxW, maxH, err := parseGeometry(*targetFlag)
	if err != nil {
		fmt.Fprintf(stderr, "Error: %v\n", err)
		return 1
	}

	opts := protocol.DefaultOptions()
	opts.Quiet = *quietFlag
	opts.Columns = *colsFlag
	opts.Rows = *rowsFlag

	mode := strings.ToLower(*modeFlag)
	if mode != "auto" && mode != "passthrough" && mode != "fallback" {
		fmt.Fprintf(stderr, "Error: unknown mode %q (must be auto, passthrough, or fallback)\n", *modeFlag)
		return 1
	}

	bufferedOut := bufio.NewWriterSize(stdout, 64*1024)
	setupDuration := time.Since(totalStart)

	// Handle stdin
	if inputPath == "" || inputPath == "-" {
		if mode == "passthrough" {
			fmt.Fprintf(stderr, "Error: passthrough mode requires a local file path, stdin cannot be used\n")
			return 1
		}
		bbox := pipeline.BoundingBox{MaxWidth: maxW, MaxHeight: maxH}
		processed, err := pipeline.ProcessImage(stdin, bbox)
		if err != nil {
			fmt.Fprintf(stderr, "Error processing stdin image: %v\n", err)
			return 1
		}
		protocolStart := time.Now()
		if err := protocol.WriteDirectStream(bufferedOut, processed.PNGData, opts); err != nil {
			fmt.Fprintf(stderr, "Error writing protocol output: %v\n", err)
			return 1
		}
		if err := bufferedOut.Flush(); err != nil {
			fmt.Fprintf(stderr, "Error flushing protocol output: %v\n", err)
			return 1
		}
		protocolDuration := time.Since(protocolStart)
		if *timingsFlag {
			writeTimings(stderr, "fallback", setupDuration, 0, protocolDuration, time.Since(totalStart), &processed)
		}
		return 0
	}

	// Local file path provided
	inspectStart := time.Now()
	isPNG, absPath, _ := pipeline.FastPathCheck(inputPath)
	inspectDuration := time.Since(inspectStart)

	// Decision logic for mode
	usePassthrough := false
	if mode == "passthrough" {
		if !isPNG {
			fmt.Fprintf(stderr, "Error: passthrough mode requested, but %s is not a valid local PNG\n", inputPath)
			return 1
		}
		usePassthrough = true
	} else if mode == "auto" {
		// In auto mode, if it is a local PNG and no resizing is requested, or if target is unset, use fast path.
		// Even when target pixel dimensions are not scaled sender-side, Ghostty scales directly on GPU.
		// Passthrough is default for local PNGs.
		if isPNG && maxW == 0 && maxH == 0 {
			usePassthrough = true
		} else if isPNG && mode == "auto" {
			// If target geometry is specified, we can either let Kitty place it via c/r or downscale sender-side.
			// By default in auto, local PNG uses fast path.
			usePassthrough = true
		}
	}

	if usePassthrough {
		protocolStart := time.Now()
		if err := protocol.WriteFilePassthrough(bufferedOut, absPath, opts); err != nil {
			fmt.Fprintf(stderr, "Error writing passthrough protocol: %v\n", err)
			return 1
		}
		if err := bufferedOut.Flush(); err != nil {
			fmt.Fprintf(stderr, "Error flushing protocol output: %v\n", err)
			return 1
		}
		protocolDuration := time.Since(protocolStart)
		if *timingsFlag {
			writeTimings(stderr, "passthrough", setupDuration, inspectDuration, protocolDuration, time.Since(totalStart), nil)
		}
		return 0
	}

	// Fallback pipeline: open file, decode, downscale, encode, direct stream
	f, err := os.Open(inputPath)
	if err != nil {
		fmt.Fprintf(stderr, "Error opening file %s: %v\n", inputPath, err)
		return 1
	}
	defer f.Close()

	bbox := pipeline.BoundingBox{MaxWidth: maxW, MaxHeight: maxH}
	processed, err := pipeline.ProcessImage(f, bbox)
	if err != nil {
		fmt.Fprintf(stderr, "Error processing image %s: %v\n", inputPath, err)
		return 1
	}

	protocolStart := time.Now()
	if err := protocol.WriteDirectStream(bufferedOut, processed.PNGData, opts); err != nil {
		fmt.Fprintf(stderr, "Error writing direct stream: %v\n", err)
		return 1
	}
	if err := bufferedOut.Flush(); err != nil {
		fmt.Fprintf(stderr, "Error flushing protocol output: %v\n", err)
		return 1
	}
	protocolDuration := time.Since(protocolStart)
	if *timingsFlag {
		writeTimings(stderr, "fallback", setupDuration, inspectDuration, protocolDuration, time.Since(totalStart), &processed)
	}

	return 0
}

func main() {
	exitCode := run(os.Args[1:], os.Stdin, os.Stdout, os.Stderr)
	os.Exit(exitCode)
}

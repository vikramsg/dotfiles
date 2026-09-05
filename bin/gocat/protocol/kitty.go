package protocol

import (
	"encoding/base64"
	"fmt"
	"io"
	"strings"
)

const (
	// MaxChunkPayloadSize is the maximum size in bytes of base64 data per Kitty protocol chunk (4096 standard).
	MaxChunkPayloadSize = 4096

	// ActionTransmitAndDisplay is the Kitty action 'a=T'.
	ActionTransmitAndDisplay = "T"

	// FormatPNG is the Kitty format 'f=100' for PNG.
	FormatPNG = 100

	// MediumFile is Kitty transmission medium 't=f' (local file path).
	MediumFile = "f"

	// MediumDirect is Kitty transmission medium 't=d' (direct data).
	MediumDirect = "d"
)

// Options holds control parameters for Kitty graphics emission.
type Options struct {
	Action      string // default "T"
	Format      int    // default 100 (PNG)
	Quiet       int    // default 2 (suppress OK responses)
	Columns     int    // target columns (c=N)
	Rows        int    // target rows (r=N)
	Width       int    // target pixel width (s=N)
	Height      int    // target pixel height (v=N)
	ImageID     uint32 // optional image id (i=N)
	PlacementID uint32 // optional placement id (p=N)
}

// DefaultOptions returns default options (a=T, f=100, q=2).
func DefaultOptions() Options {
	return Options{
		Action: ActionTransmitAndDisplay,
		Format: FormatPNG,
		Quiet:  2,
	}
}

// formatControlHeader constructs the Kitty control key-value string.
func (o Options) formatControlHeader(medium string, moreChunks bool) string {
	parts := make([]string, 0, 8)

	action := o.Action
	if action == "" {
		action = ActionTransmitAndDisplay
	}
	parts = append(parts, fmt.Sprintf("a=%s", action))

	format := o.Format
	if format == 0 {
		format = FormatPNG
	}
	parts = append(parts, fmt.Sprintf("f=%d", format))

	if medium != "" {
		parts = append(parts, fmt.Sprintf("t=%s", medium))
	}

	if o.Quiet > 0 {
		parts = append(parts, fmt.Sprintf("q=%d", o.Quiet))
	}

	if o.ImageID > 0 {
		parts = append(parts, fmt.Sprintf("i=%d", o.ImageID))
	}

	if o.PlacementID > 0 {
		parts = append(parts, fmt.Sprintf("p=%d", o.PlacementID))
	}

	if o.Columns > 0 {
		parts = append(parts, fmt.Sprintf("c=%d", o.Columns))
	}
	if o.Rows > 0 {
		parts = append(parts, fmt.Sprintf("r=%d", o.Rows))
	}
	if o.Width > 0 {
		parts = append(parts, fmt.Sprintf("s=%d", o.Width))
	}
	if o.Height > 0 {
		parts = append(parts, fmt.Sprintf("v=%d", o.Height))
	}

	if moreChunks {
		parts = append(parts, "m=1")
	} else {
		parts = append(parts, "m=0")
	}

	return strings.Join(parts, ",")
}

// WriteFilePassthrough writes a Kitty graphics command pointing to an absolute local file path (t=f).
func WriteFilePassthrough(w io.Writer, absPath string, opts Options) error {
	encodedPath := base64.StdEncoding.EncodeToString([]byte(absPath))
	ctrl := opts.formatControlHeader(MediumFile, false)

	// Format: \x1b_G<ctrl>;<payload>\x1b\
	_, err := fmt.Fprintf(w, "\x1b_G%s;%s\x1b\\", ctrl, encodedPath)
	return err
}

// WriteDirectStream writes raw PNG (or other encoded) bytes as chunked base64 (t=d).
func WriteDirectStream(w io.Writer, data []byte, opts Options) error {
	encoded := base64.StdEncoding.EncodeToString(data)
	totalLen := len(encoded)

	if totalLen == 0 {
		ctrl := opts.formatControlHeader(MediumDirect, false)
		_, err := fmt.Fprintf(w, "\x1b_G%s;\x1b\\", ctrl)
		return err
	}

	offset := 0
	isFirst := true

	for offset < totalLen {
		end := offset + MaxChunkPayloadSize
		more := true
		if end >= totalLen {
			end = totalLen
			more = false
		}

		chunk := encoded[offset:end]

		if isFirst {
			ctrl := opts.formatControlHeader(MediumDirect, more)
			if _, err := fmt.Fprintf(w, "\x1b_G%s;%s\x1b\\", ctrl, chunk); err != nil {
				return err
			}
			isFirst = false
		} else {
			mVal := 1
			if !more {
				mVal = 0
			}
			if _, err := fmt.Fprintf(w, "\x1b_Gm=%d;%s\x1b\\", mVal, chunk); err != nil {
				return err
			}
		}

		offset = end
	}

	return nil
}

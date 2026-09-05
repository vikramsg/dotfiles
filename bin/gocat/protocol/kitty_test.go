package protocol

import (
	"bytes"
	"encoding/base64"
	"strings"
	"testing"
)

func TestWriteFilePassthrough(t *testing.T) {
	var buf bytes.Buffer
	testPath := "/home/user/image.png"
	opts := DefaultOptions()

	err := WriteFilePassthrough(&buf, testPath, opts)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	out := buf.String()
	expectedPrefix := "\x1b_Ga=T,f=100,t=f,q=2,m=0;"
	if !strings.HasPrefix(out, expectedPrefix) {
		t.Errorf("expected prefix %q, got %q", expectedPrefix, out)
	}
	if !strings.HasSuffix(out, "\x1b\\") {
		t.Errorf("expected suffix \\x1b\\\\, got %q", out)
	}

	payload := strings.TrimPrefix(out, expectedPrefix)
	payload = strings.TrimSuffix(payload, "\x1b\\")

	decoded, err := base64.StdEncoding.DecodeString(payload)
	if err != nil {
		t.Fatalf("failed to decode base64 payload: %v", err)
	}
	if string(decoded) != testPath {
		t.Errorf("expected payload %q, got %q", testPath, string(decoded))
	}
}

func TestWriteDirectStreamSingleChunk(t *testing.T) {
	var buf bytes.Buffer
	data := []byte("hello-png-image-data")
	opts := DefaultOptions()

	err := WriteDirectStream(&buf, data, opts)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	out := buf.String()
	expectedPrefix := "\x1b_Ga=T,f=100,t=d,q=2,m=0;"
	if !strings.HasPrefix(out, expectedPrefix) {
		t.Errorf("expected prefix %q, got %q", expectedPrefix, out)
	}
	if !strings.HasSuffix(out, "\x1b\\") {
		t.Errorf("expected suffix \\x1b\\\\, got %q", out)
	}

	payload := strings.TrimPrefix(out, expectedPrefix)
	payload = strings.TrimSuffix(payload, "\x1b\\")

	decoded, err := base64.StdEncoding.DecodeString(payload)
	if err != nil {
		t.Fatalf("failed to decode payload: %v", err)
	}
	if !bytes.Equal(decoded, data) {
		t.Errorf("expected %q, got %q", data, decoded)
	}
}

func TestWriteDirectStreamMultiChunk(t *testing.T) {
	var buf bytes.Buffer
	// Generate data that exceeds MaxChunkPayloadSize (4096 base64 chars = 3072 raw bytes)
	rawSize := 10000
	data := make([]byte, rawSize)
	for i := range data {
		data[i] = byte(i % 256)
	}

	opts := DefaultOptions()
	err := WriteDirectStream(&buf, data, opts)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	out := buf.String()
	commands := strings.Split(out, "\x1b\\")
	// The last element after split will be empty because of trailing \x1b\
	if len(commands) > 0 && commands[len(commands)-1] == "" {
		commands = commands[:len(commands)-1]
	}

	if len(commands) < 2 {
		t.Fatalf("expected multiple chunks, got %d commands", len(commands))
	}

	var totalBase64 strings.Builder
	for i, cmd := range commands {
		if !strings.HasPrefix(cmd, "\x1b_G") {
			t.Errorf("chunk %d missing \\x1b_G prefix: %q", i, cmd)
		}
		parts := strings.SplitN(strings.TrimPrefix(cmd, "\x1b_G"), ";", 2)
		if len(parts) != 2 {
			t.Fatalf("chunk %d malformed: %q", i, cmd)
		}
		header, chunkPayload := parts[0], parts[1]

		if i == 0 {
			if !strings.Contains(header, "a=T") || !strings.Contains(header, "t=d") || !strings.Contains(header, "m=1") {
				t.Errorf("chunk 0 header unexpected: %s", header)
			}
		} else if i == len(commands)-1 {
			if header != "m=0" {
				t.Errorf("final chunk header expected 'm=0', got %q", header)
			}
		} else {
			if header != "m=1" {
				t.Errorf("intermediate chunk header expected 'm=1', got %q", header)
			}
		}

		if len(chunkPayload) > MaxChunkPayloadSize {
			t.Errorf("chunk %d payload exceeds max size: %d > %d", i, len(chunkPayload), MaxChunkPayloadSize)
		}
		totalBase64.WriteString(chunkPayload)
	}

	decoded, err := base64.StdEncoding.DecodeString(totalBase64.String())
	if err != nil {
		t.Fatalf("failed to decode assembled base64: %v", err)
	}
	if !bytes.Equal(decoded, data) {
		t.Errorf("assembled data does not match original data")
	}
}
